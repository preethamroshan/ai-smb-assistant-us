from sqlalchemy import Column, String, DateTime, JSON
from database import Base
from datetime import datetime, timezone

class Session(Base):
    __tablename__ = "sessions"
    booking_state = Column(String, default="IDLE")
    session_id = Column(String, primary_key=True, index=True)  # phone number
    last_message_id = Column(String, nullable=True)
    last_intent = Column(String, nullable=True)
    
    pending_service = Column(String, nullable=True)
    pending_date = Column(String, nullable=True)
    pending_time = Column(String, nullable=True)

    processed_message_ids = Column(JSON, default=list)

    updated_at = Column(DateTime, default=datetime.now(timezone.utc))

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