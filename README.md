# 📞 AI WhatsApp Receptionist for US SMBs (Initial US Version)
## Overview

This project is an AI-powered WhatsApp receptionist designed for US small and medium businesses (SMBs) such as salons, clinics, and local service providers.

The assistant handles customer conversations, appointment booking, confirmations, and basic inquiries automatically via WhatsApp, while following a backend-controlled conversational flow for reliability and correctness.

This repository represents the initial US-focused version, built on a finite state machine (FSM) architecture with database-backed persistence.

## 🎯 Problem Statement

### US SMBs often face challenges such as:
- Missed calls and messages
- Manual appointment handling
- Inconsistent customer responses
- Limited staff availability

### This AI receptionist solves these problems by:
- Responding instantly on WhatsApp
- Collecting appointment details step-by-step
- Confirming bookings reliably
- Reducing manual workload for business owners

---

## ✨ Key Features (Current)

### ✅ Conversational Appointment Booking
- Multi-turn booking flow (service → date → time)
- Works even when details are provided across multiple messages

### ✅ FSM-Based Conversation Control
- Explicit conversation states:
- IDLE
- COLLECTING
- CONFIRMING
- Prevents looping, forgetting, or inconsistent behavior

### ✅ Backend-Driven Intelligence
- Backend controls booking logic
- LLM is used only for intent & slot extraction
- No LLM memory hacks or chat-history dependency

### ✅ Persistence & Reliability
- Session state stored in database
- Idempotent message handling (prevents duplicate processing)
- Booking data persisted safely

### ✅ WhatsApp Cloud API Integration
- Uses Meta WhatsApp Cloud API
- Compatible with US phone numbers
- Webhook-based message ingestion

---

## 🧠 Architecture Overview
WhatsApp User
     ↓
WhatsApp Cloud API
     ↓
Webhook (FastAPI)
     ↓
FSM-based Backend Logic
     ↓
Database (Sessions & Bookings)
     ↓
Response sent back to WhatsApp

---

## Core Design Principles

- Backend is the brain
- LLM is a parser, not a decision-maker
- State-driven conversation flow
- Predictable, debuggable behavior

---

## 🛠 Tech Stack

- Backend: FastAPI (Python)
- LLM: Groq (LLaMA 3.1)
- Database: SQLite (dev), designed for Postgres later
- Messaging: WhatsApp Cloud API
- Infra Glue: Webhooks & REST APIs
- Version Control: Git & GitHub

---

## 📌 Current Scope (Initial US Version)

✔ Appointment booking
✔ Booking confirmation
✔ Service & availability inquiries
✔ FSM-based conversation control
✔ Persistence & idempotency

---

## 🚧 Planned Features (Next Steps)

This repository is an active build, not a finished product.
Upcoming US-focused features include:
❌ Appointment cancellation

❌ Appointment rescheduling

❌ Mid-booking service modification

❌ Date & time normalization (US formats, AM/PM)

❌ Business hours & availability rules

❌ Admin dashboard (replace static config)

❌ Multi-language support (US-first, extensible later)

❌ Session timeouts & cleanup

❌ Human handoff option

---

## 🚀 Status

- Stage: Initial US Version (FSM & Persistence Complete)
- Next Milestone: US Intent Schema + Cancellation & Rescheduling FSM

---

## 📖 Notes

- This project intentionally avoids LangChain-style memory.
- Conversation correctness is achieved via explicit state management.
- The codebase is designed to scale to voice assistants and other channels later.

---
