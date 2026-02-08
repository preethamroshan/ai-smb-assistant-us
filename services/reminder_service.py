from zoneinfo import ZoneInfo
from datetime import datetime, timedelta, timezone
from database import SessionLocal
from models import Booking, Session
from utils.time_utils import format_time_for_user
from services.channel_router import send_message
import os
from models import Business
from utils.datetime_utils import booking_to_datetime

FIRST_WINDOW = timedelta(minutes=3)
SECOND_WINDOW = timedelta(minutes=1)

def run_reminder_job():

    db = SessionLocal()
    now = datetime.now(timezone.utc)

    try:
        confirmed_bookings = (
            db.query(Booking)
            .filter(Booking.status == "CONFIRMED")
            .all()
        )

        for booking in confirmed_bookings:

            appointment_time = booking_to_datetime(db, booking)
            time_diff = appointment_time - now

            # ------------------------------------------------
            # 1️⃣ FIRST REMINDER (24h in prod)
            # ------------------------------------------------
            if (
                not booking.reminder_24h_sent
                and timedelta(0) < time_diff <= FIRST_WINDOW
            ):

                send_message(
                    booking.channel,
                    booking.phone_number,
                    (
                        f"Reminder: You have a {booking.service} appointment "
                        f"on {booking.date} at {format_time_for_user(booking.time)}.\n"
                        "Reply YES to confirm or CANCEL to cancel."
                    )
                )

                booking.reminder_24h_sent = True
                booking.reminder_last_sent_at = now

                bind_reminder_to_session(db, booking, now)
                db.commit()
                continue

            # ------------------------------------------------
            # 2️⃣ SECOND REMINDER (2h in prod)
            # ------------------------------------------------
            if (
                not booking.reminder_2h_sent
                and timedelta(0) < time_diff <= SECOND_WINDOW
            ):

                send_message(
                    booking.channel,
                    booking.phone_number,
                    (
                        f"⏰ Reminder: Your {booking.service} appointment "
                        f"is coming up at {format_time_for_user(booking.time)}.\n"
                        "Reply YES to confirm or CANCEL if needed."
                    )
                )

                booking.reminder_2h_sent = True
                booking.reminder_last_sent_at = now

                # 🔥 Reset confirmation for final attendance signal
                booking.reminder_confirmed = False

                bind_reminder_to_session(db, booking, now)
                db.commit()
                continue

    except Exception as e:
        print("Reminder job error:", str(e))

    finally:
        db.close()


def bind_reminder_to_session(db, booking, now):
    session = (
        db.query(Session)
        .filter(Session.session_id == booking.phone_number)
        .first()
    )

    if session:
        session.last_reminder_booking_id = booking.id
        session.updated_at = now
