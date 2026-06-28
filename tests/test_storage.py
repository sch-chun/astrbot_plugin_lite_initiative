# tests/test_storage.py
import json
import os
import pytest
from src.storage import Storage
from src.data_types import Trigger, SessionState

@pytest.fixture
def storage(tmp_path):
    return Storage(str(tmp_path / "plugin_data"))

def test_save_load_triggers(storage):
    t = Trigger(
        trigger_id="id1",
        fire_at_unix=12345.0,
        session="sess",
        extra_prompt="test",
        direct_send=True
    )
    triggers = {"id1": t}
    storage.save_triggers(triggers)
    loaded = storage.load_triggers()
    assert "id1" in loaded
    assert loaded["id1"].trigger_id == "id1"
    assert loaded["id1"].fire_at_unix == 12345.0
    assert loaded["id1"].session == "sess"
    assert loaded["id1"].extra_prompt == "test"
    assert loaded["id1"].direct_send is True

def test_save_load_states(storage):
    s = SessionState(last_ai_reply_unix=111.0, last_user_msg_unix=222.0)
    sessions = {"sess1": s}
    last_user = {"sess1": 333.0}
    storage.save_states(sessions, last_user)
    loaded_sess, loaded_last = storage.load_states()
    assert "sess1" in loaded_sess
    assert loaded_sess["sess1"].last_ai_reply_unix == 111.0
    assert loaded_sess["sess1"].last_user_msg_unix == 222.0
    assert loaded_last.get("sess1") == 333.0

def test_load_missing_files(storage):
    triggers = storage.load_triggers()
    assert triggers == {}
    sessions, last = storage.load_states()
    assert sessions == {}
    assert last == {}

def test_load_states_filters_invalid_umo(storage, tmp_path):
    # 写入包含无效 umo 的数据
    data = {
        "sess1": {"last_ai_reply_unix": 1, "last_user_msg_unix": 2},
        "invalid": {"last_ai_reply_unix": 3, "last_user_msg_unix": 4},
        "last_user_msg_unix": {
            "valid:FriendMessage:123": 5,
            "invalid_no_colon": 6,
        }
    }
    file = os.path.join(storage.data_dir, "session_states.json")
    with open(file, "w") as f:
        json.dump(data, f)
    sessions, last = storage.load_states()
    assert "sess1" in sessions
    assert "invalid" not in sessions
    assert "valid:FriendMessage:123" in last
    assert "invalid_no_colon" not in last
