import json
import os

import pytest

from ..src.storage import Storage
from ..src.data_types import Trigger, SessionState

from pathlib import Path


@pytest.fixture
def storage(tmp_path: Path) -> Storage:
    return Storage(str(tmp_path / "plugin_data"))


def test_save_load_triggers(storage: Storage) -> None:
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


def test_save_load_states(storage: Storage) -> None:
    valid_umo = "platform:FriendMessage:user123"
    s = SessionState(last_ai_reply_unix=111.0, last_user_msg_unix=222.0)
    sessions = {valid_umo: s}
    last_user = {valid_umo: 333.0}
    storage.save_states(sessions, last_user)
    loaded_sess, loaded_last = storage.load_states()
    assert valid_umo in loaded_sess
    assert loaded_sess[valid_umo].last_ai_reply_unix == 111.0
    assert loaded_sess[valid_umo].last_user_msg_unix == 222.0
    assert loaded_last.get(valid_umo) == 333.0


def test_load_missing_files(storage: Storage) -> None:
    triggers = storage.load_triggers()
    assert triggers == {}
    sessions, last = storage.load_states()
    assert sessions == {}
    assert last == {}


def test_load_states_filters_invalid_umo(storage: Storage, tmp_path: Path) -> None:
    """写入包含无效 umo 的数据"""
    valid_umo = "platform:FriendMessage:user123"
    data = {
        valid_umo: {"last_ai_reply_unix": 1, "last_user_msg_unix": 2},
        "invalid_no_colon": {"last_ai_reply_unix": 3, "last_user_msg_unix": 4},
        "last_user_msg_unix": {
            valid_umo: 5,
            "invalid_no_colon": 6,
        }
    }
    file = os.path.join(storage.data_dir, "session_states.json")
    with open(file, "w") as f:
        json.dump(data, f)
    sessions, last = storage.load_states()
    
    # 只应加载符合 UMO 格式的键（至少两个冒号）
    assert valid_umo in sessions
    assert sessions[valid_umo].last_ai_reply_unix == 1
    assert "invalid_no_colon" not in sessions
    assert last.get(valid_umo) == 5
    assert "invalid_no_colon" not in last
