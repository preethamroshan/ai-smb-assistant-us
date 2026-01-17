from fastapi import FastAPI, Request, Depends
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
import json
import os
import requests
import uuid
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from groq import Groq
from prompts import build_system_prompt
from database import engine
from models import Base
from database import SessionLocal
from models import Booking
from models import Session
from sqlalchemy.exc import IntegrityError
from random import choice
import re
from business_rules import validate_booking, parse_time
import dateparser
from zoneinfo import ZoneInfo

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

load_dotenv()

app = FastAPI()
@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)

# Initialize Groq client
client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# Load business config
with open("business_config.json", "r") as f:
    business_info = json.load(f)


# ----------------------------
# Constants for WhatsApp
# ----------------------------
VERIFY_TOKEN = "make_webhook_verify"   # MUST match Meta verify token
MAKE_WEBHOOK_URL = os.getenv("make_webhook_url")

# ----------------------------
# Request model
# ----------------------------
class Message(BaseModel):
    session_id: str
    text: str
    message_id: str | None = None

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

def parse_date_us(text: str, business_info: dict) -> str | None:
    """
    Converts:
      "next monday" -> YYYY-MM-DD
      "coming tuesday" -> YYYY-MM-DD
      "tomorrow" -> YYYY-MM-DD
      "01/20/2026" -> YYYY-MM-DD
    """
    if not text:
        return None

    tz_name = business_info.get("timezone", "America/New_York")
    tz = ZoneInfo(tz_name)

    cleaned = text.strip().lower()

    # -------------------------------
    # ✅ Manual handling for weekdays
    # -------------------------------
    weekdays = {
        "monday": 0,
        "tuesday": 1,
        "wednesday": 2,
        "thursday": 3,
        "friday": 4,
        "saturday": 5,
        "sunday": 6,
    }

    base_date = datetime.now(tz).date()

    # detect phrases like: "next monday", "coming tuesday", "this friday"
    m = re.search(r"\b(next|coming|this)\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", cleaned)
    if m:
        which = m.group(1)
        day_name = m.group(2)

        target_weekday = weekdays[day_name]
        today_weekday = base_date.weekday()

        days_ahead = (target_weekday - today_weekday) % 7

        # If today is same weekday and user says "this monday" -> today
        if which == "this":
            if days_ahead == 0:
                return base_date.isoformat()
            return (base_date + timedelta(days=days_ahead)).isoformat()

        # If user says "next monday":
        # If today is Monday, next Monday should be +7 days, not today.
        if which in {"next", "coming"}:
            if days_ahead == 0:
                days_ahead = 7
            return (base_date + timedelta(days=days_ahead)).isoformat()

    # -------------------------------
    # fallback: dateparser for everything else
    # -------------------------------
    dt = dateparser.parse(
        cleaned,
        settings={
            "PREFER_DATES_FROM": "future",
            "RELATIVE_BASE": datetime.now(tz),
            "DATE_ORDER": "MDY",
            "RETURN_AS_TIMEZONE_AWARE": False,
            "STRICT_PARSING": False,
        }
    )

    if not dt:
        return None

    return dt.date().isoformat()

def infer_time_from_text(text: str) -> str | None:
    """
    Extract time only if user actually mentioned a time/bucket.
    Prevents false positives and looping.
    """
    if not text:
        return None

    t = text.lower()

    # Buckets
    if "morning" in t:
        return "10:00"
    if "afternoon" in t:
        return "14:00"
    if "evening" in t:
        return "18:00"
    if "night" in t:
        return "19:30"

    # If user contains am/pm or HH:MM or a plain hour
    if re.search(r"\b(\d{1,2})(:\d{2})?\s*(am|pm)\b", t):
        return normalize_time(text)

    if re.search(r"\b([01]?\d|2[0-3]):[0-5]\d\b", t):
        return normalize_time(text)

    if re.search(r"\b\d{1,2}\b", t):
        # This allows "at 6" or "6" to work
        return normalize_time(text)

    return None

def normalize_time(text: str) -> str | None:
    """
    Returns normalized time as HH:MM (24-hour format)
    Examples:
      "6 pm" -> "18:00"
      "6:30pm" -> "18:30"
      "15:30" -> "15:30"
      "evening" -> "18:00"
      "6" -> "06:00"
    """
    if not text:
        return None

    t = text.strip().lower()

    # Buckets
    if "morning" in t:
        return "10:00"
    if "afternoon" in t:
        return "14:00"
    if "evening" in t:
        return "18:00"
    if "night" in t:
        return "19:30"

    # Remove spaces: "6 pm" -> "6pm"
    t = t.replace(" ", "")

    # 12-hour formats: 6pm / 6:30pm / 12am / 12:15am
    match_12h = re.match(r"^(\d{1,2})(?::(\d{2}))?(am|pm)$", t)
    if match_12h:
        hour = int(match_12h.group(1))
        minute = int(match_12h.group(2)) if match_12h.group(2) else 0
        ampm = match_12h.group(3)

        if hour == 12:
            hour = 0
        if ampm == "pm":
            hour += 12

        return f"{hour:02d}:{minute:02d}"

    # 24-hour HH:MM
    match_24h = re.match(r"^([01]?\d|2[0-3]):([0-5]\d)$", t)
    if match_24h:
        hour = int(match_24h.group(1))
        minute = int(match_24h.group(2))
        return f"{hour:02d}:{minute:02d}"

    # Hour only (e.g. "6")
    match_hour_only = re.match(r"^(\d{1,2})$", t)
    if match_hour_only:
        hour = int(match_hour_only.group(1))
        if 0 <= hour <= 23:
            return f"{hour:02d}:00"

    return None


def format_time_for_user(hhmm: str) -> str:
    """
    Converts "18:00" -> "6:00 PM"
    Assumes input is always HH:MM
    """
    try:
        hour, minute = map(int, hhmm.split(":"))
    except Exception:
        return hhmm  # fallback

    suffix = "AM"
    if hour >= 12:
        suffix = "PM"

    display_hour = hour % 12
    if display_hour == 0:
        display_hour = 12

    return f"{display_hour}:{minute:02d} {suffix}"

YES_WORDS = {"yes", "y", "yeah", "yep", "sure", "confirm", "ok", "okay", "please", "do it"}
NO_WORDS  = {"no", "n", "nope", "keep", "dont", "don't", "stop"}


def user_mentioned_date(text: str) -> bool:
    if not text:
        return False

    t = text.lower().strip()

    weekdays = ["monday","tuesday","wednesday","thursday","friday","saturday","sunday"]
    if any(d in t for d in weekdays):
        return True

    if any(x in t for x in ["today", "tomorrow", "day after tomorrow", "next week", "this week"]):
        return True

    # "next monday", "coming tuesday", "this friday"
    if any(x in t for x in ["next ", "coming ", "this "]):
        return True

    # numeric date formats like 01/20/2026 or 1-20-2026
    if re.search(r"\b\d{1,2}[/-]\d{1,2}([/-]\d{2,4})?\b", t):
        return True

    # month names
    if re.search(r"\b(jan(uary)?|feb(ruary)?|mar(ch)?|apr(il)?|may|jun(e)?|jul(y)?|aug(ust)?|sep(t)?(ember)?|oct(ober)?|nov(ember)?|dec(ember)?)\b", t):
        return True

    return False

def user_mentioned_time(text: str) -> bool:
    """
    Returns True only if message likely contains time info.
    Prevents extracting random numbers like "2 services".
    """
    if not text:
        return False

    t = text.lower().strip()

    # Buckets
    if any(word in t for word in ["morning", "afternoon", "evening", "night"]):
        return True

    # am/pm
    if re.search(r"\b(\d{1,2})(:\d{2})?\s*(am|pm)\b", t):
        return True

    # HH:MM 24-hour
    if re.search(r"\b([01]?\d|2[0-3]):[0-5]\d\b", t):
        return True

    # hour only allowed ONLY if context exists: "at 6", "around 6", "by 6"
    if re.search(r"\b(at|around|by)\s*\d{1,2}\b", t):
        return True

    # hour only allowed if message is just "6"
    if re.fullmatch(r"\d{1,2}", t):
        return True

    return False

def safe_extract_date(data: dict, user_text: str, business_info: dict) -> str | None:
    """
    Extract date only when:
    - LLM provided date OR
    - user message clearly mentions a date
    """

    # 1) Prefer LLM structured date
    llm_date = (data or {}).get("date")
    if llm_date:
        parsed = parse_date_us(str(llm_date), business_info)
        if parsed:
            return parsed

    # 2) If user mentioned a date, extract only the date phrase
    if user_mentioned_date(user_text):
        phrase = extract_date_phrase(user_text)   # ✅ IMPORTANT
        parsed = parse_date_us(phrase, business_info)
        if parsed:
            return parsed

        # 3) fallback: try full text
        return parse_date_us(user_text, business_info)

    return None

def safe_extract_time(data: dict, user_text: str) -> str | None:
    """
    Extract time only when:
    - LLM provided time OR
    - user message clearly mentions a time
    """
    llm_time = data.get("time")
    if llm_time:
        return normalize_time(llm_time)

    if user_mentioned_time(user_text):
        return infer_time_from_text(user_text)

    return None

def extract_booking_ref_id(text: str) -> str | None:
    """
    Matches: SALON-XXXXXXXX
    """
    if not text:
        return None
    m = re.search(r"\bSALON-[A-Z0-9]{8}\b", text.upper())
    return m.group(0) if m else None

def is_slot_taken(db, date: str, time: str) -> bool:
    existing = (
        db.query(Booking)
        .filter(
            Booking.date == date,
            Booking.time == time,
            Booking.status.in_(["PENDING", "CONFIRMED"])
        )
        .first()
    )
    return existing is not None

def suggest_slots_around(
    db,
    business_info: dict,
    date_str: str,
    time_hhmm: str,
    count: int = 5
) -> dict:
    """
    Suggest slots earlier + later around the requested time.
    If business hours are over, also suggest next-day morning slots.

    Returns:
      {
        "same_day": ["17:30", "18:00", "18:30"],
        "next_day": ["09:00", "09:30"]
      }
    """
    slot_minutes = int(business_info.get("slot_duration_minutes", 30))
    start = business_info.get("business_hours", {}).get("start", "09:00")
    end = business_info.get("business_hours", {}).get("end", "19:00")

    start_t = parse_time(start)
    end_t = parse_time(end)
    base_t = parse_time(time_hhmm)

    def to_minutes(tt):
        return tt.hour * 60 + tt.minute

    def to_hhmm(m):
        h = m // 60
        mm = m % 60
        return f"{h:02d}:{mm:02d}"

    start_min = to_minutes(start_t)
    end_min = to_minutes(end_t)
    base_min = to_minutes(base_t)

    # clamp base within business hours for searching
    base_min = max(start_min, min(base_min, end_min))

    # gather candidates around base: base, -1, +1, -2, +2, ...
    offsets = [0]
    step = 1
    while len(offsets) < 50:
        offsets.append(-step)
        offsets.append(step)
        step += 1

    same_day = []
    seen = set()

    for off in offsets:
        if len(same_day) >= count:
            break

        candidate_min = base_min + (off * slot_minutes)

        if candidate_min < start_min or candidate_min > end_min:
            continue

        hhmm = to_hhmm(candidate_min)

        if hhmm in seen:
            continue
        seen.add(hhmm)

        if not is_slot_taken(db, date_str, hhmm):
            same_day.append(hhmm)

    # If requested time is near/after closing OR no same-day suggestions found
    # suggest next-day morning slots
    next_day = []
    if base_min >= end_min or len(same_day) == 0:
        try:
            next_date = (datetime.fromisoformat(date_str).date() + timedelta(days=1)).isoformat()
        except Exception:
            next_date = None

        if next_date:
            morning_min = start_min
            attempts = 0
            while len(next_day) < min(3, count) and attempts < 20:
                hhmm = to_hhmm(morning_min)
                if not is_slot_taken(db, next_date, hhmm):
                    next_day.append(hhmm)
                morning_min += slot_minutes
                attempts += 1

    return {"same_day": same_day, "next_day": next_day}

def extract_date_phrase(text: str) -> str:
    """
    Extracts date-like phrase from user text.
    Example:
      "Book haircut next monday at 3 pm" -> "next monday"
      "next tuesday at 6 pm" -> "next tuesday"
      "tomorrow evening" -> "tomorrow"
    """
    t = text.lower()

    patterns = [
        r"\b(today|tomorrow|day after tomorrow)\b",
        r"\bnext\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
        r"\bcoming\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
        r"\bthis\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
        r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
        r"\bnext week\b",
    ]

    for p in patterns:
        m = re.search(p, t)
        if m:
            return m.group(0)

    return text

# =========================================================
# CHAT ENDPOINT (UNCHANGED LOGIC)
# =========================================================
@app.post("/chat")
def chat(msg: Message, db: Session = Depends(get_db)):
    session_id = msg.session_id
    user_text = msg.text.strip()
    now = datetime.now(timezone.utc)

    if not session_id:
        return {"intent": "error", "reply": "Something went wrong. Please try again."}

    # --------------------------------------------------
    # FETCH / CREATE SESSION
    # --------------------------------------------------
    session = db.query(Session).filter(Session.session_id == session_id).first()
    if not session:
        session = Session(
            session_id=session_id,
            booking_state="IDLE",
            processed_message_ids=[]
        )
        db.add(session)
        db.commit()
        db.refresh(session)

    # --------------------------------------------------
    # IDEMPOTENCY
    # --------------------------------------------------
    session.processed_message_ids = session.processed_message_ids or []
    if msg.message_id and msg.message_id in session.processed_message_ids:
        return {"intent": "ignored", "reply": None}

    if msg.message_id:
        session.processed_message_ids.append(msg.message_id)
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
        return {"intent": "fallback", "reply": "Sorry, I didn’t quite catch that."}

    intent = data.get("intent")

    # --------------------------------------------------
    # CANCEL CONFIRM STATE
    # --------------------------------------------------
    if session.booking_state == "CANCEL_CONFIRM":

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

            session.booking_state = "IDLE"
            session.pending_booking_id = None
            session.updated_at = now
            db.commit()

            return {
                "intent": "booking_cancelled",
                "reply": "Done — your appointment has been cancelled."
            }

        if intent == "booking_cancel" or user_text.lower() in NO_WORDS:
            session.booking_state = "IDLE"
            session.pending_booking_id = None
            session.updated_at = now
            db.commit()

            return {
                "intent": "cancel_aborted",
                "reply": "No worries — your appointment is still confirmed."
            }

        return {
            "intent": "cancel_confirmation",
            "reply": "Please reply YES to cancel or NO to keep your appointment."
        }


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

    if session.booking_state == "CONFIRMING" and pending_booking:
        if intent == "booking_confirm" or user_text.lower() in {"yes", "confirm", "ok", "sure"}:
            pending_booking.status = "CONFIRMED"
            pending_booking.confirmed_at = now

            session.booking_state = "IDLE"
            session.pending_service = None
            session.pending_date = None
            session.pending_time = None
            session.last_question = None
            session.updated_at = now
            db.commit()

            return {
                "intent": "booking_confirmed",
                "reply": (
                    f"✅ Your appointment is confirmed!\n"
                    f"Ref ID: {pending_booking.id}\n"
                    f"See you on {pending_booking.date} at {format_time_for_user(pending_booking.time)}."
                )
            }

        if intent == "booking_cancel" or user_text.lower() in {"no", "cancel"}:
            pending_booking.status = "CANCELLED"

            session.booking_state = "IDLE"
            session.pending_service = None
            session.pending_date = None
            session.pending_time = None
            session.last_question = None
            session.updated_at = now
            db.commit()

            return {
                "intent": "booking_cancelled",
                "reply": "No problem — the booking has been cancelled."
            }

        return {
            "intent": "awaiting_confirmation",
            "reply": "Please reply YES to confirm or NO to cancel."
        }

    # --------------------------------------------------
    # CANCEL FLOW (INITIATE CANCELLATION) - supports Ref ID
    # --------------------------------------------------
    if intent == "booking_cancel" and session.booking_state == "IDLE":

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
        session.reschedule_new_date = None
        session.reschedule_new_time = None
        session.updated_at = now
        db.commit()

        return {
            "intent": "reschedule_start",
            "reply": (
                f"Sure — you’re booked for {booking_to_reschedule.service} on "
                f"{booking_to_reschedule.date} at {format_time_for_user(booking_to_reschedule.time)}.\n"
                "What new date and time would you like?"
            )
        }

    # --------------------------------------------------
    # RESCHEDULE COLLECTING STATE
    # --------------------------------------------------
    if session.booking_state == "RESCHEDULE_COLLECTING":

        extracted_date = safe_extract_date(data, user_text, business_info)
        if extracted_date:
            session.reschedule_new_date = extracted_date

        extracted_time = safe_extract_time(data, user_text)
        if extracted_time:
            session.reschedule_new_time = extracted_time

        session.updated_at = now
        db.commit()

        if not session.reschedule_new_date:
            return {"intent": "reschedule_in_progress", "reply": choice(DATE_QUESTIONS)}

        if not session.reschedule_new_time:
            return {"intent": "reschedule_in_progress", "reply": choice(TIME_QUESTIONS)}

        # Validate business rules
        is_valid, invalid_slot, error_msg = validate_booking(
            session.reschedule_new_date,
            session.reschedule_new_time,
            business_info
        )

        if not is_valid:
            if invalid_slot == "time":
                session.reschedule_new_time = None
            if invalid_slot == "date":
                session.reschedule_new_date = None

            session.updated_at = now
            db.commit()
            return {"intent": "reschedule_invalid", "reply": error_msg}

        # Check slot availability
        if is_slot_taken(db, session.reschedule_new_date, session.reschedule_new_time):
            suggestions = suggest_slots_around(
                db=db,
                business_info=business_info,
                date_str=session.reschedule_new_date,
                time_hhmm=session.reschedule_new_time,
                count=5
            )

            session.reschedule_new_time = None
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
                "intent": "reschedule_unavailable",
                "reply": "\n".join(msg_lines)
            }


        session.booking_state = "RESCHEDULE_CONFIRM"
        session.updated_at = now
        db.commit()

        return {
            "intent": "reschedule_confirm",
            "reply": (
                f"Got it — reschedule to {session.reschedule_new_date} at "
                f"{format_time_for_user(session.reschedule_new_time)}?\n"
                "Reply YES to confirm or NO to cancel."
            )
        }

    # --------------------------------------------------
    # RESCHEDULE CONFIRM STATE
    # --------------------------------------------------
    if session.booking_state == "RESCHEDULE_CONFIRM":

        if intent == "booking_confirm" or user_text.lower() in YES_WORDS:

            booking_to_update = (
                db.query(Booking)
                .filter(
                    Booking.phone_number == session_id,
                    Booking.id == session.reschedule_target_booking_id,
                    Booking.status == "CONFIRMED"
                )
                .first()
            )

            if not booking_to_update:
                session.booking_state = "IDLE"
                session.reschedule_target_booking_id = None
                session.reschedule_new_date = None
                session.reschedule_new_time = None
                session.updated_at = now
                db.commit()
                return {
                    "intent": "reschedule_failed",
                    "reply": "I couldn’t find that appointment anymore. Please try again."
                }

            booking_to_update.date = session.reschedule_new_date
            booking_to_update.time = session.reschedule_new_time

            session.booking_state = "IDLE"
            session.reschedule_target_booking_id = None
            session.reschedule_new_date = None
            session.reschedule_new_time = None
            session.updated_at = now
            db.commit()

            return {
                "intent": "booking_rescheduled",
                "reply": (
                    f"✅ Perfect — you’re all set for {booking_to_update.date} at "
                    f"{format_time_for_user(booking_to_update.time)}."
                )
            }

        if intent == "booking_cancel" or user_text.lower() in NO_WORDS:
            session.booking_state = "IDLE"
            session.reschedule_target_booking_id = None
            session.reschedule_new_date = None
            session.reschedule_new_time = None
            session.updated_at = now
            db.commit()

            return {
                "intent": "reschedule_cancelled",
                "reply": "No problem — I didn’t make any changes."
            }

        return {
            "intent": "reschedule_confirm",
            "reply": "Please reply YES to confirm the reschedule or NO to cancel."
        }

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
            db.commit()

            # Now COLLECTING block will ask only missing info
            # So we can fall-through by NOT returning here
            # (or return a question immediately)

    # --------------------------------------------------
    # COLLECTING STATE
    # --------------------------------------------------
    if session.booking_state == "COLLECTING":

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
    return {
    "intent": intent or "fallback",
    "reply": data.get("reply") or f"Welcome to {business_info['name']}! How can I help you today?"
}

# =========================================================
# WHATSAPP WEBHOOK — VERIFICATION (GET)
# =========================================================
@app.get("/whatsapp/webhook")
async def verify_whatsapp_webhook(request: Request):
    params = request.query_params

    if (
        params.get("hub.mode") == "subscribe"
        and params.get("hub.verify_token") == VERIFY_TOKEN
    ):
        return PlainTextResponse(params.get("hub.challenge"))

    return PlainTextResponse("Verification failed", status_code=403)


# =========================================================
# WHATSAPP WEBHOOK — INCOMING MESSAGES (POST)
# =========================================================

@app.post("/whatsapp/webhook")
async def whatsapp_webhook(payload: dict):
    try:
        entry = payload["entry"][0]
        change = entry["changes"][0]
        value = change["value"]

        # 👇 IGNORE non-message webhooks
        if "messages" not in value:
            return {"status": "ignored_non_message"}
        
        message = value["messages"][0]

        message_id = message["id"]  # 👈 IMPORTANT

        if message.get("type") != "text":
            print(f"[NON_TEXT_IGNORED] msg_id={message_id} type={message.get('type')}")
            return {"status": "non_text_ignored"}
        
        print(f"[WHATSAPP_INCOMING] msg_id={message_id} from={message['from']}")

        clean_payload = {
            "session_id": message["from"],   # 👈 USE PHONE AS SESSION
            "text": message["text"]["body"],
            "message_id": message["id"]
        }

        resp = requests.post(MAKE_WEBHOOK_URL, json=clean_payload, timeout=5)
        print(f"[MAKE_FORWARD] session={clean_payload['session_id']} status={resp.status_code}")
    except Exception as e:
        print("Webhook parse error:", e)

    return {"status": "ok"}
