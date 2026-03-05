from conftest import send_message


RESCHEDULE_WORDS = [

    "reschedule",
    "change time",
    "move it",
    "push it",
    "bump it",
    "shift it",
    "later time",
    "earlier",
    "different time",
    "not 3, make it 5",
    "can we do 5",
    "make it 6 instead",
    "actually 7 works",
    "change to tomorrow",
    "next day",
    "another time",
    "switch time",
    "modify time",
    "adjust time"
]

def complete_booking(client, session):

    send_message(client, "book haircut", session)

    send_message(client, "tomorrow", session)

    send_message(client, "3pm", session)

    send_message(client, "yes", session)


def test_reschedule_variations(client):

    for word in RESCHEDULE_WORDS:

        session = f"reschedule_{word}"

        complete_booking(client, session)

        reply = send_message(client, word, session)

        assert reply["intent"] != "fallback"