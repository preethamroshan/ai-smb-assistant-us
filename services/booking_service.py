import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from models import Booking
from business_rules import parse_time

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

# =========================================================
# REF ID EXTRACTION
# =========================================================
def extract_booking_ref_id(text: str) -> str | None:
    """
    Matches: SALON-XXXXXXXX
    """
    if not text:
        return None
    m = re.search(r"\bSALON-[A-Z0-9]{8}\b", text.upper())
    return m.group(0) if m else None

# =========================================================
# CALENDAR TIME FORMATTER
# =========================================================
def booking_to_event_times(date_str: str, time_hhmm: str, duration_minutes: int, timezone_name: str):
    # date_str: "2026-01-23"
    # time_hhmm: "18:30"
    tz = ZoneInfo(timezone_name)

    dt_start = datetime.fromisoformat(f"{date_str} {time_hhmm}:00").replace(tzinfo=tz)
    
    dt_end = dt_start + timedelta(minutes=duration_minutes)

    return dt_start.isoformat(), dt_end.isoformat()