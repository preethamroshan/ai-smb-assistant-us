from models import Business

def build_business_info(db):
    business = db.query(Business).filter(Business.is_active == True).first()

    return {
        "name": business.name,
        "type": business.type,
        "timezone": business.timezone,
        "slot_duration_minutes": business.slot_duration_minutes,
        "same_day_cutoff": (
            f"{business.same_day_cutoff_hour:02d}:00"
            if business.same_day_cutoff_hour is not None
            else None
        ),
        "business_hours": business.business_hours,
        "services": business.services,
        "deposit_required_after_hour": business.deposit_required_after_hour,
        "deposit_amount": business.deposit_amount,
    }
