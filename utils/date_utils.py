import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import dateparser

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
        r"\b(day after tomorrow|tomorrow|today)\b",
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