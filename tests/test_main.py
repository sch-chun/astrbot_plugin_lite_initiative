# tests/test_main.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import time
from astrbot_plugin_lite_initiative.main import LiteInitiativePlugin
from astrbot_plugin_lite_initiative.data_types import Trigger

# 统一的会话标识
TEST_SESSION = "platform:private:user123"

@pytest.fixture
def plugin(mock_context, sample_config_dict):
    with patch('astrbot_plugin_lite_initiative.main.Storage') as mock_storage:
        mock_storage_instance = MagicMock()
        mock_storage.return_value = mock_storage_instance
        mock_storage_instance.load_triggers.return_value = {}
        mock_storage_instance.load_states.return_value = ({}, {})
        plugin = LiteInitiativePlugin(mock_context, sample_config_dict)
        return plugin

def test_whitelist(plugin):
    # 没有白名单，全部允许
    assert plugin._is_user_whitelisted("any") is True
    # 有白名单 – 注意使用 plugin._config.cfg（不是 _cfg）
    plugin._config.cfg["whitelist"] = ["123"]
    assert plugin._is_user_whitelisted("platform:private:123") is True
    assert plugin._is_user_whitelisted("platform:private:456") is False

def test_enforce_max_triggers(plugin):
    for i in range(10):
        t = Trigger(
            trigger_id=f"id{i}",
            session="sess1",
            created_at=time.time() - i * 10
        )
        plugin._triggers[f"id{i}"] = t
    plugin._config.cfg["max_triggers"] = 5   # 修改配置
    plugin._enforce_max_triggers()
    assert len(plugin._triggers) == 5
    remaining_ids = list(plugin._triggers.keys())
    # 最早的 5 个（id9~id5）应被删除
    assert "id9" not in remaining_ids
    assert "id5" not in remaining_ids

def test_get_or_create_session(plugin):
    s = plugin._get_or_create_session("sess1")
    assert s is not None
    assert "sess1" in plugin._sessions

@pytest.mark.asyncio
async def test_on_user_message_clears_triggers(plugin, mock_event):
    t1 = Trigger(session=mock_event.unified_msg_origin, trigger_id="t1")
    plugin._triggers["t1"] = t1
    await plugin._on_user_message(mock_event)
    assert len(plugin._triggers) == 0
    assert plugin._last_user_msg[mock_event.unified_msg_origin] > 0

@pytest.mark.asyncio
async def test_timeout_decision_flow(plugin, mock_event):
    with patch('astrbot_plugin_lite_initiative.main.run_ai_decision') as mock_decision:
        mock_decision.return_value = AsyncMock(return_value=True)
        event = MagicMock()
        event.unified_msg_origin = mock_event.unified_msg_origin
        event.get_extra.return_value = False
        await plugin._on_llm_response(event)
        s = plugin._sessions[event.unified_msg_origin]
        assert s.timeout_task is not None
        s.timeout_task.cancel()
        await plugin._on_user_message(mock_event)
        assert s.timeout_task is None

@pytest.mark.asyncio
async def test_daily_analysis(plugin):
    with patch('astrbot_plugin_lite_initiative.main._get_now_tz') as mock_now:
        from datetime import datetime
        mock_now.return_value = datetime(2026, 1, 1, 7, 0, 0)
        plugin._last_user_msg["sess1"] = time.time()
        with patch('astrbot_plugin_lite_initiative.main.run_ai_decision') as mock_run:
            mock_run.return_value = AsyncMock(return_value=True)
            await plugin._daily_analysis_check()
            mock_run.assert_called_once()
            