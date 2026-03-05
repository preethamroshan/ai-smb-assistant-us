from conftest import send_message


FAQ_MESSAGES = [

    # hours

    "what time open",

    "opening time",

    "closing time",

    "are you open today",

    "when do you close",

    "business hours",

    "hours today",

    "when open",

    # address

    "where located",

    "address",

    "location",

    "where are you",

    "directions",

    "how to reach",

    "where is salon",

    # pricing

    "price haircut",

    "cost haircut",

    "how much haircut",

    "haircut price",

    "rate haircut",

    "charges haircut",

    # services

    "what services",

    "do you offer beard trim",

    "service list",

    "what do you do"

]


def test_faq_variations(client):

    for msg in FAQ_MESSAGES:

        reply = send_message(client, msg, msg)

        assert reply["intent"] is not None