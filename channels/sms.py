import os
from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse
from twilio.twiml.messaging_response import MessagingResponse
from database import SessionLocal
from services.conversation_engine import handle_message
from twilio.rest import Client
from services.business_loader import build_business_info

router = APIRouter()

@router.post("/sms/webhook")
async def sms_webhook(request: Request):

    form = await request.form()

    phone = form.get("From")
    text = form.get("Body")
    message_id = form.get("MessageSid")

    print(f"[SMS_INCOMING] {phone}: {text}")

    db = SessionLocal()
    from app import calendar_service, GOOGLE_CALENDAR_ID
    business_info = build_business_info(db)
    response = handle_message(
        session_id=phone,
        user_text=text,
        message_id=message_id,
        channel="sms",
        db=db,
        business_info=business_info,
        calendar_service=calendar_service,
        GOOGLE_CALENDAR_ID=GOOGLE_CALENDAR_ID,
    )

    db.close()

    reply_text = response.get("reply") or ""

    # Build Twilio XML response
    twiml = MessagingResponse()
    twiml.message(reply_text)

    return PlainTextResponse(str(twiml), media_type="application/xml")


def send_sms_message(phone: str, text: str):
    client = Client(
        os.getenv("TWILIO_ACCOUNT_SID"),
        os.getenv("TWILIO_AUTH_TOKEN")
    )

    client.messages.create(
        body=text,
        from_=os.getenv("TWILIO_PHONE_NUMBER"),
        to=phone
    )
