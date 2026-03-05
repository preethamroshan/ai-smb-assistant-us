from conftest import send_message


CANCEL_WORDS = [

    "cancel",
    "cancel it",
    "cancel appointment",
    "never mind",
    "forget it",
    "no cancel",
    "stop",
    "abort",
    "end it",
    "dont book",
    "call it off",
    "scratch that",
    "not anymore"
]

def complete_booking(client, session):

    send_message(client, "book haircut", session)

    send_message(client, "tomorrow", session)

    send_message(client, "3pm", session)

    send_message(client, "yes", session)


def test_cancel_variations(client):

    for word in CANCEL_WORDS:

        session = f"cancel_{word}"

        complete_booking(client, session)

        reply = send_message(client, word, session)

        assert reply["intent"] != "fallback"