from conftest import send_message


def test_real_flow_1(client):

    send_message(client, "book haircut tomorrow")

    send_message(client, "3pm")

    send_message(client, "yes")

    reply = send_message(client, "actually can we do 5")

    assert reply is not None



def test_real_flow_2(client):

    send_message(client, "haircut tomorrow")

    reply = send_message(client, "never mind")

    assert reply is not None



def test_real_flow_3(client):

    send_message(client, "book haircut")

    send_message(client, "tomorrow")

    reply = send_message(client, "change it")

    assert reply is not None



def test_real_flow_4(client):

    send_message(client, "book haircut tomorrow")

    send_message(client, "3")

    send_message(client, "yes")

    reply = send_message(client, "cancel")

    assert reply is not None