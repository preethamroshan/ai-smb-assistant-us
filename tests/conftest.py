import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

import pytest
from fastapi.testclient import TestClient
from app import app

from unittest.mock import patch
import json


@pytest.fixture(autouse=True)
def groq_mock():

    if os.getenv("USE_REAL_LLM") == "true":

        yield
        return

    def fake_response(*args, **kwargs):

        content = json.dumps({

            "intent": "booking_request",
            "service": "Haircut",
            "date": "tomorrow",
            "time": "3pm",
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


    with patch(

        "services.conversation_engine.client.chat.completions.create",

        side_effect=fake_response

    ):

        yield


@pytest.fixture(scope="function")
def client():

    with TestClient(app) as c:

        yield c


def send_message(client, text, session="test_user"):

    response = client.post(

        "/chat",

        json={

            "session_id": session,
            "text": text,
            "message_id": text

        }

    )

    data = response.json()

    assert "intent" in data
    assert "reply" in data

    return data