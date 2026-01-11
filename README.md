# WhatsApp AI Receptionist (Phase 1)

This is Phase 1 of an AI-powered virtual receptionist designed for small Indian businesses.

## What it does
- Accepts customer messages (English + local slang)
- Identifies intent (booking, service query, business info)
- Extracts structured data (date, time, service)
- Responds like a local staff member
- Returns clean JSON for automation systems

## Tech Stack
- FastAPI (backend)
- Groq LLM (Llama 3.1)
- Python
- REST API
- Prompt-based intent extraction

## Example Input
```json
{
  "text" : "Bro tomorrow evening haircut slot free aa?"
}
```

## Example Output
```json
{
  "intent": "booking_request",
  "service": "Haircut",
  "date": "tomorrow",
  "time": "evening",
  "reply": "Yes bro, evening slot available hai 👍 Shall I book it?"
}
```


## Phase 2 – Booking Confirmation (Current)

- Multi-turn booking flow
- Backend-managed booking state
- Confirmation step before finalizing
- Unique booking reference generation
- LLM used only for intent extraction (not control)

This phase introduces deterministic workflows on top of LLM reasoning.

## Example Input
```json
{
  "session_id": "user123",
  "text": "Bro tomorrow evening haircut slot free aa?"
}
```
## Example Output
```json
{
  "intent": "booking_pending",
  "reply": "Yes bro 👍 Haircut is available tomorrow evening. Shall I confirm the booking?"
}
```
## Example Input
```json
{
  "session_id": "user123",
  "text": "yes"
}
```
## Example Output
```json
{
  "intent": "booking_confirmed",
  "booking_id": "SALON-8392",
  "reply": "✅ Booking confirmed bro! Ref ID: SALON-8392"
}
```


## Status
- Phase 2 complete.
- Next phases will include WhatsApp integration, and voice support.