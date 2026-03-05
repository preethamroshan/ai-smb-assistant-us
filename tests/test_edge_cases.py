from conftest import send_message


EDGE_MESSAGES = [

    "k",

    "ok",

    "yeah",

    "y",

    "sure",

    "fine",

    "alright",

    "hmm",

    "uh",

    "wait",

    "what",

    "?",

    "hello",

    "hi",

    "hey",

    "yo",

    "sup",

    "hello there",

    "anyone there",

    "test"

]


def test_edge_variations(client):

    for msg in EDGE_MESSAGES:

        reply = send_message(client, msg, msg)

        assert reply is not None