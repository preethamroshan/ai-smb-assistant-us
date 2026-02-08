from zoneinfo import ZoneInfo
from datetime import datetime, timezone
from models import Business

def booking_to_datetime(db, booking):
    business = db.query(Business).filter(
        Business.id == booking.business_id
    ).first()

    local_tz = ZoneInfo(business.timezone)

    dt_str = f"{booking.date} {booking.time}"
    local_dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
    local_dt = local_dt.replace(tzinfo=local_tz)

    return local_dt.astimezone(timezone.utc)
