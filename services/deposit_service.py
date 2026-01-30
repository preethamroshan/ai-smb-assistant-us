from datetime import datetime

DEPOSIT_RULES_BY_SERVICE = {
    "facial": {
        "deposit_required": True,
        "deposit_amount_cents": 2000,
    },
    "haircut": {
        "deposit_required": False,
        "deposit_amount_cents": 0,
    },
    "beard trim": {
        "deposit_required": False,
        "deposit_amount_cents": 0,
    },
}

PRIME_TIME_RULES = {
    "enabled": True,
    "weekend_required": True,
    "evening_required": True,
    "evening_start_hour": 18,  # 6 PM
    "deposit_amount_cents": 1500,
}

def compute_deposit(service: str, date: str, time: str) -> int:
    """
    Returns deposit amount in cents.
    """
    service_key = service.lower().strip()
    service_rule = DEPOSIT_RULES_BY_SERVICE.get(service_key, {
        "deposit_required": False,
        "deposit_amount_cents": 0
    })

    service_deposit = service_rule["deposit_amount_cents"]

    # ---- Prime time logic ----
    prime_deposit = 0
    if PRIME_TIME_RULES.get("enabled"):
        booking_dt = datetime.fromisoformat(f"{date} {time}")
        weekday = booking_dt.weekday()  # 5=Sat, 6=Sun

        is_weekend = weekday >= 5
        is_evening = booking_dt.hour >= PRIME_TIME_RULES["evening_start_hour"]

        if (
            (PRIME_TIME_RULES["weekend_required"] and is_weekend)
            or (PRIME_TIME_RULES["evening_required"] and is_evening)
        ):
            prime_deposit = PRIME_TIME_RULES["deposit_amount_cents"]

    return max(service_deposit, prime_deposit)