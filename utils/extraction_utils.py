from utils.date_utils import parse_date_us, extract_date_phrase, user_mentioned_date
from utils.time_utils import normalize_time, infer_time_from_text, user_mentioned_time

def safe_extract_date(data: dict, user_text: str, business_info: dict) -> str | None:
    """
    Extract date only when:
    - LLM provided date OR
    - user message clearly mentions a date
    """

    # 1) Prefer LLM structured date
    llm_date = (data or {}).get("date")
    if llm_date:
        parsed = parse_date_us(str(llm_date), business_info)
        if parsed:
            return parsed

    # 2) If user mentioned a date, extract only the date phrase
    if user_mentioned_date(user_text):
        phrase = extract_date_phrase(user_text)   # ✅ IMPORTANT
        parsed = parse_date_us(phrase, business_info)
        if parsed:
            return parsed

        # 3) fallback: try full text
        return parse_date_us(user_text, business_info)

    return None

def safe_extract_time(data: dict, user_text: str) -> str | None:
    """
    Extract time only when:
    - LLM provided time OR
    - user message clearly mentions a time
    """
    llm_time = (data or {}).get("time")
    if llm_time:
        return normalize_time(llm_time)

    if user_mentioned_time(user_text):
        return infer_time_from_text(user_text)

    return None