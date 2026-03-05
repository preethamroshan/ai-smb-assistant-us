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
from services.conversation_engine import handle_message
from utils.payment_utils import expire_payment_if_needed
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
from services.stripe_checkout import create_checkout_session_for_booking
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
print("REAL GROQ CALLED")
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

    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    
    return create_checkout_session_for_booking(booking,db)

# =========================================================
# PAYMENTS — STRIPE WEBHOOK ENDPOINT (FINAL VERSION)
# =========================================================
@app.post("/stripe/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(None, alias="Stripe-Signature"),
    db: Session = Depends(get_db)
):
    payload = await request.body()

    # -----------------------------------------------------
    # VERIFY SIGNATURE
    # -----------------------------------------------------
    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=stripe_signature,
            secret=STRIPE_WEBHOOK_SECRET,
        )
    except Exception as e:
        print("❌ Stripe webhook verification failed:", str(e))
        return {"status": "invalid_signature"}

    # -----------------------------------------------------
    # IDEMPOTENCY — DEDUPE EVENTS
    # -----------------------------------------------------
    existing = db.query(StripeWebhookEvent).filter(
        StripeWebhookEvent.event_id == event.id
    ).first()

    if existing:
        return {"status": "duplicate_event"}

    db.add(
        StripeWebhookEvent(
            event_id=event.id,
            event_type=event.type,
            payload=event.data.object
        )
    )
    db.commit()

    # -----------------------------------------------------
    # HANDLE CHECKOUT COMPLETION
    # -----------------------------------------------------
    if event.type == "checkout.session.completed":

        stripe_session = event.data.object

        booking_id = stripe_session.metadata.get("booking_id")
        phone_number = stripe_session.metadata.get("phone_number")

        if not booking_id:
            return {"status": "missing_booking_id"}

        booking = db.query(Booking).filter(
            Booking.id == booking_id
        ).first()

        if not booking:
            return {"status": "booking_not_found"}

        # -------------------------------------------------
        # PREVENT DOUBLE PROCESSING
        # -------------------------------------------------
        if booking.payment_status == "PAID":
            return {"status": "already_processed"}

        # -------------------------------------------------
        # HANDLE LATE PAYMENT SAFELY
        # -------------------------------------------------
        if booking.status != "PENDING":

            booking.payment_status = "LATE_PAYMENT"
            booking.payment_last_error = "Payment received after booking expired"
            db.commit()

            print(f"⚠️ Late payment ignored for booking {booking.id}")

            return {"status": "late_payment_ignored"}

        now = datetime.now(timezone.utc)

        # -------------------------------------------------
        # CONFIRM BOOKING
        # -------------------------------------------------
        booking.payment_status = "PAID"
        booking.status = "CONFIRMED"
        booking.confirmed_at = now
        booking.paid_at = now
        booking.no_show_risk = True

        booking.stripe_payment_intent_id = stripe_session.payment_intent

        print(f"✅ Booking {booking.id} marked CONFIRMED")

        # -------------------------------------------------
        # RESET FSM SESSION STATE
        # -------------------------------------------------
        session = db.query(Session).filter(
            Session.session_id == booking.phone_number
        ).first()

        if session:

            session.booking_state = "IDLE"

            session.pending_service = None
            session.pending_date = None
            session.pending_time = None
            session.pending_booking_id = None

            session.reschedule_target_booking_id = None
            session.reschedule_new_date = None
            session.reschedule_new_time = None

            session.updated_at = now

            print(f"✅ Session reset for {booking.phone_number}")

        # -------------------------------------------------
        # CREATE GOOGLE CALENDAR EVENT
        # -------------------------------------------------
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

            print(f"✅ Calendar event created {event_id}")

        except Exception as e:

            print("❌ Calendar create failed:", str(e))

        db.commit()

        # -------------------------------------------------
        # SEND CONFIRMATION MESSAGE TO CUSTOMER
        # -------------------------------------------------
        try:
            display_time = booking.time
            try:
                hour, minute = map(int, booking.time.split(":"))
                suffix = "AM"
                if hour >= 12:
                    suffix = "PM"
                display_hour = hour % 12
                if display_hour == 0:
                    display_hour = 12
                display_time = f"{display_hour}:{minute:02d} {suffix}"
            except:
                pass
            confirmation_message = (
                f"✅ Your appointment is confirmed!\n\n"
                f"Service: {booking.service}\n"
                f"Date: {booking.date}\n"
                f"Time: {display_time}\n"
                f"Ref ID: {booking.id}\n\n"
                f"Thank you!"
            )
            send_whatsapp_message(
                phone=booking.phone_number,
                text=confirmation_message
            )

            print(f"✅ Confirmation message sent to {booking.phone_number}")

        except Exception as e:

            print("❌ Failed to send confirmation message:", str(e))

        return {"status": "payment_confirmed"}

    # -----------------------------------------------------
    # IGNORE OTHER EVENTS SAFELY
    # -----------------------------------------------------
    return {"status": "event_ignored"}

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
scheduler = BackgroundScheduler()
@app.on_event("startup")
def start_scheduler():
    if not scheduler.running:
        scheduler.add_job(run_reminder_job, "interval", seconds=45)
        scheduler.start()
