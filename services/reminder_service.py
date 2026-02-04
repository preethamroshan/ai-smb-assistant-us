from zoneinfo import ZoneInfo
from datetime import datetime, timedelta, timezone
from database import SessionLocal
from models import Booking, Session
from utils.time_utils import format_time_for_user
from services.channel_router import send_message
import os

BUSINESS_TIMEZONE = os.getenv("BUSINESS_TIMEZONE", "America/New_York")

FIRST_WINDOW = timedelta(minutes=3)
SECOND_WINDOW = timedelta(minutes=1)

def booking_to_datetime(booking):
    local_tz = ZoneInfo(BUSINESS_TIMEZONE)
    dt_str = f"{booking.date} {booking.time}"
    local_dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
    local_dt = local_dt.replace(tzinfo=local_tz)
    return local_dt.astimezone(timezone.utc)


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

            appointment_time = booking_to_datetime(booking)
            time_diff = appointment_time - now

            # ------------------------------------------------
            # 1️⃣ 24-HOUR REMINDER
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
            # 2️⃣ 2-HOUR REMINDER
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

                bind_reminder_to_session(db, booking, now)

                db.commit()
                continue

            # ------------------------------------------------
            # 3️⃣ NO-SHOW RISK TAGGING
            # ------------------------------------------------
            if (
                time_diff <= timedelta(seconds=-10)  # appointment passed
                and not booking.reminder_confirmed
                and not booking.no_show_risk
                and (booking.reminder_24h_sent or booking.reminder_2h_sent)
            ):
                booking.no_show_risk = True
                db.commit()

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
