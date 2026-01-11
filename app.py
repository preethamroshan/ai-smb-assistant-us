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
from prompts import SYSTEM_PROMPT
from database import engine
from models import Base
from database import SessionLocal
from models import Booking
from models import Session
from sqlalchemy.exc import IntegrityError

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
MAKE_WEBHOOK_URL = "https://hook.eu1.make.com/bnris781v64i4icxwfdk39m1x9lw1wqn"

# ----------------------------
# Request model
# ----------------------------
class Message(BaseModel):
    session_id: str
    text: str
    message_id: str | None = None


# =========================================================
# CHAT ENDPOINT (UNCHANGED LOGIC)
# =========================================================
@app.post("/chat")
@app.post("/chat")
def chat(msg: Message, db: Session = Depends(get_db)):
    session_id = msg.session_id
    user_text = msg.text.lower().strip()
    now = datetime.now(timezone.utc)

    if not session_id:
        return {
            "intent": "error",
            "reply": "Something went wrong bro 😅 Please try again."
        }

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
    if msg.message_id:
        if msg.message_id in (session.processed_message_ids or []):
            return {"intent": "ignored", "reply": None}

        session.processed_message_ids = (
            (session.processed_message_ids or []) + [msg.message_id]
        )[-20:]
        db.commit()

    # --------------------------------------------------
    # CHECK PENDING BOOKING (CONFIRMING STATE)
    # --------------------------------------------------
    pending_booking = (
        db.query(Booking)
        .filter(
            Booking.phone_number == session_id,
            Booking.status == "PENDING"
        )
        .first()
    )

    CONFIRM_WORDS = {"yes", "haan", "confirm", "ok", "yeah"}
    CANCEL_WORDS = {"no", "nah", "cancel"}

    if session.booking_state == "CONFIRMING" and pending_booking:
        if user_text in CONFIRM_WORDS:
            pending_booking.status = "CONFIRMED"
            pending_booking.confirmed_at = now

            # RESET SESSION
            session.booking_state = "IDLE"
            session.pending_service = None
            session.pending_date = None
            session.pending_time = None
            session.updated_at = now

            db.commit()

            return {
                "intent": "booking_confirmed",
                "reply": (
                    f"✅ Booking confirmed bro!\n"
                    f"Ref ID: {pending_booking.id}\n"
                    f"See you {pending_booking.date} {pending_booking.time} 👍"
                )
            }

        if user_text in CANCEL_WORDS:
            pending_booking.status = "CANCELLED"

            session.booking_state = "IDLE"
            session.pending_service = None
            session.pending_date = None
            session.pending_time = None
            session.updated_at = now

            db.commit()

            return {
                "intent": "booking_cancelled",
                "reply": "No worries bro 👍 Booking cancelled."
            }

        return {
            "intent": "awaiting_confirmation",
            "reply": "Please reply YES to confirm or NO to cancel 🙂"
        }

    # --------------------------------------------------
    # CALL LLM (UNDERSTANDING ONLY)
    # --------------------------------------------------
    completion = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[
            {
                "role": "system",
                "content": SYSTEM_PROMPT.format(business_info=business_info)
            },
            {
                "role": "user",
                "content": msg.text
            }
        ],
        temperature=0.2
    )

    try:
        data = json.loads(completion.choices[0].message.content)
    except Exception:
        return {
            "intent": "fallback",
            "reply": "Sorry bro 😅 I didn’t understand that."
        }

    intent = data.get("intent")

    # --------------------------------------------------
    # IDLE STATE
    # --------------------------------------------------
    if session.booking_state == "IDLE":
        if intent == "booking_request":
            session.booking_state = "COLLECTING"
            session.updated_at = now
            db.commit()

            return {
                "intent": "booking_start",
                "reply": "Sure bro 🙂 Which service do you want to book?"
            }

        # normal non-booking response
        return {
            "intent": intent,
            "reply": data.get("reply")
        }

    # --------------------------------------------------
    # COLLECTING STATE
    # --------------------------------------------------
    if session.booking_state == "COLLECTING":

        if data.get("service") and not session.pending_service:
            session.pending_service = data["service"]

        if data.get("date") and not session.pending_date:
            session.pending_date = data["date"]

        if data.get("time") and not session.pending_time:
            session.pending_time = data["time"]

        session.updated_at = now
        db.commit()

        if not session.pending_service:
            return {
                "intent": "booking_in_progress",
                "reply": "Which service do you want to book bro? 🙂"
            }

        if not session.pending_date:
            return {
                "intent": "booking_in_progress",
                "reply": "For which date bro? 🙂"
            }

        if not session.pending_time:
            return {
                "intent": "booking_in_progress",
                "reply": "What time should I book it bro? 🙂"
            }

        # --------------------------------------------------
        # ALL INFO COLLECTED → CREATE PENDING BOOKING
        # --------------------------------------------------
        booking_id = f"SALON-{str(uuid.uuid4())[:8].upper()}"

        booking = Booking(
            id=booking_id,
            phone_number=session_id,
            service=session.pending_service,
            date=session.pending_date,
            time=session.pending_time,
            status="PENDING",
            created_at=now
        )

        try:
            db.add(booking)
            db.commit()
        except IntegrityError:
            db.rollback()

        session.booking_state = "CONFIRMING"
        session.updated_at = now
        db.commit()

        return {
            "intent": "booking_pending",
            "reply": (
                f"Yes bro 👍 {session.pending_service} is available "
                f"{session.pending_date} {session.pending_time}.\n"
                "Shall I confirm the booking?"
            )
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
