from google.oauth2 import service_account
from googleapiclient.discovery import build


SCOPES = ["https://www.googleapis.com/auth/calendar"]


def get_calendar_service(service_account_path: str):
    creds = service_account.Credentials.from_service_account_file(
        service_account_path,
        scopes=SCOPES
    )
    return build("calendar", "v3", credentials=creds)


def create_calendar_event(service, calendar_id: str, title: str, start_iso: str, end_iso: str, timezone: str):
    event = {
        "summary": title,
        "start": {"dateTime": start_iso, "timeZone": timezone},
        "end": {"dateTime": end_iso, "timeZone": timezone},
    }

    created = service.events().insert(calendarId=calendar_id, body=event).execute()
    return created["id"]


def update_calendar_event(service, calendar_id: str, event_id: str, title: str, start_iso: str, end_iso: str, timezone: str):
    event = service.events().get(calendarId=calendar_id, eventId=event_id).execute()

    event["summary"] = title
    event["start"] = {"dateTime": start_iso, "timeZone": timezone}
    event["end"] = {"dateTime": end_iso, "timeZone": timezone}

    updated = service.events().update(calendarId=calendar_id, eventId=event_id, body=event).execute()
    return updated["id"]


def delete_calendar_event(service, calendar_id: str, event_id: str):
    service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
    return True
