import json
from unittest.mock import patch

def build_mock_response(intent, service=None, date=None, time=None):
    content = json.dumps({
        "intent": intent,
        "service": service,
        "date": date,
        "time": time,
        "ref_id": None,
        "faq_topic": None,
        "confidence": 0.99
    })

    return {
        "choices": [
            {
                "message": {
                    "content": content
                }
            }
        ]
    }


def patch_groq(intent, service=None, date=None, time=None):
    return patch(
        "app.client.chat.completions.create",
        return_value=build_mock_response(intent, service, date, time)
    )