import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from database import SessionLocal
from models import Booking
from utils.time_utils import format_time_for_user
from services.channel_router import send_message


# -----------------------------
# CONFIG
# -----------------------------
TEST_MODE = os.getenv("REMINDER_TEST_MODE", "false").lower() == "true"


if TEST_MODE:
    # In test mode we simulate time windows
    FIRST_WINDOW = timedelta(minutes=3)
    SECOND_WINDOW = timedelta(minutes=1)
else:
    FIRST_WINDOW = timedelta(hours=24)
    SECOND_WINDOW = timedelta(hours=2)

# -----------------------------
# HELPER: Convert booking to datetime
# -----------------------------
def booking_to_datetime(booking):
    dt_str = f"{booking.date} {booking.time}"
    dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
    return dt.replace(tzinfo=timezone.utc)


# -----------------------------
# MAIN REMINDER JOB
# -----------------------------
def run_reminder_job():
    db = SessionLocal()

    try:
        now = datetime.now(timezone.utc)

        bookings = db.query(Booking).filter(
            Booking.status == "CONFIRMED"
        ).all()

        reminders_to_send = []
        updates_made = False

        for booking in bookings:
            appointment_time = booking_to_datetime(booking)
            time_diff = appointment_time - now

            # ----------------------------------
            # 1️⃣ 24-HOUR REMINDER
            # ----------------------------------
            if (
                not booking.reminder_24h_sent and
                timedelta(0) < time_diff <= FIRST_WINDOW
            ):
                reminders_to_send.append(
                    ("24h", booking.id, booking.channel, booking.phone_number)
                )

            # ----------------------------------
            # 2️⃣ 2-HOUR REMINDER
            # ----------------------------------
            elif (
                booking.reminder_24h_sent and
                not booking.reminder_confirmed and
                not booking.reminder_2h_sent and
                timedelta(0) < time_diff <= SECOND_WINDOW
            ):
                reminders_to_send.append(
                    ("2h", booking.id, booking.channel, booking.phone_number)
                )

            # ----------------------------------
            # 3️⃣ NO-SHOW RISK FLAG
            # ----------------------------------
            if (
                time_diff <= timedelta(0) and
                not booking.reminder_confirmed and
                not booking.no_show_risk
            ):
                booking.no_show_risk = True
                updates_made = True

        # Commit ONLY risk flag updates here
        if updates_made:
            db.commit()

        db.close()  # 🔥 CLOSE BEFORE SENDING MESSAGES

        # ----------------------------------------
        # Send reminders outside DB session
        # ----------------------------------------
        for reminder_type, booking_id, channel, phone in reminders_to_send:
            db2 = SessionLocal()
            booking = db2.query(Booking).filter(Booking.id == booking_id).first()

            if not booking:
                db2.close()
                continue

            if reminder_type == "24h":
                send_message(
                    channel,
                    phone,
                    f"Reminder: You have a {booking.service} appointment "
                    f"on {booking.date} at {format_time_for_user(booking.time)}.\n"
                    "Reply YES to confirm or CANCEL to cancel."
                )
                booking.reminder_24h_sent = True

            elif reminder_type == "2h":
                send_message(
                    channel,
                    phone,
                    f"⏰ Reminder: Your {booking.service} appointment "
                    f"is today at {format_time_for_user(booking.time)}.\n"
                    "Please reply YES to confirm or CANCEL if you can’t make it."
                )
                booking.reminder_2h_sent = True

            booking.reminder_last_sent_at = datetime.now(timezone.utc)

            db2.commit()
            db2.close()

    except Exception as e:
        print("Reminder job error:", str(e))
