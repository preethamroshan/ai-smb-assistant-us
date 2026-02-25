import stripe
import os
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException
from dotenv import load_dotenv
from models import Booking
from services.deposit_service import compute_deposit
from utils.payment_utils import expire_payment_if_needed

load_dotenv()

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")

STRIPE_SUCCESS_URL = os.getenv("STRIPE_SUCCESS_URL")

STRIPE_CANCEL_URL = os.getenv("STRIPE_CANCEL_URL")

PAYMENT_TIMEOUT_MINUTES = 15


if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY


def create_checkout_session_for_booking(booking, db):

    if not STRIPE_SECRET_KEY:
        raise HTTPException(status_code=500, detail="Stripe not configured")

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