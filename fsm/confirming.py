from services.deposit_service import compute_deposit
from services.calendar_service import create_calendar_event
from services.booking_service import booking_to_event_times
from utils.extraction_utils import safe_extract_date, safe_extract_time
from utils.time_utils import format_time_for_user

def handle_confirming_state(
    session,
    session_id,
    intent,
    user_text,
    data,
    db,
    now,
    pending_booking,
    business_info,
    calendar_service,
    GOOGLE_CALENDAR_ID,
    user_wants_to_modify_booking,
    reset_failures,
):
    if not pending_booking or session.booking_state != "CONFIRMING":
        return None

    # ---------------------------------------------
    # MID-BOOKING CHANGE HANDLING (NEW)
    # ---------------------------------------------
    if intent == "booking_modify" or user_wants_to_modify_booking(intent, user_text):

        # Apply safe extraction updates
        if data.get("service"):
            session.pending_service = data["service"]

        extracted_date = safe_extract_date(data, user_text, business_info)
        if extracted_date:
            session.pending_date = extracted_date

        extracted_time = safe_extract_time(data, user_text)
        if extracted_time:
            session.pending_time = extracted_time

        # Cancel old pending booking record (avoid stale pending rows)
        pending_booking.status = "CANCELLED"

        # Move back to collecting so it re-validates and re-creates pending booking
        session.booking_state = "COLLECTING"
        session.updated_at = now
        db.commit()

        # After switching to COLLECTING, let app.py continue to COLLECTING block
        if not (session.pending_service and session.pending_date and session.pending_time):
            return {
                "intent": "booking_modify",
                "reply": "Got it — updating your booking. 👍"
            }

        # If all fields already present, just fall through
        return None

    # If we changed state to COLLECTING above, skip CONFIRMING actions
    if session.booking_state == "CONFIRMING":

        # ---------------------------------------------
        # CONFIRM YES
        # ---------------------------------------------
        if intent == "booking_confirm" or user_text.lower() in {"yes", "confirm", "ok", "sure"}:

            deposit_amount = compute_deposit(
                pending_booking.service,
                pending_booking.date,
                pending_booking.time
            )

            # --------------------------------------------------
            # CASE 1: DEPOSIT REQUIRED → DO NOT CONFIRM
            # --------------------------------------------------
            if deposit_amount > 0:

                pending_booking.payment_required = True
                pending_booking.payment_status = "REQUIRES_PAYMENT"
                pending_booking.deposit_amount_cents = deposit_amount
                pending_booking.currency = "usd"

                session.booking_state = "PAYMENT_PENDING"
                session.updated_at = now
                db.commit()

                return {
                    "intent": "payment_required",
                    "reply": (
                        f"To confirm your {pending_booking.service} appointment on "
                        f"{pending_booking.date} at {format_time_for_user(pending_booking.time)}, "
                        "a small deposit is required.\n\n"
                        "I’ll send you a secure payment link next."
                    )
                }

            # --------------------------------------------------
            # CASE 2: NO DEPOSIT → CONFIRM IMMEDIATELY (OLD LOGIC)
            # --------------------------------------------------
            pending_booking.status = "CONFIRMED"
            pending_booking.confirmed_at = now

            # Google Calendar create (UNCHANGED)
            if calendar_service and GOOGLE_CALENDAR_ID:
                try:
                    start_iso, end_iso = booking_to_event_times(
                        date_str=pending_booking.date,
                        time_hhmm=pending_booking.time,
                        duration_minutes=business_info["slot_duration_minutes"],
                        timezone_name=business_info["timezone"]
                    )

                    event_title = f"{business_info['name']} - {pending_booking.service}"
                    event_id = create_calendar_event(
                        service=calendar_service,
                        calendar_id=GOOGLE_CALENDAR_ID,
                        title=event_title,
                        start_iso=start_iso,
                        end_iso=end_iso,
                        timezone=business_info["timezone"]
                    )

                    pending_booking.calendar_event_id = event_id
                except Exception as e:
                    print("Calendar create failed:", str(e))

            session.booking_state = "IDLE"
            session.pending_service = None
            session.pending_date = None
            session.pending_time = None
            session.last_question = None
            session.updated_at = now
            reset_failures(session)
            db.commit()

            return {
                "intent": "booking_confirmed",
                "reply": (
                    f"✅ Your appointment is confirmed!\n"
                    f"Ref ID: {pending_booking.id}\n"
                    f"See you on {pending_booking.date} at "
                    f"{format_time_for_user(pending_booking.time)}."
                )
            }


        # ---------------------------------------------
        # CONFIRM NO
        # ---------------------------------------------
        if intent == "booking_cancel" or user_text.lower() in {"no", "cancel"}:
            pending_booking.status = "CANCELLED"

            session.booking_state = "IDLE"
            session.pending_service = None
            session.pending_date = None
            session.pending_time = None
            session.last_question = None
            session.updated_at = now
            reset_failures(session)
            db.commit()

            return {
                "intent": "booking_cancelled",
                "reply": "No problem — the booking has been cancelled."
            }

        return {
            "intent": "awaiting_confirmation",
            "reply": "Please reply YES to confirm, or tell me what you’d like to change (service/date/time)."
        }