from datetime import datetime, time, timezone
import re

def parse_time(t: str) -> time:
    """
    Accepts formats like:
    - "18:30"
    - "6 pm", "6pm"
    - "6:30 pm", "6:30pm"
    - "6" (assume 06:00)
    """
    if not t:
        raise ValueError("Empty time string")

    t = t.strip().lower()

    # Normalize spaces
    t = re.sub(r"\s+", " ", t)

    # 12-hour formats with am/pm
    match_12h = re.match(r"^(\d{1,2})(?::(\d{2}))?\s*(am|pm)$", t)
    if match_12h:
        hour = int(match_12h.group(1))
        minute = int(match_12h.group(2)) if match_12h.group(2) else 0
        ampm = match_12h.group(3)

        if hour == 12:
            hour = 0
        if ampm == "pm":
            hour += 12

        return time(hour, minute)

    # 24-hour HH:MM format
    match_24h = re.match(r"^([01]?\d|2[0-3]):([0-5]\d)$", t)
    if match_24h:
        hour = int(match_24h.group(1))
        minute = int(match_24h.group(2))
        return time(hour, minute)

    # Just hour (e.g., "6")
    match_hour_only = re.match(r"^(\d{1,2})$", t)
    if match_hour_only:
        hour = int(match_hour_only.group(1))
        if 0 <= hour <= 23:
            return time(hour, 0)

    raise ValueError(f"Unsupported time format: {t}")


def validate_booking(date_str: str, time_str: str, business_info: dict):
    """
    Returns:
    (is_valid: bool, invalid_slot: "date"|"time"|None, error_msg: str|None)
    """

    # Parse business rules config
    business_hours = business_info.get("business_hours", {})
    start_time = parse_time(business_hours.get("start", "09:00"))
    end_time = parse_time(business_hours.get("end", "19:00"))
    same_day_cutoff = parse_time(business_info.get("same_day_cutoff", "17:00"))

    # Parse booking date/time
    try:
        booking_date = datetime.fromisoformat(date_str).date()
    except Exception:
        return False, "date", "That date doesn’t look valid. Please try again."

    try:
        booking_time = parse_time(time_str)
    except Exception:
        return False, "time", "That time doesn’t look valid. Please share a time like 3 PM or 15:30."

    now_utc = datetime.now(timezone.utc)
    today_utc = now_utc.date()

    # Past date check
    if booking_date < today_utc:
        return False, "date", "That date is in the past. Please choose a future date."

    # Same-day cutoff check
    if booking_date == today_utc and booking_time < same_day_cutoff:
        return False, "time", f"Same-day bookings are available only after {same_day_cutoff.strftime('%H:%M')}."

    # Business hours check
    if booking_time < start_time or booking_time > end_time:
        return False, "time", f"We're open from {start_time.strftime('%H:%M')} to {end_time.strftime('%H:%M')}."

    return True, None, None