from utils.extraction_utils import safe_extract_date, safe_extract_time
from utils.time_utils import format_time_for_user
from services.booking_service import (
    is_slot_taken,
    suggest_slots_around,
    booking_to_event_times,
)
from services.calendar_service import update_calendar_event
from business_rules import validate_booking
from models import Booking


def handle_reschedule_state(
    session,
    session_id,
    intent,
    user_text,
    data,
    db,
    now,
    business_info,
    calendar_service,
    GOOGLE_CALENDAR_ID,
    increment_failure,
    should_handoff,
    offer_handoff,
    reset_session,
    reset_failures,
    DATE_QUESTIONS,
    TIME_QUESTIONS,
    YES_WORDS,
    NO_WORDS,
):
    # ==================================================
    # RESCHEDULE COLLECTING (PROPOSAL MODEL)
    # ==================================================
    if session.booking_state == "RESCHEDULE_COLLECTING":

        # Load original booking
        original_booking = (
            db.query(Booking)
            .filter(
                Booking.phone_number == session_id,
                Booking.id == session.reschedule_target_booking_id,
                Booking.status == "CONFIRMED",
            )
            .first()
        )

        if not original_booking:
            reset_session(session, now)
            db.commit()
            return {
                "intent": "reschedule_failed",
                "reply": "I couldn’t find that appointment anymore. Please try again.",
            }

        # -----------------------------
        # APPLY PATCH (PROPOSAL UPDATE)
        # -----------------------------
        extracted_date = safe_extract_date(data, user_text, business_info)
        extracted_time = safe_extract_time(data, user_text)

        user_changed = False

        if extracted_date:
            session.reschedule_new_date = extracted_date
            user_changed = True

        if extracted_time:
            session.reschedule_new_time = extracted_time
            user_changed = True

        # If user didn't change anything, ask clearly
        if not user_changed:
            return {
                "intent": "reschedule_in_progress",
                "reply": "What would you like to change — date, time, or both?",
            }

        session.updated_at = now
        db.commit()

        # -----------------------------
        # VALIDATE PROPOSAL
        # -----------------------------
        is_valid, invalid_slot, error_msg = validate_booking(
            session.reschedule_new_date,
            session.reschedule_new_time,
            business_info,
        )

        if not is_valid:
            increment_failure(session, db, now)

            if should_handoff(session):
                offer_handoff(session, db, now)
                reset_session(session, now)
                db.commit()
                return {
                    "intent": "handoff",
                    "reply": "Sorry — I’m having trouble rescheduling 😅 Please call +1-XXX-XXX-XXXX 📞 and we’ll help you.",
                }

            # DO NOT RESET FIELDS — keep proposal intact
            return {
                "intent": "reschedule_invalid",
                "reply": error_msg,
            }

        # -----------------------------
        # CHECK AVAILABILITY
        # -----------------------------
        if is_slot_taken(
            db, session.reschedule_new_date, session.reschedule_new_time
        ):
            suggestions = suggest_slots_around(
                db=db,
                business_info=business_info,
                date_str=session.reschedule_new_date,
                time_hhmm=session.reschedule_new_time,
                count=5,
            )

            same_day = suggestions.get("same_day", [])
            next_day = suggestions.get("next_day", [])

            msg_lines = ["That time is already booked."]

            if same_day:
                pretty = ", ".join(
                    [format_time_for_user(x) for x in same_day]
                )
                msg_lines.append(
                    f"Here are some available times on the same day: {pretty}."
                )

            if next_day:
                pretty_next = ", ".join(
                    [format_time_for_user(x) for x in next_day]
                )
                msg_lines.append(
                    f"If you prefer tomorrow, I can do: {pretty_next}."
                )

            msg_lines.append("Which time works for you?")

            return {
                "intent": "reschedule_unavailable",
                "reply": "\n".join(msg_lines),
            }

        # -----------------------------
        # DIFF-AWARE CONFIRMATION
        # -----------------------------
        changes = []

        if original_booking.date != session.reschedule_new_date:
            changes.append(f"date → {session.reschedule_new_date}")

        if original_booking.time != session.reschedule_new_time:
            changes.append(
                f"time → {format_time_for_user(session.reschedule_new_time)}"
            )

        if not changes:
            return {
                "intent": "reschedule_no_change",
                "reply": "You're already booked for that same slot 🙂 Would you like to keep it as is?",
            }

        session.booking_state = "RESCHEDULE_CONFIRM"
        session.updated_at = now
        db.commit()
        reset_failures(session)

        return {
            "intent": "reschedule_confirm",
            "reply": (
                "Update appointment: "
                + ", ".join(changes)
                + "?\nReply YES to confirm or NO to cancel."
            ),
        }

    # ==================================================
    # RESCHEDULE CONFIRM (ALLOW PATCH AGAIN)
    # ==================================================
    if session.booking_state == "RESCHEDULE_CONFIRM":

        # Allow modifications inside confirm
        extracted_date = safe_extract_date(data, user_text, business_info)
        extracted_time = safe_extract_time(data, user_text)

        if extracted_date or extracted_time:
            session.booking_state = "RESCHEDULE_COLLECTING"
            session.updated_at = now
            db.commit()
            return None  # fall back to collecting logic

        # -----------------------------
        # CONFIRM YES
        # -----------------------------
        if intent == "booking_confirm" or user_text.lower() in YES_WORDS:

            booking_to_update = (
                db.query(Booking)
                .filter(
                    Booking.phone_number == session_id,
                    Booking.id == session.reschedule_target_booking_id,
                    Booking.status == "CONFIRMED",
                )
                .first()
            )

            if not booking_to_update:
                reset_session(session, now)
                db.commit()
                return {
                    "intent": "reschedule_failed",
                    "reply": "I couldn’t find that appointment anymore.",
                }

            booking_to_update.date = session.reschedule_new_date
            booking_to_update.time = session.reschedule_new_time

            # Update Google Calendar
            if (
                calendar_service
                and GOOGLE_CALENDAR_ID
                and booking_to_update.calendar_event_id
            ):
                try:
                    start_iso, end_iso = booking_to_event_times(
                        date_str=booking_to_update.date,
                        time_hhmm=booking_to_update.time,
                        duration_minutes=business_info[
                            "slot_duration_minutes"
                        ],
                        timezone_name=business_info["timezone"],
                    )

                    event_title = (
                        f"{business_info['name']} - {booking_to_update.service}"
                    )

                    update_calendar_event(
                        service=calendar_service,
                        calendar_id=GOOGLE_CALENDAR_ID,
                        event_id=booking_to_update.calendar_event_id,
                        title=event_title,
                        start_iso=start_iso,
                        end_iso=end_iso,
                        timezone=business_info["timezone"],
                    )
                except Exception as e:
                    print("Calendar update failed:", str(e))

            reset_session(session, now)
            db.commit()

            return {
                "intent": "booking_rescheduled",
                "reply": (
                    f"✅ Perfect — you're all set for {booking_to_update.date} at "
                    f"{format_time_for_user(booking_to_update.time)}."
                ),
            }

        # -----------------------------
        # CONFIRM NO
        # -----------------------------
        if intent == "booking_cancel" or user_text.lower() in NO_WORDS:
            reset_session(session, now)
            db.commit()
            return {
                "intent": "reschedule_cancelled",
                "reply": "No problem — I didn’t make any changes.",
            }

        return {
            "intent": "reschedule_confirm",
            "reply": "Please reply YES to confirm the reschedule or NO to cancel.",
        }

    return None
