# tests/test_tools.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import time
from astrbot_plugin_lite_initiative.tools import LLMFunctions
from astrbot_plugin_lite_initiative.data_types import Trigger

@pytest.fixture
def mock_plugin():
    plugin = MagicMock()
    plugin._triggers = {}
    plugin._config = MagicMock()
    plugin._config.get_tz = MagicMock(return_value="Asia/Shanghai")
    plugin._config.get_max_triggers = MagicMock(return_value=5)
    plugin._config.get_sleep_hours = MagicMock(return_value="23:00-07:00")
    plugin._storage = MagicMock()
    plugin._storage.save_triggers = MagicMock()
    plugin._lock = AsyncMock()
    plugin._lock.__aenter__ = AsyncMock()
    plugin._lock.__aexit__ = AsyncMock()
    plugin._enforce_max_triggers = MagicMock()
    return plugin

@pytest.fixture
def llm_funcs(mock_plugin):
    return LLMFunctions(mock_plugin)

@pytest.mark.asyncio
async def test_list_triggers_empty(llm_funcs, mock_event):
    result = await llm_funcs.list_triggers(mock_event)
    assert "当前没有待执行的触发器" in result

@pytest.mark.asyncio
async def test_create_trigger_basic(llm_funcs, mock_event):
    # 模拟当前时间，让触发时间在明天
    with patch('astrbot_plugin_lite_initiative.tools._get_now_tz') as mock_now:
        from datetime import datetime
        mock_now.return_value = datetime(2026, 1, 1, 12, 0, 0)
        result = await llm_funcs.create_trigger(
            event=mock_event,
            fire_at_str="13:30:00",  # 今天13:30
            extra_prompt="你好"
        )
        assert "✅ 触发器已创建" in result
        # 检查触发器被添加到字典
        triggers = llm_funcs._plugin._triggers
        assert len(triggers) == 1
        t = list(triggers.values())[0]
        assert t.session == mock_event.unified_msg_origin
        assert t.extra_prompt == "你好"
        assert t.use_agent is True

@pytest.mark.asyncio
async def test_create_trigger_exceeds_limit(llm_funcs, mock_event):
    # 添加5个触发器（达到上限）
    for i in range(5):
        t = Trigger(
            trigger_id=f"id{i}",
            fire_at_unix=time.time()+1000,
            session=mock_event.unified_msg_origin,
            extra_prompt=""
        )
        llm_funcs._plugin._triggers[t.trigger_id] = t
    # 设置max_triggers为5
    llm_funcs._plugin._config.get_max_triggers.return_value = 5
    result = await llm_funcs.create_trigger(
        event=mock_event,
        fire_at_str="14:00:00",
        extra_prompt=""
    )
    assert "已达到触发器上限" in result
    assert "❌ 创建失败" in result

@pytest.mark.asyncio
async def test_create_trigger_sleep_hours(llm_funcs, mock_event):
    # 设置睡眠时段 23:00-07:00，当前时间假设为 01:00
    with patch('astrbot_plugin_lite_initiative.tools._get_now_tz') as mock_now:
        from datetime import datetime
        mock_now.return_value = datetime(2026, 1, 1, 1, 0, 0)
        result = await llm_funcs.create_trigger(
            event=mock_event,
            fire_at_str="02:00:00",  # 在睡眠时段内
            extra_prompt=""
        )
        assert "睡眠时段内" in result
        assert "❌ 创建失败" in result

@pytest.mark.asyncio
async def test_delete_trigger(llm_funcs, mock_event):
    t = Trigger(trigger_id="delme", session=mock_event.unified_msg_origin)
    llm_funcs._plugin._triggers["delme"] = t
    result = await llm_funcs.delete_trigger(mock_event, "delme")
    assert "成功删除" in result
    assert "delme" not in llm_funcs._plugin._triggers

    result2 = await llm_funcs.delete_trigger(mock_event, "nonexist")
    assert "未找到触发器" in result2

@pytest.mark.asyncio
async def test_update_trigger(llm_funcs, mock_event):
    t = Trigger(
        trigger_id="upd",
        fire_at_unix=100.0,
        session=mock_event.unified_msg_origin,
        extra_prompt="old",
        use_agent=True
    )
    llm_funcs._plugin._triggers["upd"] = t
    new_ts = 200.0
    result = await llm_funcs.update_trigger(
        event=mock_event,
        trigger_id="upd",
        fire_at_unix=new_ts,
        extra_prompt="new",
        use_agent=False
    )
    assert "已更新" in result
    assert t.fire_at_unix == new_ts
    assert t.extra_prompt == "new"
    assert t.use_agent is False
    