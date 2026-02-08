from fastapi import FastAPI, Request, Depends, HTTPException, Header
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
import json
import os
import requests
import uuid
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from database import engine
from models import Base
from database import SessionLocal
from services.conversation_engine import handle_message, expire_payment_if_needed
from models import Booking, Session, StripeWebhookEvent, Business
import re

from services.deposit_service import compute_deposit
from services.calendar_service import (
    get_calendar_service,
    create_calendar_event
)
from services.booking_service import (
    booking_to_event_times,
)
import stripe
from channels.whatsapp import router as whatsapp_router
from channels.sms import router as sms_router
from apscheduler.schedulers.background import BackgroundScheduler
from services.reminder_service import run_reminder_job
from channels.whatsapp import send_whatsapp_message
from services.business_loader import build_business_info
load_dotenv()

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

STRIPE_SUCCESS_URL = os.getenv("STRIPE_SUCCESS_URL")
STRIPE_CANCEL_URL = os.getenv("STRIPE_CANCEL_URL")

if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY
if not STRIPE_SECRET_KEY:
    print("⚠️ STRIPE_SECRET_KEY not set — payments disabled")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def seed_default_business():
    db = SessionLocal()
    try:
        if db.query(Business).first():
            return

        with open("business_config.json", "r") as f:
            config = json.load(f)
        
        cutoff_raw = config.get("same_day_cutoff")

        if cutoff_raw:
            # Convert "17:00" → 17
            cutoff_hour = int(str(cutoff_raw).split(":")[0])
        else:
            cutoff_hour = None

        business = Business(
            name=config["name"],
            type=config["type"],
            timezone=config["timezone"],
            slot_duration_minutes=config["slot_duration_minutes"],
            same_day_cutoff_hour=cutoff_hour,
            business_hours=config["business_hours"],
            services=config["services"],
            deposit_required_after_hour=17,  # match current logic
        )

        db.add(business)
        db.commit()
    finally:
        db.close()


app = FastAPI()
@app.on_event("startup")
def on_startup():
    seed_default_business()

GOOGLE_SERVICE_ACCOUNT_PATH = os.getenv("GOOGLE_SERVICE_ACCOUNT_PATH")
GOOGLE_CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID")

calendar_service = None
if GOOGLE_SERVICE_ACCOUNT_PATH and GOOGLE_CALENDAR_ID:
    calendar_service = get_calendar_service(GOOGLE_SERVICE_ACCOUNT_PATH)

# ----------------------------
# Constants for WhatsApp
# ----------------------------
VERIFY_TOKEN = "make_webhook_verify"   # MUST match Meta verify token

# ----------------------------
# Request model
# ----------------------------
class Message(BaseModel):
    session_id: str
    text: str
    message_id: str | None = None

# =========================================================
# CHAT ENDPOINT (UNCHANGED LOGIC)
# =========================================================
@app.post("/chat")
def chat(msg: Message, db: Session = Depends(get_db)):
    business_info = build_business_info(db)
    return handle_message(
        session_id=msg.session_id,
        user_text=msg.text,
        message_id=msg.message_id,
        channel="web",
        db=db,
        business_info=business_info,
        calendar_service=calendar_service,
        GOOGLE_CALENDAR_ID=GOOGLE_CALENDAR_ID,
    )

# =========================================================
# PAYMENTS — STRIPE CHECKOUT
# =========================================================
@app.post("/payments/create-checkout-session")
def create_checkout_session(booking_id: str, db: Session = Depends(get_db)):

    if not STRIPE_SECRET_KEY:
        raise HTTPException(status_code=500, detail="Stripe not configured")

    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    
    now = datetime.now(timezone.utc)
    # Auto-expire old payment attempts
    if expire_payment_if_needed(booking, db, now):
        raise HTTPException(
            status_code=400,
            detail="Payment session expired. Please start booking again."
        )
    
    # Idempotency: already paid
    if booking.payment_status == "PAID":
        return {
            "status": "already_paid",
            "message": "Payment already completed"
        }
    
    # ----------------------------------------
    # VALIDATE BOOKING IS PAYABLE
    # ----------------------------------------
    if booking.status != "PENDING":
        raise HTTPException(
            status_code=400,
            detail=f"Booking not payable (status={booking.status})"
        )

    if booking.payment_status not in {
        None,
        "REQUIRES_PAYMENT",
        "CHECKOUT_CREATED"
    }:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid payment state ({booking.payment_status})"
        )

    # Optional (but recommended): prevent expired payments
    if booking.payment_expires_at and booking.payment_expires_at < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=400,
            detail="Payment session expired"
        )

    deposit_amount = compute_deposit(
        booking.service,
        booking.date,
        booking.time
    )

    # No payment required
    if deposit_amount <= 0:
        booking.payment_required = False
        booking.payment_status = "NOT_REQUIRED"
        booking.status = "CONFIRMED"
        booking.confirmed_at = datetime.now(timezone.utc)
        
        # 🔥 Default predictive risk
        booking.no_show_risk = True
        db.commit()
        return {"status": "confirmed_without_payment"}

    try:
        checkout = stripe.checkout.Session.create(
            mode="payment",
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "product_data": {
                        "name": f"{booking.service} deposit",
                    },
                    "unit_amount": deposit_amount,
                },
                "quantity": 1,
            }],
            metadata={
                "booking_id": booking.id,
                "phone_number": booking.phone_number,
            },
            success_url=STRIPE_SUCCESS_URL,
            cancel_url=STRIPE_CANCEL_URL,
        )
    except Exception as e:
        booking.payment_last_error = str(e)
        db.commit()
        raise HTTPException(status_code=500, detail="Stripe checkout creation failed")

    booking.payment_required = True
    booking.payment_status = "CHECKOUT_CREATED"
    booking.deposit_amount_cents = deposit_amount
    booking.currency = "usd"

    booking.stripe_checkout_session_id = checkout.id
    booking.payment_link = checkout.url
    booking.payment_expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)
    booking.payment_attempt_count = (booking.payment_attempt_count or 0) + 1

    db.commit()

    return {
        "checkout_url": checkout.url,
        "expires_at": booking.payment_expires_at.isoformat()
    }

# =========================================================
# PAYMENTS — STRIPE WEBHOOK ENDPOINT
# =========================================================
@app.post("/stripe/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(None, alias="Stripe-Signature"),
    db: Session = Depends(get_db)
):
    payload = await request.body()

    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=stripe_signature,
            secret=STRIPE_WEBHOOK_SECRET,
        )
    except Exception as e:
        print("❌ Stripe webhook verification failed:", str(e))
        return {"status": "invalid_signature"}

    # Deduplicate webhook events
    if db.query(StripeWebhookEvent).filter(
        StripeWebhookEvent.event_id == event.id
    ).first():
        return {"status": "duplicate_event"}

    db.add(StripeWebhookEvent(
        event_id=event.id,
        event_type=event.type,
        payload=event.data.object
    ))
    db.commit()

    # ----------------------------------------
    # PAYMENT SUCCESS
    # ----------------------------------------
    if event.type == "checkout.session.completed":
        session = event.data.object
        booking_id = session.metadata.get("booking_id")

        booking = db.query(Booking).filter(Booking.id == booking_id).first()
        if not booking:
            return {"status": "booking_not_found"}

        # Prevent double processing
        if booking.payment_status == "PAID":
            return {"status": "duplicate_event_ignored"}

        # Ignore late webhook for expired/cancelled booking
        if booking.status != "PENDING":
            booking.payment_status = "LATE_PAYMENT"
            db.commit()
            return {"status": "late_payment_ignored"}

        booking.payment_status = "PAID"
        booking.status = "CONFIRMED"
        booking.confirmed_at = datetime.now(timezone.utc)
        booking.paid_at = datetime.now(timezone.utc)
        # 🔥 Default predictive risk
        booking.no_show_risk = True
        booking.stripe_payment_intent_id = session.payment_intent

        # Create calendar event ONLY HERE
        if calendar_service and GOOGLE_CALENDAR_ID:
            try:
                business = db.query(Business).filter(
                    Business.id == booking.business_id
                ).first()

                start_iso, end_iso = booking_to_event_times(
                    booking.date,
                    booking.time,
                    business.slot_duration_minutes,
                    business.timezone
                )

                event_title = f"{business.name} - {booking.service}"

                event_id = create_calendar_event(
                    service=calendar_service,
                    calendar_id=GOOGLE_CALENDAR_ID,
                    title=event_title,
                    start_iso=start_iso,
                    end_iso=end_iso,
                    timezone=business.timezone
                )

                booking.calendar_event_id = event_id
            except Exception as e:
                print("Calendar create failed after payment:", str(e))

        db.commit()

    return {"status": "ok"}

# =========================================================
# PAYMENTS — STATUS ENDPOINT
# =========================================================
@app.get("/payments/status/{booking_id}")
def payment_status(booking_id: str, db: Session = Depends(get_db)):
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    now = datetime.now(timezone.utc)
    expire_payment_if_needed(booking, db, now)
    return {
        "booking_id": booking.id,
        "booking_status": booking.status,
        "payment_status": booking.payment_status,
        "payment_required": booking.payment_required,
        "amount_cents": booking.deposit_amount_cents,
        "payment_link": booking.payment_link,
        "paid_at": booking.paid_at,
    }

# =========================================================
# WHATSAPP
# =========================================================
app.include_router(whatsapp_router)
# =========================================================
# SMS
# =========================================================
app.include_router(sms_router)
# =========================================================
# REMAINDER
# =========================================================
@app.on_event("startup")
def start_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(run_reminder_job, "interval", minutes=2)
    scheduler.start()
