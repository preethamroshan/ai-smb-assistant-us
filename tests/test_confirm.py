from conftest import send_message


CONFIRM_WORDS = [

    "yes",
    "yeah",
    "yep",
    "yup",
    "confirm",
    "ok",
    "okay",
    "sure",
    "sounds good",
    "perfect",
    "book it",
    "do it",
    "fine",
    "alright",
    "that works",
    "lets do it",
    "please do",
    "correct",
    "right",
    "go ahead"
]

def complete_booking(client, session):

    send_message(client, "book haircut", session)

    send_message(client, "tomorrow", session)

    send_message(client, "3pm", session)

    reply = send_message(client, "yes", session)

    return reply


def test_confirm_variations(client):

    for word in CONFIRM_WORDS:

        session = f"confirm_{word}"

        complete_booking(client, session)

        reply = send_message(client, word, session)

        assert reply["intent"] != "fallback"