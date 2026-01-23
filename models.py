from sqlalchemy import Column, String, DateTime, JSON, Boolean
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
    status = Column(String)  # PENDING | CONFIRMED | CANCELLED
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    confirmed_at = Column(DateTime, nullable=True)
    calendar_event_id = Column(String, nullable=True)
    calendar_provider = Column(String, default="google")
    calendar_last_synced_at = Column(DateTime(timezone=True), nullable=True)
