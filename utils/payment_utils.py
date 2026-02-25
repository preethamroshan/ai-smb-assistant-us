from datetime import datetime
from models import Booking
import stripe

def refund_booking(booking: Booking):
    """
    Minimal, safe refund logic.
    Call ONLY for system-triggered refunds.
    """
    if not booking.stripe_payment_intent_id:
        return

    try:
        stripe.Refund.create(
            payment_intent=booking.stripe_payment_intent_id
        )
        booking.payment_status = "REFUNDED"
    except Exception as e:
        booking.payment_last_error = str(e)

def expire_payment_if_needed(booking: Booking, db, now: datetime) -> bool:
    """
    Expires a pending payment if timeout passed.
    Returns True if booking was expired.
    """

    # Only care about unpaid, payment-required bookings
    if booking.status != "PENDING":
        return False

    if booking.payment_status not in {
        "REQUIRES_PAYMENT",
        "CHECKOUT_CREATED"
    }:
        return False

    if not booking.payment_expires_at:
        return False

    if booking.payment_expires_at > now:
        return False

    # -----------------------------
    # EXPIRE BOOKING
    # -----------------------------
    booking.payment_status = "EXPIRED"
    booking.status = "CANCELLED"

    # Refund if money somehow got captured
    if booking.stripe_payment_intent_id:
        refund_booking(booking)

    db.commit()
    return True