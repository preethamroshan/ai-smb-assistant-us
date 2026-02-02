from models import Booking

RESCHEDULE_VERBS = {
    "reschedule", "change", "modify", "move", "update", "shift"
}

def normalize_intent(
    raw_intent: str | None,
    user_text: str,
    session,
    db
) -> str | None:
    """
    Deterministically correct LLM intent
    using session state + booking data.
    """

    text = (user_text or "").lower().strip()

    # -------------------------------------------------
    # 1️⃣ If mid-reschedule → always treat as reschedule
    # -------------------------------------------------
    if session.booking_state in {
        "RESCHEDULE_COLLECTING",
        "RESCHEDULE_CONFIRM"
    }:
        return "booking_reschedule"

    # -------------------------------------------------
    # 2️⃣ If user says change/modify AND has confirmed booking
    #    → treat as reschedule even if LLM said booking_modify
    # -------------------------------------------------
    if raw_intent in {"booking_modify", "booking_request"}:
        if any(v in text for v in RESCHEDULE_VERBS):

            confirmed = (
                db.query(Booking)
                .filter(
                    Booking.phone_number == session.session_id,
                    Booking.status == "CONFIRMED"
                )
                .first()
            )

            if confirmed:
                return "booking_reschedule"

    # -------------------------------------------------
    # 3️⃣ If IDLE + booking_modify but no pending booking
    #    → likely reschedule
    # -------------------------------------------------
    if raw_intent == "booking_modify":
        if session.booking_state == "IDLE":

            confirmed = (
                db.query(Booking)
                .filter(
                    Booking.phone_number == session.session_id,
                    Booking.status == "CONFIRMED"
                )
                .first()
            )

            if confirmed:
                return "booking_reschedule"

    # -------------------------------------------------
    # 4️⃣ Otherwise keep original
    # -------------------------------------------------
    return raw_intent
