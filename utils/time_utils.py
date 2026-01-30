import re

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
    m12 = re.match(r"^(\d{1,2})(?::(\d{2}))?(am|pm)$", t)
    if m12:
        hour = int(m12.group(1))
        minute = int(m12.group(2) or 0)
        ampm = m12.group(3)

        if hour == 12:
            hour = 0
        if ampm == "pm":
            hour += 12

        return f"{hour:02d}:{minute:02d}"
    
    # 24-hour HH:MM
    m24 = re.match(r"^([01]?\d|2[0-3]):([0-5]\d)$", t)
    if m24:
        return f"{int(m24.group(1)):02d}:{int(m24.group(2)):02d}"
    
    # Hour only (e.g. "6")
    mh = re.match(r"^(\d{1,2})$", t)
    if mh:
        hour = int(mh.group(1))
        if 0 <= hour <= 23:
            return f"{hour:02d}:00"

    return None

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

def format_time_for_user(hhmm: str) -> str:
    """
    Converts "18:00" -> "6:00 PM"
    Assumes input is always HH:MM
    """
    try:
        hour, minute = map(int, hhmm.split(":"))
    except Exception:
        return hhmm

    suffix = "PM" if hour >= 12 else "AM"
    display_hour = hour % 12 or 12

    return f"{display_hour}:{minute:02d} {suffix}"