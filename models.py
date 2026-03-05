from sqlalchemy import Column, String, DateTime, JSON, Boolean, Integer
from database import Base
from datetime import datetime, timezone
from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import UUID
import uuid
from sqlalchemy import Text
from sqlalchemy.dialects.postgresql import JSONB

class Session(Base):
    __tablename__ = "sessions"
    booking_state = Column(String, default="IDLE")
    session_id = Column(String, primary_key=True, index=True)  # phone number
    business_id = Column(UUID(as_uuid=True), ForeignKey("businesses.id"), nullable=True)
    channel = Column(String)
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
    
    last_reminder_booking_id = Column(String, nullable=True)

    processed_message_ids = Column(JSON, default=list)
    expired_last_turn = Column(Boolean, default=False)
    expired_from_state = Column(String, nullable=True)

    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    fail_count = Column(String, default="0")   # store as string to avoid migration issues
    handoff_offered = Column(String, default="0")

class Booking(Base):
    __tablename__ = "bookings"

    id = Column(String, primary_key=True)
    business_id = Column(UUID(as_uuid=True), ForeignKey("businesses.id"), nullable=True)
    channel = Column(String, default="whatsapp")
    phone_number = Column(String, index=True)
    service = Column(String)
    date = Column(String)
    time = Column(String)

    # EXISTING
    status = Column(String)  # PENDING | CONFIRMED | CANCELLED | EXPIRED
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    confirmed_at = Column(DateTime(timezone=True), nullable=True)

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

    stripe_checkout_session_id = Column(String, nullable=True, index=True)
    stripe_payment_intent_id = Column(String, nullable=True, index=True)

    payment_link = Column(String, nullable=True)
    payment_expires_at = Column(DateTime(timezone=True), nullable=True)
    paid_at = Column(DateTime(timezone=True), nullable=True)

    # Safety / retries
    payment_attempt_count = Column(Integer, default=0)
    payment_last_error = Column(String, nullable=True)

    # Remainder fields
    reminder_24h_sent = Column(Boolean, default=False)
    reminder_2h_sent = Column(Boolean, default=False)
    reminder_confirmed = Column(Boolean, default=False)
    reminder_last_sent_at = Column(DateTime(timezone=True))
    no_show_risk = Column(Boolean, default=False)


class Business(Base):
    __tablename__ = "businesses"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    name = Column(String, nullable=False)
    type = Column(String, nullable=False)

    timezone = Column(String, nullable=False)

    slot_duration_minutes = Column(Integer, nullable=False)
    same_day_cutoff_hour = Column(Integer, nullable=True)

    business_hours = Column(JSON, nullable=False)
    services = Column(JSON, nullable=False)

    deposit_required_after_hour = Column(Integer, nullable=True)
    deposit_amount = Column(Integer, nullable=True)

    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class StripeWebhookEvent(Base):
    __tablename__ = "stripe_webhook_events"

    id = Column(Integer, primary_key=True)
    event_id = Column(String, unique=True, index=True, nullable=False)
    event_type = Column(String, nullable=False)
    payload = Column(JSON, nullable=False)
    received_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class ConversationMessage(Base):
    __tablename__ = "conversation_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    business_id = Column(UUID(as_uuid=True), ForeignKey("businesses.id"), nullable=False, index=True)
    session_id = Column(String, index=True)
    phone_number = Column(String, index=True)

    role = Column(String, nullable=False)  # user | bot | system
    message_text = Column(Text, nullable=False)

    normalized_intent = Column(String, nullable=True)
    llm_confidence = Column(String, nullable=True)

    llm_raw_json = Column(JSONB, nullable=True)

    fsm_state_before = Column(String, nullable=True)
    fsm_state_after = Column(String, nullable=True)

    is_error = Column(Boolean, default=False)
    error_type = Column(String, nullable=True)

    latency_ms = Column(Integer, nullable=True)

    model_version = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class ConversationSession(Base):
    __tablename__ = "conversation_sessions"

    session_id = Column(String, primary_key=True)
    business_id = Column(UUID(as_uuid=True), ForeignKey("businesses.id"), nullable=False, index=True)
    phone_number = Column(String, index=True)

    started_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    ended_at = Column(DateTime(timezone=True), nullable=True)

    total_messages = Column(Integer, default=0)

    booking_created = Column(Boolean, default=False)
    booking_confirmed = Column(Boolean, default=False)
    booking_cancelled = Column(Boolean, default=False)
    booking_rescheduled = Column(Boolean, default=False)

    payment_completed = Column(Boolean, default=False)
    no_show = Column(Boolean, default=False)

    fallback_count = Column(Integer, default=0)
    handoff_count = Column(Integer, default=0)

    avg_latency_ms = Column(Integer, nullable=True)

class FSMTransition(Base):
    __tablename__ = "fsm_transitions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    business_id = Column(UUID(as_uuid=True), ForeignKey("businesses.id"), nullable=False, index=True)
    session_id = Column(String, index=True)

    from_state = Column(String, nullable=False)
    to_state = Column(String, nullable=False)

    trigger_intent = Column(String, nullable=True)

    timestamp = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
