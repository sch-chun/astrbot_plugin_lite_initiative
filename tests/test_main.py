import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import time

from ..main import LiteInitiativePlugin
from ..src.data_types import Trigger


TEST_SESSION = "platform:FriendMessage:user123"


@pytest.fixture
def plugin(mock_context: MagicMock, sample_config_dict: dict) -> LiteInitiativePlugin:
    with patch('astrbot_plugin_lite_initiative.main.Storage') as mock_storage:
        mock_storage_instance = MagicMock()
        mock_storage.return_value = mock_storage_instance
        mock_storage_instance.load_triggers.return_value = {}
        mock_storage_instance.load_states.return_value = ({}, {})
        plugin = LiteInitiativePlugin(mock_context, sample_config_dict)

        # 手动设置 _last_user_msg 以避免空
        plugin._last_user_msg = {}
        return plugin
    

def test_whitelist(plugin: LiteInitiativePlugin) -> None:

    # 无白名单，全部允许
    assert plugin._is_user_whitelisted("any") is True

    # 有白名单
    plugin._config.cfg["whitelist"] = ["123"]
    assert plugin._is_user_whitelisted("platform:FriendMessage:123") is True
    assert plugin._is_user_whitelisted("platform:FriendMessage:456") is False


def test_enforce_max_triggers(plugin: LiteInitiativePlugin) -> None:
    for i in range(10):
        t = Trigger(
            trigger_id=f"id{i}",
            session="sess1",
            created_at=time.time() - i * 10
        )
        plugin._triggers[f"id{i}"] = t
    plugin._config.cfg["max_triggers"] = 5
    plugin._enforce_max_triggers()
    assert len(plugin._triggers) == 5

    # 最早创建的5个应该被删除（id9~id5）
    remaining = list(plugin._triggers.keys())
    assert "id9" not in remaining
    assert "id5" not in remaining
    assert "id4" in remaining


def test_get_or_create_session(plugin: LiteInitiativePlugin) -> None:
    s = plugin._get_or_create_session("sess1")
    assert s is not None
    assert "sess1" in plugin._sessions


@pytest.mark.asyncio
async def test_on_user_message_clears_triggers(plugin: LiteInitiativePlugin, mock_event: MagicMock) -> None:

    # 设置超时窗口，构建一个即将触发和一个远期触发
    now = time.time()
    timeout = plugin._config.get_decision_timeout()
    t1 = Trigger(trigger_id="t1", session=mock_event.unified_msg_origin, fire_at_unix=now + 10)  # 即将触发
    t2 = Trigger(trigger_id="t2", session=mock_event.unified_msg_origin, fire_at_unix=now + timeout + 100)  # 远期
    plugin._triggers["t1"] = t1
    plugin._triggers["t2"] = t2

    await plugin._on_user_message(mock_event)

    # 应只清除 t1，保留 t2
    assert "t1" not in plugin._triggers
    assert "t2" in plugin._triggers


@pytest.mark.asyncio
async def test_on_user_message_cancels_timeout(plugin: LiteInitiativePlugin, mock_event: MagicMock) -> None:

    # 模拟超时任务
    s = plugin._get_or_create_session(mock_event.unified_msg_origin)
    mock_task = AsyncMock()
    s.timeout_task = mock_task

    await plugin._on_user_message(mock_event)

    # 验证取消被调用
    mock_task.cancel.assert_called_once()

    # 验证 timeout_task 被清空
    assert s.timeout_task is None


@pytest.mark.asyncio
async def test_on_llm_response_starts_timeout(plugin: LiteInitiativePlugin, mock_event: MagicMock) -> None:
    with patch('astrbot_plugin_lite_initiative.main.asyncio.create_task') as mock_create:
        mock_create.return_value = AsyncMock()
        await plugin._on_llm_response(mock_event, None)
        s = plugin._sessions[mock_event.unified_msg_origin]
        assert s.last_ai_reply_unix > 0
        mock_create.assert_called_once()


@pytest.mark.asyncio
async def test_timeout_decision_flow(plugin: LiteInitiativePlugin, mock_event: MagicMock) -> None:

    # 模拟超时到达，调用 _perform_decision
    with patch("asyncio.sleep", return_value=None):
        with patch.object(plugin, '_perform_decision', new=AsyncMock()) as mock_perform:
            s = plugin._get_or_create_session(mock_event.unified_msg_origin)
            s.last_ai_reply_unix = time.time()
            s.last_user_msg_unix = 0  # 确保用户未发言

            # 手动触发超时任务（直接调用 _timeout_decision）
            await plugin._timeout_decision(mock_event.unified_msg_origin, 1)
            mock_perform.assert_called_once_with(mock_event.unified_msg_origin, is_daily=False)


@pytest.mark.asyncio
async def test_daily_analysis(plugin: LiteInitiativePlugin) -> None:
    with patch('astrbot_plugin_lite_initiative.main._get_now_tz') as mock_now:
        from datetime import datetime
        mock_now.return_value = datetime(2026, 1, 1, 7, 0, 0)
        plugin._last_user_msg["sess1"] = time.time()  # 活跃
        with patch.object(plugin, '_perform_decision', new=AsyncMock()) as mock_perform:
            await plugin._daily_analysis_check()
            mock_perform.assert_called_once_with("sess1", is_daily=True)


@pytest.mark.asyncio
async def test_scheduler_tick(plugin: LiteInitiativePlugin) -> None:

    # 简单测试调度循环，不实际运行
    plugin._stopped = True  # 避免循环

    # 测试 _tick 是否会触发触发器执行
    t = Trigger(trigger_id="t1", session="sess", fire_at_unix=time.time() - 10)
    plugin._triggers["t1"] = t
    with patch.object(plugin, '_execute_trigger', new=AsyncMock()) as mock_exec:
        await plugin._tick()
        mock_exec.assert_called_once_with(t)


@pytest.mark.asyncio
async def test_execute_trigger_plain(plugin: LiteInitiativePlugin) -> None:
    t = Trigger(trigger_id="t1", session="sess", extra_prompt="hello", direct_send=True)
    plugin._firing_ids = set()
    with patch('astrbot_plugin_lite_initiative.main.run_trigger', return_value=("hello", True)) as mock_run:
        with patch('astrbot_plugin_lite_initiative.main.save_proactive_history', new=AsyncMock()) as mock_save:
            await plugin._execute_trigger(t)
            mock_run.assert_called_once()
            mock_save.assert_called_once()

            # 触发器应被删除
            assert "t1" not in plugin._triggers
