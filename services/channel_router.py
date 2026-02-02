from channels.whatsapp import send_whatsapp_message
from channels.sms import send_sms_message

def send_message(channel: str, phone: str, text: str):
    if channel == "whatsapp":
        send_whatsapp_message(phone, text)
    elif channel == "sms":
        send_sms_message(phone, text)
