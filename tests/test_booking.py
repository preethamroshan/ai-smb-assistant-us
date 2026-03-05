from conftest import send_message


BOOKING_MESSAGES = [

    "book haircut",

    "I want haircut",

    "need haircut",

    "can I book haircut",

    "schedule haircut",

    "haircut tomorrow",

    "haircut tomorrow 3pm",

    "book haircut tomorrow",

    "appointment for haircut",

    "I need appointment",

    "can I come tomorrow",

    "available tomorrow?",

    "need haircut at 5",

    "book me haircut",

    "I'd like haircut",

    "get haircut",

    "haircut please",

    "can you book haircut",

    "set appointment haircut",

    "make appointment haircut",

    # casual US speech

    "I wanna haircut",

    "lemme get haircut",

    "can u book haircut",

    "need trim",

    "can I stop by tomorrow",

    "got time tomorrow?",

    "slot tomorrow?",

    "any opening tomorrow",

    "free tomorrow?",

    "can I get in tomorrow",

    "book something tomorrow",

    "I wanna come tomorrow",

    "fit me in tomorrow",

    "need appointment asap",

    "next available haircut",

    "earliest appointment haircut",

    "get haircut tomorrow afternoon",

    "book haircut morning",

    "schedule haircut evening"

]


def test_booking_variations(client):

    for msg in BOOKING_MESSAGES:

        reply = send_message(client, msg, msg)

        assert reply["intent"] is not None