from models import Booking
from services.calendar_service import delete_calendar_event

def handle_cancel_confirm_state(
    session,
    session_id,
    intent,
    user_text,
    db,
    now,
    calendar_service,
    GOOGLE_CALENDAR_ID,
    YES_WORDS,
    NO_WORDS,
    reset_failures,
):
    if session.booking_state != "CANCEL_CONFIRM":
        return None

    if intent == "booking_confirm" or user_text.lower() in YES_WORDS:

        booking_to_cancel = (
            db.query(Booking)
            .filter(
                Booking.phone_number == session_id,
                Booking.id == session.pending_booking_id,
                Booking.status == "CONFIRMED"
            )
            .first()
        )

        if booking_to_cancel:
            booking_to_cancel.status = "CANCELLED"

        if (
            booking_to_cancel
            and calendar_service
            and GOOGLE_CALENDAR_ID
            and booking_to_cancel.calendar_event_id
        ):
            try:
                delete_calendar_event(
                    service=calendar_service,
                    calendar_id=GOOGLE_CALENDAR_ID,
                    event_id=booking_to_cancel.calendar_event_id
                )
            except Exception as e:
                print("Calendar delete failed:", str(e))

        session.booking_state = "IDLE"
        session.pending_booking_id = None
        session.updated_at = now
        reset_failures(session)
        db.commit()

        return {
            "intent": "booking_cancelled",
            "reply": "Done — your appointment has been cancelled."
        }

    if intent == "booking_cancel" or user_text.lower() in NO_WORDS:
        session.booking_state = "IDLE"
        session.pending_booking_id = None
        session.updated_at = now
        reset_failures(session)
        db.commit()

        return {
            "intent": "cancel_aborted",
            "reply": "No worries — your appointment is still confirmed."
        }

    return {
        "intent": "cancel_confirmation",
        "reply": "Please reply YES to cancel or NO to keep your appointment."
    }
