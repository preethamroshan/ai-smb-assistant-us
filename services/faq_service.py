from utils.time_utils import format_time_for_user

def handle_faq_reply(intent: str, business_info: dict) -> str | None:
    if intent == "faq_hours":
        hours = business_info.get("business_hours", {})
        start = hours.get("start", "09:00")
        end = hours.get("end", "19:00")
        return f"We’re open from {format_time_for_user(start)} to {format_time_for_user(end)}."

    if intent == "faq_address":
        return f"We’re located at: {business_info.get('location', 'our salon location')} 📍"

    if intent == "faq_services":
        services = ", ".join(business_info.get("services", []))
        return f"We offer: {services}. Which one would you like to book?"

    if intent == "faq_pricing":
        return "Pricing depends on the service 😊 Which service are you looking for? (Haircut / Facial / etc.)"

    return None

def infer_faq_intent_from_text(user_text: str) -> str | None:
    t = (user_text or "").lower()

    if any(x in t for x in ["hours", "open", "close", "timing", "working hours"]):
        return "faq_hours"

    if any(x in t for x in ["address", "location", "where are you", "where r you", "located"]):
        return "faq_address"

    if any(x in t for x in ["services", "service list", "what do you offer", "do you do"]):
        return "faq_services"

    if any(x in t for x in ["price", "pricing", "cost", "how much", "charges", "$"]):
        return "faq_pricing"

    return None