from sqlalchemy import Column, String, DateTime, JSON, Boolean, Integer
from database import Base
from datetime import datetime, timezone

class Session(Base):
    __tablename__ = "sessions"
    booking_state = Column(String, default="IDLE")
    session_id = Column(String, primary_key=True, index=True)  # phone number
    last_message_id = Column(String, nullable=True)
    last_intent = Column(String, nullable=True)
    last_question = Column(String, nullable=True)

    pending_service = Column(String, nullable=True)
    pending_date = Column(String, nullable=True)
    pending_time = Column(String, nullable=True)

    pending_booking_id = Column(String, nullable=True)
    reschedule_target_booking_id = Column(String, nullable=True)
    reschedule_new_date = Column(String, nullable=True)
    reschedule_new_time = Column(String, nullable=True)

    processed_message_ids = Column(JSON, default=list)
    expired_last_turn = Column(Boolean, default=False)
    expired_from_state = Column(String, nullable=True)

    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    fail_count = Column(String, default="0")   # store as string to avoid migration issues
    handoff_offered = Column(String, default="0")

class Booking(Base):
    __tablename__ = "bookings"

    id = Column(String, primary_key=True)
    phone_number = Column(String, index=True)
    service = Column(String)
    date = Column(String)
    time = Column(String)

    # EXISTING
    status = Column(String)  # PENDING | CONFIRMED | CANCELLED | EXPIRED
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    confirmed_at = Column(DateTime, nullable=True)

    calendar_event_id = Column(String, nullable=True)
    calendar_provider = Column(String, default="google")
    calendar_last_synced_at = Column(DateTime(timezone=True), nullable=True)

    # -------------------------
    # 💳 STRIPE PAYMENT FIELDS
    # -------------------------
    payment_required = Column(Boolean, default=False, nullable=False)

    payment_status = Column(
        String,
        default="NOT_REQUIRED",
        nullable=False
        # NOT_REQUIRED | REQUIRES_PAYMENT | CHECKOUT_CREATED
        # PAID | FAILED | REFUNDED | DUPLICATE
    )

    deposit_amount_cents = Column(Integer, default=0, nullable=False)
    currency = Column(String, default="usd", nullable=False)

    # stripe_checkout_session_id = Column(String, nullable=True, index=True)
    # stripe_payment_intent_id = Column(String, nullable=True, index=True)
    # payment_provider = Column(String, default="razorpay")
    # payment_order_id = Column(String, nullable=True)   # razorpay_order_id
    # payment_payment_id = Column(String, nullable=True) # razorpay_payment_id

    payment_link = Column(String, nullable=True)
    payment_expires_at = Column(DateTime, nullable=True)
    paid_at = Column(DateTime, nullable=True)

    # Safety / retries
    payment_attempt_count = Column(Integer, default=0)
    payment_last_error = Column(String, nullable=True)

class StripeWebhookEvent(Base):
    __tablename__ = "Stripe_webhook_events"

    id = Column(Integer, primary_key=True)
    event_id = Column(String, unique=True, index=True, nullable=False)
    event_type = Column(String, nullable=False)
    payload = Column(JSON, nullable=False)
    received_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
