# tests/test_data_types.py
import time
from astrbot_plugin_lite_initiative.data_types import Trigger, SessionState

def test_trigger_to_from_dict():
    t = Trigger(
        trigger_id="test123",
        fire_at_unix=time.time() + 100,
        session="sess",
        extra_prompt="hello",
        use_agent=False,
        extra={"key": "val"}
    )
    d = t.to_dict()
    t2 = Trigger.from_dict(d)
    assert t2.trigger_id == t.trigger_id
    assert t2.fire_at_unix == t.fire_at_unix
    assert t2.session == t.session
    assert t2.extra_prompt == t.extra_prompt
    assert t2.use_agent == t.use_agent
    assert t2.created_at == t.created_at
    assert t2.extra == t.extra

def test_session_state_to_from_dict():
    s = SessionState(
        last_ai_reply_unix=1000.0,
        last_user_msg_unix=2000.0,
    )
    d = s.to_dict()
    s2 = SessionState.from_dict(d)
    assert s2.last_ai_reply_unix == s.last_ai_reply_unix
    assert s2.last_user_msg_unix == s.last_user_msg_unix
    # timeout_task not serialized
    assert s2.timeout_task is None
    assert s2.decision_in_progress is False
    