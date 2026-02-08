# 📞 AI Receptionist Engine for US SMBs

## Overview

This project is a production-grade AI-powered receptionist engine designed for US small and medium businesses (SMBs) such as salons, clinics, and local service providers.

It automates:

- Appointment booking  
- Confirmations  
- Cancellations  
- Rescheduling  
- Payments (Stripe deposits)  
- Automated reminders  
- No-show risk tracking  

The system is backend-controlled using a deterministic FSM (Finite State Machine) architecture for reliability and correctness.

---

# 🎯 Mission

Reduce no-shows.  
Automate front-desk workflows.  
Increase operational efficiency for SMBs.

---

# ✨ Core Capabilities

## 🗓 Intelligent Booking Flow

- Multi-turn conversation handling
- Service → Date → Time collection
- Mid-booking modification support
- Same-day cutoff enforcement
- Business hours validation
- Timezone-aware booking logic

---

## 🔁 FSM-Based Conversation Engine

Explicit state machine:

- IDLE  
- COLLECTING  
- CONFIRMING  
- PAYMENT_PENDING  
- RESCHEDULE_COLLECTING  
- RESCHEDULE_CONFIRM  
- CANCEL_CONFIRM  

Prevents:

- Intent drift  
- Looping  
- Inconsistent confirmations  
- LLM hallucination effects  

---

## 💳 Stripe Deposit System

- Conditional deposit logic
- Prime-time deposit rules
- Weekend deposit enforcement
- Payment expiration handling
- Secure Stripe Checkout
- Webhook-based confirmation
- Late-payment protection

---

## ⏰ Smart Reminder System

- 24-hour reminder  
- 2-hour reminder  
- Confirmation tracking  
- Reminder interception logic  
- No-show risk auto-tagging  
- Post-appointment session cleanup  

No-show risk logic supports future analytics and behavior modeling.

---

## 🧠 AI Usage Philosophy

LLM is used strictly for:

- Intent classification  
- Slot extraction (service/date/time)  

All business decisions are backend-driven.

No LLM memory dependency.

Deterministic control > generative guessing.

---

# 🏗 Architecture

User (WhatsApp / SMS)
↓
Webhook (FastAPI)
↓
Intent Extraction (Groq LLaMA 3.1)
↓
Intent Normalizer
↓
FSM Engine
↓
PostgreSQL (Sessions, Bookings, Businesses)
↓
Stripe / Google Calendar
↓
Response to User

---

# 🛠 Tech Stack

- Backend: FastAPI  
- Database: PostgreSQL  
- ORM: SQLAlchemy 2.0  
- Migrations: Alembic  
- LLM: Groq (LLaMA 3.1)  
- Payments: Stripe  
- Messaging: WhatsApp Cloud API + Twilio SMS  
- Scheduler: APScheduler  
- Calendar: Google Calendar API  

---

# 🧩 Data Models

Core tables:

- `businesses`
- `sessions`
- `bookings`
- `stripe_webhook_events`

Supports multi-business architecture.

---

# 🔐 Production Safety

- Idempotent message handling  
- Webhook deduplication  
- Payment state validation  
- Expiry handling  
- Session timeout resets  
- No-show analytics tagging  
- Migration-controlled schema evolution  

---

# 🚀 Local Setup

## 1️⃣ Create `.env`

Configure:

DATABASE_URL=
STRIPE_SECRET_KEY=
STRIPE_WEBHOOK_SECRET=
WHATSAPP_ACCESS_TOKEN=
WHATSAPP_PHONE_NUMBER_ID=
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
GOOGLE_SERVICE_ACCOUNT_PATH=
GOOGLE_CALENDAR_ID=

---

## 2️⃣ Run Migrations

alembic upgrade head

---

## 3️⃣ Start Server

uvicorn app:app --reload

---

# 📈 Future Roadmap

- Admin dashboard
- Analytics dashboard (no-show insights)
- Customer reliability scoring
- Multi-tenant SaaS layer
- AI-based demand forecasting
- Smart overbooking model
- Voice assistant integration

---

# 🎯 Current Status

- PostgreSQL migration complete  
- Reminder lifecycle validated  
- Multi-business architecture active  

---

# 🧠 Design Philosophy

Backend is the authority.  
LLM is a tool, not the brain.  
Determinism over randomness.  
State machines over prompt hacks.

---

## 📌 Notes

This system is designed as a scalable booking infrastructure engine, not just a chatbot.

It can expand to support:

- Web chat
- Voice bots
- CRM integrations
- Advanced analytics
- SaaS deployment model
