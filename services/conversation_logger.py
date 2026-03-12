import json
from datetime import datetime
from models import ConversationMessage, FSMTransition
import time

def log_conversation_message(
    db,
    business_id,
    session_id,
    phone_number,
    user_message,
    bot_reply,
    intent,
    llm_raw,
    latency_ms,
    error=False
):

    # ---------------------------
    # USER MESSAGE
    # ---------------------------
    if user_message:
        user_msg = ConversationMessage(
            business_id=business_id,
            session_id=session_id,
            phone_number=phone_number,
            role="user",
            message_text=user_message,
            normalized_intent=intent,
            llm_raw_json=llm_raw,
            latency_ms=latency_ms,
            is_error=error,
            created_at=datetime.utcnow()
        )

        db.add(user_msg)

    # ---------------------------
    # BOT REPLY
    # ---------------------------
    if bot_reply:
        bot_msg = ConversationMessage(
            business_id=business_id,
            session_id=session_id,
            phone_number=phone_number,
            role="bot",
            message_text=bot_reply,
            normalized_intent=intent,
            llm_raw_json=llm_raw,
            latency_ms=latency_ms,
            is_error=error,
            created_at=datetime.utcnow()
        )

        db.add(bot_msg)

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
        trigger_intent=intent,
        timestamp=datetime.utcnow()
    )

    db.add(transition)

def finalize_response(
    db,
    session,
    session_id,
    user_text,
    response,
    llm_raw,
    start_time,
    error_flag,
    fsm_state_before
):

    latency_ms = int((time.time() - start_time) * 1000)

    fsm_state_after = session.booking_state

    # extract confidence safely
    llm_confidence = None
    if isinstance(llm_raw, dict):
        llm_confidence = llm_raw.get("confidence")

    # -------------------------------
    # LOG MESSAGE
    # -------------------------------
    log_conversation_message(
        db=db,
        business_id=session.business_id,
        session_id=session_id,
        phone_number=session_id,
        user_message=user_text,
        bot_reply=response.get("reply"),
        intent=response.get("intent"),
        llm_raw=llm_raw,
        llm_confidence=llm_confidence,   # ✅ NEW
        fsm_state_before=fsm_state_before,  # ✅ NEW
        fsm_state_after=fsm_state_after,    # ✅ NEW
        latency_ms=latency_ms,
        error=error_flag
    )

    # -------------------------------
    # LOG FSM TRANSITION
    # -------------------------------
    if fsm_state_before != fsm_state_after:

        log_fsm_transition(
            db=db,
            business_id=session.business_id,
            session_id=session_id,
            from_state=fsm_state_before,
            to_state=fsm_state_after,
            intent=response.get("intent")
        )

    db.commit()

    print(
        f"[LOG] session={session_id} "
        f"intent={response.get('intent')} "
        f"state={fsm_state_before}->{fsm_state_after}"
    )

    return response