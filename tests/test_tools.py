# tests/test_tools.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import time
from src.tools import (
    ListTriggersTool,
    CreateTriggerTool,
    DeleteTriggerTool,
    UpdateTriggerTool,
)
from src.data_types import Trigger
from src.config import ConfigReader

# 模拟 ContextWrapper
class MockContextWrapper:
    def __init__(self, event):
        self.context = MagicMock()
        self.context.event = event

@pytest.fixture
def mock_plugin():
    plugin = MagicMock()
    plugin._triggers = {}
    plugin._config = ConfigReader({
        "timezone": "Asia/Shanghai",
        "sleep_hours": "23:00-07:00",
        "max_triggers": 5,
        "min_trigger_delay": 0,
    })
    plugin._storage = MagicMock()
    plugin._storage.save_triggers = MagicMock()
    plugin._lock = AsyncMock()
    plugin._lock.__aenter__ = AsyncMock()
    plugin._lock.__aexit__ = AsyncMock()
    plugin._enforce_max_triggers = MagicMock()
    return plugin

@pytest.fixture
def mock_event():
    event = MagicMock()
    event.unified_msg_origin = "platform:FriendMessage:user123"
    return event

def test_list_triggers_tool(mock_plugin, mock_event):
    tool = ListTriggersTool(plugin=mock_plugin)
    # 无触发器
    ctx = MockContextWrapper(mock_event)
    result = tool.call(ctx)
    assert "当前没有待执行的触发器" in result

    # 添加触发器
    t = Trigger(trigger_id="t1", session=mock_event.unified_msg_origin, fire_at_unix=time.time()+100, extra_prompt="test")
    mock_plugin._triggers["t1"] = t
    result = tool.call(ctx)
    assert "t1" in result
    assert "test" in result

@pytest.mark.asyncio
async def test_create_trigger_tool(mock_plugin, mock_event):
    tool = CreateTriggerTool(plugin=mock_plugin)
    ctx = MockContextWrapper(mock_event)
    # 缺少 fire_at_str
    result = await tool.call(ctx)
    assert "缺少必填参数" in result

    # 成功创建
    with patch('astrbot_plugin_lite_initiative.tools._get_now_tz') as mock_now:
        from datetime import datetime
        mock_now.return_value = datetime(2026, 1, 1, 12, 0, 0)
        result = await tool.call(ctx, fire_at_str="13:30:00", extra_prompt="hello", direct_send=True)
        assert "✅ 触发器已创建" in result
        assert len(mock_plugin._triggers) == 1
        t = list(mock_plugin._triggers.values())[0]
        assert t.extra_prompt == "hello"
        assert t.direct_send is True
        assert t.session == mock_event.unified_msg_origin

    # 超过上限
    mock_plugin._config.cfg["max_triggers"] = 1
    # 先添加一个
    t2 = Trigger(trigger_id="t2", session=mock_event.unified_msg_origin, fire_at_unix=time.time()+100)
    mock_plugin._triggers["t2"] = t2
    result = await tool.call(ctx, fire_at_str="14:00:00")
    assert "已达上限" in result

    # 睡眠时段拒绝
    mock_plugin._config.cfg["max_triggers"] = 5
    with patch('astrbot_plugin_lite_initiative.tools._get_now_tz') as mock_now:
        mock_now.return_value = datetime(2026, 1, 1, 1, 0, 0)
        result = await tool.call(ctx, fire_at_str="02:00:00")
        assert "睡眠时段内" in result

    # 最小延迟拒绝
    mock_plugin._config.cfg["min_trigger_delay"] = 60
    with patch('astrbot_plugin_lite_initiative.tools._get_now_tz') as mock_now:
        mock_now.return_value = datetime(2026, 1, 1, 12, 0, 0)
        result = await tool.call(ctx, fire_at_str="12:00:10")  # 10秒后
        assert "必须至少延迟" in result

@pytest.mark.asyncio
async def test_delete_trigger_tool(mock_plugin, mock_event):
    tool = DeleteTriggerTool(plugin=mock_plugin)
    ctx = MockContextWrapper(mock_event)
    # 不存在
    result = await tool.call(ctx, trigger_id="none")
    assert "未找到" in result

    # 存在
    t = Trigger(trigger_id="delme", session=mock_event.unified_msg_origin)
    mock_plugin._triggers["delme"] = t
    result = await tool.call(ctx, trigger_id="delme")
    assert "已删除" in result
    assert "delme" not in mock_plugin._triggers

@pytest.mark.asyncio
async def test_update_trigger_tool(mock_plugin, mock_event):
    tool = UpdateTriggerTool(plugin=mock_plugin)
    ctx = MockContextWrapper(mock_event)
    # 不存在
    result = await tool.call(ctx, trigger_id="none")
    assert "未找到" in result

    # 存在
    t = Trigger(trigger_id="upd", session=mock_event.unified_msg_origin, fire_at_unix=100.0, extra_prompt="old", direct_send=True)
    mock_plugin._triggers["upd"] = t
    new_ts = 200.0
    result = await tool.call(ctx, trigger_id="upd", fire_at_unix=new_ts, extra_prompt="new", direct_send=False)
    assert "已更新" in result
    assert t.fire_at_unix == new_ts
    assert t.extra_prompt == "new"
    assert t.direct_send is False

    # 更新到睡眠时段拒绝
    with patch('astrbot_plugin_lite_initiative.tools._is_in_sleep_hours', return_value=True):
        result = await tool.call(ctx, trigger_id="upd", fire_at_unix=100.0)
        assert "睡眠时段内" in result
