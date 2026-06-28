import sys
import os
from unittest.mock import AsyncMock, MagicMock
import pytest
from astrbot.api.event import AstrMessageEvent


plugin_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if plugin_parent not in sys.path:
    sys.path.insert(0, plugin_parent)


@pytest.fixture
def mock_context():
    ctx = MagicMock()
    ctx.conversation_manager = MagicMock()
    ctx.conversation_manager.get_curr_conversation_id = AsyncMock(return_value="conv_123")
    ctx.conversation_manager.get_conversation = AsyncMock(return_value=MagicMock(history='[]'))
    ctx.conversation_manager.update_conversation = AsyncMock()
    ctx.send_message = AsyncMock()
    ctx.get_config = MagicMock(return_value={
        "provider_settings": {
            "tool_call_timeout": 120,
            "sanitize_context_by_modalities": False,
            "context_limit_reached_strategy": "truncate_by_turns",
            "llm_compress_instruction": "",
            "llm_compress_provider_id": "",
            "max_context_length": -1,
            "dequeue_context_length": 1,
            "safety_mode_strategy": "system_prompt",
            "computer_use_runtime": "local",
            "sandbox": {},
            "max_quoted_fallback_images": 20,
        },
        "timezone": "Asia/Shanghai"
    })
    ctx.provider_manager = MagicMock()
    ctx.provider_manager.get_provider_by_id = AsyncMock(return_value=None)
    return ctx

@pytest.fixture
def mock_event():
    event = MagicMock(spec=AstrMessageEvent)
    event.unified_msg_origin = "platform:FriendMessage:user123"
    event.role = "user"
    event.message_obj = MagicMock(group_id=None)
    event.message_str = "test"
    event.get_extra = MagicMock(return_value=False)
    return event

@pytest.fixture
def sample_config_dict():
    return {
        "whitelist": [],
        "timezone": "Asia/Shanghai",
        "sleep_hours": "23:00-07:00",
        "max_triggers": 5,
        "decision_timeout_seconds": 300,
        "decision_prompt": "决策提示词",
        "decision_provider": "",
        "min_trigger_delay": 0,
        "suggest_direct_send": True,
        "suggest_direct_send_prompt": "",
        "daily_analysis_times": "07:00,16:00",
        "daily_analysis_prompt": "分析提示词",
        "inactive_threshold_hours": 24,
        "inject_date_tip": True,
        "trigger_persist": True,
    }
