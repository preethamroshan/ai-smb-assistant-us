import os
import requests
from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse
from database import SessionLocal
from services.conversation_engine import handle_message

router = APIRouter()

VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "make_webhook_verify")

def send_whatsapp_message(phone: str, text: str):
    if not text:
        return

    url = f"https://graph.facebook.com/v18.0/{os.getenv('WHATSAPP_PHONE_NUMBER_ID')}/messages"

    headers = {
        "Authorization": f"Bearer {os.getenv('WHATSAPP_ACCESS_TOKEN')}",
        "Content-Type": "application/json",
    }

    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "text",
        "text": {"body": text}
    }

    response = requests.post(url, headers=headers, json=payload)

    if response.status_code != 200:
        print("❌ WhatsApp send failed:", response.text)
    else:
        print("✅ WhatsApp message sent")

# =========================================================
# WHATSAPP WEBHOOK — VERIFICATION (GET)
# =========================================================
@router.get("/whatsapp/webhook")
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
@router.post("/whatsapp/webhook")
async def whatsapp_webhook(request: Request):

    payload = await request.json()

    try:
        entry = payload["entry"][0]
        change = entry["changes"][0]
        value = change["value"]

        if "messages" not in value:
            return {"status": "ignored_non_message"}

        message = value["messages"][0]

        if message.get("type") != "text":
            return {"status": "non_text_ignored"}

        phone = message["from"]
        text = message["text"]["body"]
        message_id = message["id"]

        print(f"[WHATSAPP_INCOMING] {phone}: {text}")

        db = SessionLocal()

        from app import business_info, calendar_service, GOOGLE_CALENDAR_ID

        response = handle_message(
            session_id=phone,
            user_text=text,
            message_id=message_id,
            channel="whatsapp",
            db=db,
            business_info=business_info,
            calendar_service=calendar_service,
            GOOGLE_CALENDAR_ID=GOOGLE_CALENDAR_ID,
        )

        db.close()

        reply_text = response.get("reply")

        if reply_text:
            send_whatsapp_message(phone, reply_text)

    except Exception as e:
        print("Webhook error:", e)

    return {"status": "ok"}
