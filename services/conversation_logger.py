import json
from datetime import datetime
from models import ConversationMessage, FSMTransition


def log_conversation_message(
    db,
    business_id,
    session_id,
    user_message,
    bot_reply,
    intent,
    llm_raw,
    latency_ms,
    error=False
):
    msg = ConversationMessage(
        business_id=business_id,
        session_id=session_id,
        user_message=user_message,
        bot_reply=bot_reply,
        intent=intent,
        llm_raw_json=json.dumps(llm_raw) if llm_raw else None,
        latency_ms=latency_ms,
        error=error,
        created_at=datetime.utcnow()
    )

    db.add(msg)


def log_fsm_transition(
    db,
    business_id,
    session_id,
    from_state,
    to_state,
    intent
):
    transition = FSMTransition(
        business_id=business_id,
        session_id=session_id,
        from_state=from_state,
        to_state=to_state,
        intent=intent,
        created_at=datetime.utcnow()
    )

    db.add(transition)