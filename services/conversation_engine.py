import json
from datetime import datetime, timedelta, timezone
from random import choice
import os
from groq import Groq
from models import Booking, Session, Business
from sqlalchemy.orm import Session as DBSession

from prompts import build_system_prompt
from services.intent_normalizer import normalize_intent

from services.booking_service import (
    extract_booking_ref_id,
)

from services.faq_service import (
    handle_faq_reply,
    infer_faq_intent_from_text,
)

from utils.extraction_utils import safe_extract_date, safe_extract_time
from utils.time_utils import format_time_for_user, user_mentioned_time
from utils.date_utils import user_mentioned_date
from utils.datetime_utils import booking_to_datetime
from fsm.reschedule import handle_reschedule_state
from fsm.cancel import handle_cancel_confirm_state
from fsm.confirming import handle_confirming_state
from fsm.collecting import handle_collecting_state
import stripe
from dotenv import load_dotenv
load_dotenv()
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

STRIPE_SUCCESS_URL = os.getenv("STRIPE_SUCCESS_URL")
STRIPE_CANCEL_URL = os.getenv("STRIPE_CANCEL_URL")

if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY
if not STRIPE_SECRET_KEY:
    print("⚠️ STRIPE_SECRET_KEY not set — payments disabled")

COLLECTING_TIMEOUT_MINUTES = 30
CONFIRMING_TIMEOUT_MINUTES = 10
RESCHEDULE_TIMEOUT_MINUTES = 30
CANCEL_TIMEOUT_MINUTES = 10
PAYMENT_TIMEOUT_MINUTES = 15

TIME_QUESTIONS = [
    "What time works best for you?",
    "Any preferred time?",
    "Morning, afternoon, or evening?"
]

DATE_QUESTIONS = [
    "What date would you like?",
    "Which day should I book it for?"
]

SERVICE_QUESTIONS = [
    "Which service would you like to book?",
    "What service are you looking for?"
]

# Initialize Groq client
client = Groq(api_key=os.getenv("GROQ_API_KEY"))

def ensure_utc_aware(dt: datetime | None) -> datetime | None:
    """
    Ensure datetime is timezone-aware in UTC.
    If DB returns naive datetime, assume it's UTC and attach tzinfo.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

YES_WORDS = {"yes", "y", "yeah", "yep", "sure", "confirm", "ok", "okay", "please", "do it"}
NO_WORDS  = {"no", "n", "nope", "keep", "dont", "don't", "stop"}

def user_wants_to_modify_booking(intent: str | None, user_text: str) -> bool:
    if intent == "booking_modify":
        return True

    # Heuristic: if user mentions a new date/time/service while in confirming
    t = (user_text or "").lower()
    keywords = ["actually", "instead", "change", "make it", "update", "tomorrow", "today", "next"]
    if any(k in t for k in keywords):
        if user_mentioned_date(user_text) or user_mentioned_time(user_text):
            return True

    return False

def booking_continue_prompt(session: Session) -> str:
    missing = []
    if not session.pending_service:
        missing.append("service")
    if not session.pending_date:
        missing.append("date")
    if not session.pending_time:
        missing.append("time")

    if not missing:
        return "Great — please reply YES to confirm, or tell me what you’d like to change."

    if missing == ["service"]:
        return choice(SERVICE_QUESTIONS)
    if missing == ["date"]:
        return choice(DATE_QUESTIONS)
    if missing == ["time"]:
        return choice(TIME_QUESTIONS)

    return "To continue, please share the service, date, and time."

def get_int(session: Session, field: str, default: int = 0) -> int:
    val = getattr(session, field, None)
    try:
        return int(val)
    except Exception:
        return default

def set_int(session: Session, field: str, value: int):
    setattr(session, field, str(value))

def reset_failures(session: Session):
    set_int(session, "fail_count", 0)
    set_int(session, "handoff_offered", 0)

def increment_failure(session: Session, db, now: datetime):
    current = get_int(session, "fail_count", 0)
    set_int(session, "fail_count", current + 1)
    session.updated_at = now
    db.commit()

def should_handoff(session: Session) -> bool:
    fail_count = get_int(session, "fail_count", 0)
    offered = get_int(session, "handoff_offered", 0)
    return fail_count >= 3 and offered == 0

def offer_handoff(session: Session, db, now: datetime):
    set_int(session, "handoff_offered", 1)
    session.updated_at = now
    db.commit()

def apply_session_timeout_reset(session, now, db):
    """
    Resets FSM if expired and stores 'expired_last_turn' + 'expired_from_state'
    so we can show a good UX message on the next user message.
    """
    if is_session_expired(session, now):
        prev_state = session.booking_state

        reset_session(session, now)

        session.expired_last_turn = True
        session.expired_from_state = prev_state

        db.commit()
        return True, prev_state

    return False, None

def clear_expired_flags(session, db):
    if getattr(session, "expired_last_turn", False):
        session.expired_last_turn = False
        session.expired_from_state = None
        db.commit()

def handle_expired_session_ux(session, intent, user_text, db):
    """
    If session expired last turn AND user was mid-booking,
    return a friendly response (only once) before normal routing.
    Otherwise return None.
    """

    if not getattr(session, "expired_last_turn", False):
        return None

    prev_state = getattr(session, "expired_from_state", None)

    # Only show expiry message if user was mid-booking
    if prev_state not in {"COLLECTING", "CONFIRMING"}:
        clear_expired_flags(session, db)
        return None

    # Case 1: user says YES/NO after timeout -> they were trying to confirm/cancel
    if intent in {"booking_confirm", "booking_cancel"} or user_text.strip().lower() in {"yes", "no"}:
        clear_expired_flags(session, db)
        return {
            "intent": "session_expired",
            "reply": (
                "Welcome back 🙂 Your previous booking session expired, so I couldn’t confirm it.\n"
                "Please send the service + date + time again (example: 'Facial tomorrow at 6:30pm')."
            )
        }

    # Case 2: user asks FAQs / status / human -> don't mention expiry, just continue
    if intent in {"faq_hours", "faq_address", "faq_services", "faq_pricing", "booking_status", "talk_to_human"}:
        clear_expired_flags(session, db)
        return None

    # Case 3: user starts booking again -> let flow continue, but clear flags
    if intent in {"booking_request", "booking_modify"}:
        clear_expired_flags(session, db)
        return None

    # Case 4: unclear message after timeout -> tell them it expired
    if intent in {"fallback", "inquiry"}:
        clear_expired_flags(session, db)
        return {
            "intent": "session_expired",
            "reply": (
                "Welcome back 🙂 Our previous booking session expired.\n"
                "What would you like to book today?"
            )
        }

    # Default: clear and continue
    clear_expired_flags(session, db)
    return None

def is_session_expired(session: Session, now: datetime) -> bool:
    if not session.updated_at:
        return False

    last = ensure_utc_aware(session.updated_at)
    now = ensure_utc_aware(now)

    delta = now - last

    if session.booking_state == "COLLECTING":
        return delta > timedelta(minutes=COLLECTING_TIMEOUT_MINUTES)

    if session.booking_state == "CONFIRMING":
        return delta > timedelta(minutes=CONFIRMING_TIMEOUT_MINUTES)

    if session.booking_state in {"RESCHEDULE_COLLECTING", "RESCHEDULE_CONFIRM"}:
        return delta > timedelta(minutes=RESCHEDULE_TIMEOUT_MINUTES)

    if session.booking_state == "CANCEL_CONFIRM":
        return delta > timedelta(minutes=CANCEL_TIMEOUT_MINUTES)

    return False

def reset_session(session: Session, now: datetime):
    session.booking_state = "IDLE"
    session.last_question = None

    session.pending_service = None
    session.pending_date = None
    session.pending_time = None

    session.pending_booking_id = None

    session.reschedule_target_booking_id = None
    session.reschedule_new_date = None
    session.reschedule_new_time = None

    session.updated_at = now
    session.failure_count = 0
    session.handoff_offered = False

# =========================================================
# PAYMENT HELPERS
# =========================================================

def refund_booking(booking: Booking):
    """
    Minimal, safe refund logic.
    Call ONLY for system-triggered refunds.
    """
    if not booking.stripe_payment_intent_id:
        return

    try:
        stripe.Refund.create(
            payment_intent=booking.stripe_payment_intent_id
        )
        booking.payment_status = "REFUNDED"
    except Exception as e:
        booking.payment_last_error = str(e)

def expire_payment_if_needed(booking: Booking, db, now: datetime) -> bool:
    """
    Expires a pending payment if timeout passed.
    Returns True if booking was expired.
    """

    # Only care about unpaid, payment-required bookings
    if booking.status != "PENDING":
        return False

    if booking.payment_status not in {
        "REQUIRES_PAYMENT",
        "CHECKOUT_CREATED"
    }:
        return False

    if not booking.payment_expires_at:
        return False

    if booking.payment_expires_at > now:
        return False

    # -----------------------------
    # EXPIRE BOOKING
    # -----------------------------
    booking.payment_status = "EXPIRED"
    booking.status = "CANCELLED"

    # Refund if money somehow got captured
    if booking.stripe_payment_intent_id:
        refund_booking(booking)

    db.commit()
    return True

def handle_message(
    session_id: str,
    user_text: str,
    message_id: str | None,
    channel: str,
    db: DBSession,
    business_info: dict,
    calendar_service=None,
    GOOGLE_CALENDAR_ID=None,
):
    session_id = session_id
    user_text = user_text.strip()
    now = datetime.now(timezone.utc)

    if not session_id:
        return {"intent": "error", "reply": "Something went wrong. Please try again."}

    # --------------------------------------------------
    # FETCH / CREATE SESSION
    # --------------------------------------------------
    session = db.query(Session).filter(Session.session_id == session_id).first()
    business = db.query(Business).filter(Business.is_active == True).first()

    if not session:
        session = Session(
            session_id=session_id,
            booking_state="IDLE",
            processed_message_ids=[],
            business_id=business.id
        )
        db.add(session)
        db.commit()
        db.refresh(session)
    
    session.channel = channel
    db.commit()

    # --------------------------------------------------
    # FSM TIMEOUT RESET
    # --------------------------------------------------
    apply_session_timeout_reset(session, now, db)

    # --------------------------------------------------
    # IDEMPOTENCY
    # --------------------------------------------------
    session.processed_message_ids = session.processed_message_ids or []
    if message_id and message_id in session.processed_message_ids:
        return {"intent": "ignored", "reply": None}

    if message_id:
        session.processed_message_ids.append(message_id)
        session.processed_message_ids = session.processed_message_ids[-20:]
        db.commit()

    # --------------------------------------------------
    # LLM — ALWAYS PARSE FIRST
    # --------------------------------------------------
    completion = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[
            {"role": "system", "content": build_system_prompt(business_info)},
            {"role": "user", "content": user_text}
        ],
        temperature=0.2
    )

    try:
        data = json.loads(completion.choices[0].message.content)
    except Exception:
        increment_failure(session, db, now)

        if should_handoff(session):
            offer_handoff(session, db, now)
            reset_session(session, now)
            db.commit()
            return {
                "intent": "handoff",
                "reply": "Sorry — I’m having trouble understanding 😅 Would you like to speak to a human? Please call +1-XXX-XXX-XXXX 📞"
            }

        return {"intent": "fallback", "reply": "Sorry, I didn’t quite catch that. Could you rephrase?"}


    intent = data.get("intent")
    intent = normalize_intent(
        raw_intent=intent,
        user_text=user_text,
        session=session,
        db=db
    )
    expiry_reply = handle_expired_session_ux(session, intent, user_text, db)
    if expiry_reply:
        return expiry_reply

    if intent == "fallback":
        increment_failure(session, db, now)

        if should_handoff(session):
            offer_handoff(session, db, now)
            reset_session(session, now)
            db.commit()
            return {
                "intent": "handoff",
                "reply": "Sorry — I’m still not getting that 😅 Would you like to speak to a human? Please call +1-XXX-XXX-XXXX 📞"
            }

    # --------------------------------------------------
    # FALLBACK FAQ ROUTING IF MODEL RETURNS "inquiry"
    # --------------------------------------------------
    if intent == "inquiry":
        guessed = infer_faq_intent_from_text(user_text)
        if guessed:
            intent = guessed

    # --------------------------------------------------
    # MIXED INTENTS: FAQ SHOULD NOT BREAK FSM
    # --------------------------------------------------
    if intent in {"faq_hours", "faq_address", "faq_services", "faq_pricing"}:
        faq = handle_faq_reply(intent, business_info)
        reset_failures(session)
        db.commit()

        # If user is in the middle of booking, answer + continue booking
        if session.booking_state in {"COLLECTING", "CONFIRMING"}:
            session.updated_at = now
            db.commit()
            return {
                "intent": intent,
                "reply": f"{faq}\n\n{booking_continue_prompt(session)}"
            }

        # If idle, just answer normally
        return {"intent": intent, "reply": faq}

    # --------------------------------------------------
    # HUMAN HANDOFF
    # --------------------------------------------------
    if intent == "talk_to_human":
        reset_session(session, now)
        reset_failures(session)
        db.commit()
        return {
            "intent": "talk_to_human",
            "reply": "Sure — please call the salon at +1-XXX-XXX-XXXX 📞 (or reply with your name and we’ll have someone contact you)."
        }
    # --------------------------------------------------
    # BOOKING STATUS
    # --------------------------------------------------
    if intent == "booking_status":
        latest = (
            db.query(Booking)
            .filter(Booking.phone_number == session_id)
            .order_by(Booking.created_at.desc())
            .first()
        )
        reset_failures(session)
        db.commit()
        if not latest:
            return {"intent": "booking_status", "reply": "I don’t see any bookings yet. Would you like to make one?"}

        return {
            "intent": "booking_status",
            "reply": (
                f"Your latest booking:\n"
                f"Service: {latest.service}\n"
                f"Date: {latest.date}\n"
                f"Time: {format_time_for_user(latest.time)}\n"
                f"Status: {latest.status}\n"
                f"Ref ID: {latest.id}"
            )
        }
    # --------------------------------------------------
    # REMINDER REPLY INTERCEPTOR (NON-FSM)
    # --------------------------------------------------
    if session.last_reminder_booking_id:

        booking = (
            db.query(Booking)
            .filter(
                Booking.id == session.last_reminder_booking_id,
                Booking.phone_number == session_id,
                Booking.status == "CONFIRMED"
            )
            .first()
        )

        # If booking no longer valid, clear reminder context
        if not booking:
            session.last_reminder_booking_id = None
            db.commit()
            # continue normal routing

        else:
            text_lower = user_text.lower().strip()

            # -------------------------------
            # YES → mark reminder confirmed
            # -------------------------------
            if intent == "booking_confirm" or text_lower in YES_WORDS:

                # 🔥 Calculate appointment time
                appointment_time = booking_to_datetime(db, booking)

                # 🔥 Block late confirmations
                if now > appointment_time:
                    session.last_reminder_booking_id = None
                    db.commit()

                    return {
                        "intent": "late_confirmation",
                        "reply": "That appointment time has already passed. Would you like to book a new slot?"
                    }
                            
                # 🔥 Only clear risk after 2h confirmation
                if booking.reminder_2h_sent:
                    booking.no_show_risk = False
                # ✅ Valid confirmation
                booking.reminder_confirmed = True
                session.last_reminder_booking_id = None
                session.updated_at = now
                reset_failures(session)
                db.commit()

                return {
                    "intent": "reminder_confirmed",
                    "reply": "Perfect 👍 We’ll see you then!"
                }

            # -------------------------------
            # CANCEL → move to cancel flow
            # -------------------------------
            if intent == "booking_cancel" or text_lower in {"cancel"}:

                # Clear reminder context
                session.last_reminder_booking_id = None

                # Move into your existing cancel FSM
                session.booking_state = "CANCEL_CONFIRM"
                session.pending_booking_id = booking.id
                session.updated_at = now
                db.commit()

                return {
                    "intent": "cancel_confirmation",
                    "reply": (
                        f"Just to confirm — cancel your {booking.service} appointment on "
                        f"{booking.date} at {format_time_for_user(booking.time)}?\n"
                        "Reply YES to cancel or NO to keep it."
                    )
                }

            # -------------------------------
            # Any other message → ignore reminder context
            # Let normal FSM handle it
            # -------------------------------
            session.last_reminder_booking_id = None
            db.commit()

    # --------------------------------------------------
    # CANCEL CONFIRM STATE
    # --------------------------------------------------
    cancel_response = handle_cancel_confirm_state(
        session=session,
        session_id=session_id,
        intent=intent,
        user_text=user_text,
        db=db,
        now=now,
        calendar_service=calendar_service,
        GOOGLE_CALENDAR_ID=GOOGLE_CALENDAR_ID,
        YES_WORDS=YES_WORDS,
        NO_WORDS=NO_WORDS,
        reset_failures=reset_failures,
    )

    if cancel_response:
        return cancel_response

    # --------------------------------------------------
    # CONFIRMING STATE (PENDING BOOKINGS)
    # --------------------------------------------------
    pending_booking = (
        db.query(Booking)
        .filter(
            Booking.phone_number == session_id,
            Booking.status == "PENDING"
        )
        .first()
    )
    if pending_booking:
        if expire_payment_if_needed(pending_booking, db, now):
            session.booking_state = "IDLE"
            session.updated_at = now
            db.commit()

            return {
                "intent": "payment_expired",
                "reply": (
                    "⏳ Your payment window expired, so the booking was released.\n"
                    "Would you like to try booking again?"
                )
            }
        
    confirming_response = handle_confirming_state(
        session=session,
        session_id=session_id,
        intent=intent,
        user_text=user_text,
        data=data,
        db=db,
        now=now,
        pending_booking=pending_booking,
        business_info=business_info,
        calendar_service=calendar_service,
        GOOGLE_CALENDAR_ID=GOOGLE_CALENDAR_ID,
        user_wants_to_modify_booking=user_wants_to_modify_booking,
        reset_failures=reset_failures,
    )

    if confirming_response:
        return confirming_response

    # --------------------------------------------------
    # CANCEL FLOW (INITIATE CANCELLATION) - supports Ref ID
    # --------------------------------------------------
    if intent == "booking_cancel" and session.booking_state == "IDLE":
        # reset any in-progress booking collection
        session.pending_service = None
        session.pending_date = None
        session.pending_time = None
        session.last_question = None

        ref_id = extract_booking_ref_id(user_text)

        q = db.query(Booking).filter(
            Booking.phone_number == session_id,
            Booking.status == "CONFIRMED"
        )

        if ref_id:
            q = q.filter(Booking.id == ref_id)
        else:
            q = q.order_by(Booking.created_at.desc())

        booking_to_cancel = q.first()

        if not booking_to_cancel:
            return {
                "intent": "booking_cancel",
                "reply": "I couldn’t find a confirmed appointment to cancel. If you have a reference ID, please share it."
            }

        session.booking_state = "CANCEL_CONFIRM"
        session.pending_booking_id = booking_to_cancel.id
        session.updated_at = now
        reset_failures(session)
        db.commit()

        return {
            "intent": "cancel_confirmation",
            "reply": (
                f"Just to confirm — cancel your {booking_to_cancel.service} appointment on "
                f"{booking_to_cancel.date} at {format_time_for_user(booking_to_cancel.time)}?\n"
                "Reply YES to cancel or NO to keep it."
            )
        }

    # --------------------------------------------------
    # RESCHEDULE FLOW (INITIATE) - supports Ref ID
    # --------------------------------------------------
    if intent == "booking_reschedule" and session.booking_state == "IDLE":
        # reset any in-progress booking collection
        session.pending_service = None
        session.pending_date = None
        session.pending_time = None
        session.last_question = None

        ref_id = extract_booking_ref_id(user_text)

        q = db.query(Booking).filter(
            Booking.phone_number == session_id,
            Booking.status == "CONFIRMED"
        )

        if ref_id:
            q = q.filter(Booking.id == ref_id)
        else:
            q = q.order_by(Booking.created_at.desc())

        booking_to_reschedule = q.first()

        if not booking_to_reschedule:
            return {
                "intent": "booking_reschedule",
                "reply": "I couldn’t find a confirmed appointment to reschedule. If you have a reference ID, please share it."
            }

        session.booking_state = "RESCHEDULE_COLLECTING"
        session.reschedule_target_booking_id = booking_to_reschedule.id
        session.reschedule_new_date = booking_to_reschedule.date
        session.reschedule_new_time = booking_to_reschedule.time
        session.updated_at = now
        reset_failures(session)
        db.commit()
        
    # --------------------------------------------------
    # RESCHEDULE COLLECTING & CONFIRM STATE
    # --------------------------------------------------
    reschedule_response = handle_reschedule_state(
        session=session,
        session_id=session_id,
        intent=intent,
        user_text=user_text,
        data=data,
        db=db,
        now=now,
        business_info=business_info,
        calendar_service=calendar_service,
        GOOGLE_CALENDAR_ID=GOOGLE_CALENDAR_ID,
        increment_failure=increment_failure,
        should_handoff=should_handoff,
        offer_handoff=offer_handoff,
        reset_session=reset_session,
        reset_failures=reset_failures,
        DATE_QUESTIONS=DATE_QUESTIONS,
        TIME_QUESTIONS=TIME_QUESTIONS,
        YES_WORDS=YES_WORDS,
        NO_WORDS=NO_WORDS,
    )

    if reschedule_response:
        return reschedule_response

    # --------------------------------------------------
    # IDLE STATE (SMART START)
    # --------------------------------------------------
    if session.booking_state == "IDLE":

        if intent == "booking_request":

            # Try extracting everything immediately from same message
            if data.get("service"):
                session.pending_service = data["service"]

            extracted_date = safe_extract_date(data, user_text, business_info)
            if extracted_date:
                session.pending_date = extracted_date

            extracted_time = safe_extract_time(data, user_text)
            if extracted_time:
                session.pending_time = extracted_time

            session.booking_state = "COLLECTING"
            session.updated_at = now
            reset_failures(session)

            db.commit()

            # Now COLLECTING block will ask only missing info
            # So we can fall-through by NOT returning here
            # (or return a question immediately)

    # --------------------------------------------------
    # GLOBAL INTERRUPT: Cancel while COLLECTING
    # (means cancel the in-progress booking request, not a confirmed booking)
    # --------------------------------------------------
    if intent == "booking_cancel" and session.booking_state == "COLLECTING":
        session.booking_state = "IDLE"
        session.pending_service = None
        session.pending_date = None
        session.pending_time = None
        session.last_question = None
        session.updated_at = now
        reset_session(session, now)
        reset_failures(session)
        db.commit()

        return {
            "intent": "booking_cancelled",
            "reply": "Got it 👍 I’ve cancelled this booking request. Would you like to book something else?"
        }

    # --------------------------------------------------
    # COLLECTING STATE
    # --------------------------------------------------
    collecting_response = handle_collecting_state(
        session=session,
        session_id=session_id,
        intent=intent,
        user_text=user_text,
        data=data,
        db=db,
        now=now,
        business_info=business_info,
        SERVICE_QUESTIONS=SERVICE_QUESTIONS,
        DATE_QUESTIONS=DATE_QUESTIONS,
        TIME_QUESTIONS=TIME_QUESTIONS,
        increment_failure=increment_failure,
        should_handoff=should_handoff,
        offer_handoff=offer_handoff,
        reset_session=reset_session,
        reset_failures=reset_failures,
    )

    if collecting_response:
        return collecting_response

    return {
    "intent": intent or "fallback",
    "reply": data.get("reply") or f"Welcome to {business_info['name']}! How can I help you today?"
}