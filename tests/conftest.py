# tests/conftest.py
import sys
import os
from unittest.mock import AsyncMock, MagicMock
import pytest
from astrbot.api.event import AstrMessageEvent

# 将插件根目录的父目录加入 sys.path，使 astrbot_plugin_lite_initiative 包可导入
plugin_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if plugin_parent not in sys.path:
    sys.path.insert(0, plugin_parent)

@pytest.fixture
def mock_context():
    """模拟 AstrBot Context 对象"""
    ctx = MagicMock()
    ctx.conversation_manager = MagicMock()
    ctx.conversation_manager.get_curr_conversation_id = AsyncMock(return_value="conv_123")
    ctx.conversation_manager.get_conversation = AsyncMock(return_value=MagicMock(messages=[]))
    ctx.send_message = AsyncMock()
    ctx.activate_llm_tool = MagicMock()
    return ctx

@pytest.fixture
def mock_event():
    """模拟 AstrMessageEvent"""
    event = MagicMock(spec=AstrMessageEvent)
    # 使用 MessageType.FRIEND_MESSAGE 的值 "FriendMessage"
    event.unified_msg_origin = "platform:FriendMessage:user123"
    event.role = "user"
    event.message_obj = MagicMock(group_id=None)  # 私聊
    return event

@pytest.fixture
def sample_config_dict():
    """示例配置字典（扁平结构）"""
    return {
        "whitelist": [],
        "timezone": "Asia/Shanghai",
        "sleep_hours": "23:00-07:00",
        "max_triggers": 5,
        "decision_prompt": "决策提示词",
        "decision_max_history_messages": 20,
        "decision_timeout_seconds": 300,
        "daily_analysis_times": "07:00,16:00",
        "daily_analysis_prompt": "分析提示词",
        "daily_analysis_max_history_messages": 50,
        "inactive_threshold_hours": 24,
        "inject_date_tip": True,
        "trigger_persist": True,
    }

@pytest.fixture
def sample_trigger_dict():
    """示例触发器字典"""
    import time
    return {
        "trigger_id": "abc123",
        "fire_at_unix": time.time() + 3600,
        "session": "platform:FriendMessage:user123",
        "extra_prompt": "测试消息",
        "use_agent": True,
        "created_at": time.time(),
        "extra": {},
    }
