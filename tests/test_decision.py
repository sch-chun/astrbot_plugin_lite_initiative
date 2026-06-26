# tests/test_decision.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from astrbot_plugin_lite_initiative.decision import (
    build_agent_config,
    get_history_text,
    run_ai_decision,
    run_trigger_agent,
    run_trigger_plain,
    save_proactive_history,
)
from astrbot_plugin_lite_initiative.data_types import Trigger

# 统一会话标识，message_type 必须为 "FriendMessage"
TEST_SESSION = "platform:FriendMessage:user123"

def test_build_agent_config(mock_context):
    config = build_agent_config(mock_context, TEST_SESSION)
    assert config is not None
    mock_context.get_config = MagicMock(side_effect=Exception("fail"))
    config = build_agent_config(mock_context, TEST_SESSION)
    assert config is None

@pytest.mark.asyncio
async def test_get_history_text(mock_context):
    mock_conv = MagicMock()
    mock_conv.messages = [
        MagicMock(role="user", content=[MagicMock(text="hello")]),
        MagicMock(role="assistant", content=[MagicMock(text="hi")]),
    ]
    mock_context.conversation_manager.get_curr_conversation_id = AsyncMock(return_value="cid")
    mock_context.conversation_manager.get_conversation = AsyncMock(return_value=mock_conv)
    text = await get_history_text(mock_context, TEST_SESSION, 10)
    assert "用户: hello" in text
    assert "AI: hi" in text

@pytest.mark.asyncio
async def test_run_ai_decision(mock_context, sample_config_dict):
    # 定义一个异步生成器模拟 step_until_done，让 async for 能够执行
    async def mock_step_until_done(timeout: int):
        yield  # 只 yield 一次，循环立即结束

    with patch('astrbot_plugin_lite_initiative.decision.build_main_agent') as mock_build:
        mock_runner = AsyncMock()
        mock_runner.step_until_done = mock_step_until_done
        mock_runner.get_final_llm_resp = MagicMock(return_value=MagicMock(completion_text="决策完成"))
        mock_result = MagicMock()
        mock_result.agent_runner = mock_runner
        mock_build.return_value = mock_result

        from astrbot_plugin_lite_initiative.config import ConfigReader
        config_reader = ConfigReader(sample_config_dict)
        result = await run_ai_decision(
            context=mock_context,
            config_reader=config_reader,
            umo=TEST_SESSION,
            trigger_list=[],
            silence_sec=120,
            decision_prompt="prompt",
            max_history=10
        )
        assert result is True

@pytest.mark.asyncio
async def test_run_trigger_agent(mock_context):
    # 同样模拟 step_until_done 为异步生成器
    async def mock_step_until_done(timeout: int):
        yield

    trigger = Trigger(
        trigger_id="t1",
        session=TEST_SESSION,
        extra_prompt="hello"
    )
    with patch('astrbot_plugin_lite_initiative.decision.build_main_agent') as mock_build:
        mock_runner = AsyncMock()
        mock_runner.step_until_done = mock_step_until_done
        mock_runner.get_final_llm_resp = MagicMock(return_value=MagicMock(completion_text="agent reply"))
        mock_result = MagicMock()
        mock_result.agent_runner = mock_runner
        mock_build.return_value = mock_result
        text, sent = await run_trigger_agent(mock_context, trigger)
        assert text == "agent reply"
        assert sent is False

@pytest.mark.asyncio
async def test_run_trigger_plain(mock_context):
    trigger = Trigger(
        trigger_id="t1",
        session=TEST_SESSION,
        extra_prompt="plain hello"
    )
    with patch('astrbot_plugin_lite_initiative.decision.MessageChain') as mock_chain:
        mock_chain.return_value.message = MagicMock(return_value=mock_chain)
        text, sent = await run_trigger_plain(mock_context, trigger)
        assert text == "plain hello"
        assert sent is True

@pytest.mark.asyncio
async def test_save_proactive_history(mock_context):
    mock_conv = MagicMock()
    mock_conv.messages = []
    mock_context.conversation_manager.get_curr_conversation_id = AsyncMock(return_value="cid")
    mock_context.conversation_manager.get_conversation = AsyncMock(return_value=mock_conv)
    await save_proactive_history(mock_context, TEST_SESSION, "response")
    assert len(mock_conv.messages) == 2
    assert mock_conv.messages[0].role == "user"
    assert mock_conv.messages[1].role == "assistant"
    