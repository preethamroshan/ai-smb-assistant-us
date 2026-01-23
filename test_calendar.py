import os
from dotenv import load_dotenv
from datetime import datetime, timedelta
from services.calendar_service import get_calendar_service, create_calendar_event

load_dotenv()

SERVICE_ACCOUNT_PATH = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID")
TIMEZONE = os.getenv("BUSINESS_TIMEZONE", "America/New_York")

if not SERVICE_ACCOUNT_PATH or not CALENDAR_ID:
    raise ValueError("Missing GOOGLE_SERVICE_ACCOUNT_PATH or GOOGLE_CALENDAR_ID in .env")

service = get_calendar_service(SERVICE_ACCOUNT_PATH)

start = datetime.now().replace(microsecond=0)
end = start + timedelta(minutes=30)

event_id = create_calendar_event(
    service=service,
    calendar_id=CALENDAR_ID,
    title="Test Booking - Haircut",
    start_iso=start.isoformat(),
    end_iso=end.isoformat(),
    timezone=TIMEZONE
)

print("Created Event ID:", event_id)
