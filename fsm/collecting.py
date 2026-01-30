from random import choice
import uuid
from sqlalchemy.exc import IntegrityError

from models import Booking
from business_rules import validate_booking
from services.booking_service import is_slot_taken, suggest_slots_around
from utils.extraction_utils import safe_extract_date, safe_extract_time
from utils.time_utils import format_time_for_user

def handle_collecting_state(
    session,
    session_id,
    intent,
    user_text,
    data,
    db,
    now,
    business_info,
    SERVICE_QUESTIONS,
    DATE_QUESTIONS,
    TIME_QUESTIONS,
    increment_failure,
    should_handoff,
    offer_handoff,
    reset_session,
    reset_failures,
):
    if session.booking_state != "COLLECTING":
        return None

    # -----------------------------
    # SERVICE (allow override)
    # -----------------------------
    if data.get("service"):
        session.pending_service = data["service"]

    # -----------------------------
    # DATE (extract safely)
    # -----------------------------
    extracted_date = safe_extract_date(data, user_text, business_info)
    if extracted_date:
        session.pending_date = extracted_date

    # -----------------------------
    # TIME (extract safely + normalize)
    # -----------------------------
    extracted_time = safe_extract_time(data, user_text)
    if extracted_time:
        session.pending_time = extracted_time  # always HH:MM

    session.updated_at = now
    db.commit()
    
    if data.get("service") or extracted_date or extracted_time:
        reset_failures(session)
        db.commit()

    # -----------------------------
    # ASK ONLY FOR WHAT IS MISSING
    # -----------------------------
    if not session.pending_service:
        session.last_question = "service"
        db.commit()
        return {"intent": "booking_in_progress", "reply": choice(SERVICE_QUESTIONS)}

    if not session.pending_date:
        session.last_question = "date"
        db.commit()
        return {"intent": "booking_in_progress", "reply": choice(DATE_QUESTIONS)}

    if not session.pending_time:
        session.last_question = "time"
        db.commit()
        return {"intent": "booking_in_progress", "reply": choice(TIME_QUESTIONS)}

    # -----------------------------
    # BUSINESS RULES VALIDATION
    # -----------------------------
    is_valid, invalid_slot, error_msg = validate_booking(
        session.pending_date,
        session.pending_time,
        business_info
    )

    if not is_valid:
        # ❗ Treat repeated invalid inputs as failures (helps detect frustration)
        increment_failure(session, db, now)

        if should_handoff(session):
            offer_handoff(session, db, now)
            reset_session(session, now)
            db.commit()
            return {
                "intent": "handoff",
                "reply": "Sorry — I’m having trouble booking that 😅 Please call +1-XXX-XXX-XXXX 📞 and we’ll book it for you."
            }

        if invalid_slot == "time":
            session.pending_time = None
        if invalid_slot == "date":
            session.pending_date = None

        session.updated_at = now
        db.commit()
        if invalid_slot == "time" and session.pending_date:
            # suggest nearest valid slots on same day + tomorrow morning
            suggestions = suggest_slots_around(
                db=db,
                business_info=business_info,
                date_str=session.pending_date,
                time_hhmm="19:00",  # fallback anchor near closing
                count=5
            )

            same_day = suggestions.get("same_day", [])
            next_day = suggestions.get("next_day", [])

            lines = [error_msg]

            if same_day:
                lines.append(
                    "Available times today: " +
                    ", ".join([format_time_for_user(x) for x in same_day])
                )

            if next_day:
                lines.append(
                    "Or tomorrow morning: " +
                    ", ".join([format_time_for_user(x) for x in next_day])
                )

            lines.append("What time would you like?")

            return {"intent": "booking_invalid", "reply": "\n".join(lines)}

        return {"intent": "booking_invalid", "reply": error_msg}
    
    # Check slot availability
    if is_slot_taken(db, session.pending_date, session.pending_time):
        suggestions = suggest_slots_around(
            db=db,
            business_info=business_info,
            date_str=session.pending_date,
            time_hhmm=session.pending_time,
            count=5
        )

        session.pending_time = None
        session.updated_at = now
        db.commit()

        same_day = suggestions.get("same_day", [])
        next_day = suggestions.get("next_day", [])

        msg_lines = ["That time is already booked."]

        if same_day:
            pretty = ", ".join([format_time_for_user(x) for x in same_day])
            msg_lines.append(f"Here are some available times on the same day: {pretty}.")

        if next_day:
            pretty_next = ", ".join([format_time_for_user(x) for x in next_day])
            msg_lines.append(f"If you prefer tomorrow, I can do: {pretty_next}.")

        msg_lines.append("Which time works for you?")

        return {
            "intent": "booking_unavailable",
            "reply": "\n".join(msg_lines)
        }


    # -----------------------------
    # CREATE PENDING BOOKING
    # -----------------------------
    # -----------------------------
    # CLEANUP OLD PENDING BOOKINGS (avoid duplicates)
    # -----------------------------
    old_pending = (
        db.query(Booking)
        .filter(
            Booking.phone_number == session_id,
            Booking.status == "PENDING"
        )
        .all()
    )

    for b in old_pending:
        b.status = "CANCELLED"

    db.commit()

    booking_id = f"SALON-{str(uuid.uuid4())[:8].upper()}"

    booking = Booking(
        id=booking_id,
        phone_number=session_id,
        service=session.pending_service,
        date=session.pending_date,
        time=session.pending_time,  # ALWAYS HH:MM
        status="PENDING",
        created_at=now
    )

    try:
        db.add(booking)
        db.commit()
    except IntegrityError:
        db.rollback()

    session.booking_state = "CONFIRMING"
    session.last_question = None
    session.updated_at = now
    db.commit()

    return {
        "intent": "booking_pending",
        "reply": (
            f"{session.pending_service} is available on "
            f"{session.pending_date} at {format_time_for_user(session.pending_time)}.\n"
            "Would you like me to confirm the appointment?"
        )
    }