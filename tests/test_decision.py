import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.decision import (
    build_agent_config,
    run_ai_decision,
    run_trigger,
    run_trigger_agent,
    run_trigger_plain,
    save_proactive_history,
)
from src.data_types import Trigger
from src.config import ConfigReader


TEST_SESSION = "platform:FriendMessage:user123"


def test_build_agent_config(mock_context):
    config = build_agent_config(mock_context, TEST_SESSION)
    assert config is not None
    # 模拟get_config异常
    mock_context.get_config = MagicMock(side_effect=Exception("fail"))
    config = build_agent_config(mock_context, TEST_SESSION)
    assert config is None

@pytest.mark.asyncio
async def test_run_ai_decision(mock_context, sample_config_dict):
    # 模拟 step_until_done 为异步生成器
    async def mock_step_until_done(timeout: int):
        yield

    with patch('astrbot_plugin_lite_initiative.decision.build_main_agent') as mock_build:
        mock_runner = AsyncMock()
        mock_runner.step_until_done = mock_step_until_done
        mock_runner.get_final_llm_resp = MagicMock(return_value=MagicMock(completion_text="决策完成"))
        mock_result = MagicMock()
        mock_result.agent_runner = mock_runner
        mock_build.return_value = mock_result

        config_reader = ConfigReader(sample_config_dict)
        result = await run_ai_decision(
            context=mock_context,
            config_reader=config_reader,
            umo=TEST_SESSION,
            trigger_list=[],
            decision_prompt="prompt"
        )
        assert result is True

    # 测试decision_provider生效
    with patch('astrbot_plugin_lite_initiative.decision.build_main_agent') as mock_build:
        mock_build.return_value = MagicMock(agent_runner=MagicMock(
            step_until_done=AsyncMock(),
            get_final_llm_resp=MagicMock(return_value=MagicMock(completion_text="ok"))
        ))
        config_reader = ConfigReader({**sample_config_dict, "decision_provider": "test_provider"})
        mock_context.provider_manager.get_provider_by_id.return_value = MagicMock()
        result = await run_ai_decision(
            context=mock_context,
            config_reader=config_reader,
            umo=TEST_SESSION,
            trigger_list=[],
            decision_prompt="prompt"
        )
        # provider 应该被传入 build_main_agent
        args, kwargs = mock_build.call_args
        assert kwargs.get("provider") is not None

@pytest.mark.asyncio
async def test_run_trigger_agent(mock_context):
    async def mock_step_until_done(timeout: int):
        yield

    trigger = Trigger(
        trigger_id="t1",
        session=TEST_SESSION,
        extra_prompt="hello",
        direct_send=False   # 走agent
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
        # sent 取决于 context.send_message 是否被调用，但这里模拟 send_message 未执行，所以 sent=False
        # 但实际 run_trigger_agent 中会调用 context.send_message
        # 我们模拟 send_message 成功
        mock_context.send_message = AsyncMock()
        text, sent = await run_trigger_agent(mock_context, trigger)
        assert sent is True

@pytest.mark.asyncio
async def test_run_trigger_plain(mock_context):
    trigger = Trigger(
        trigger_id="t1",
        session=TEST_SESSION,
        extra_prompt="plain hello",
        direct_send=True
    )
    mock_context.send_message = AsyncMock()
    text, sent = await run_trigger_plain(mock_context, trigger)
    assert text == "plain hello"
    assert sent is True

@pytest.mark.asyncio
async def test_run_trigger_dispatch(mock_context):
    trigger_agent = Trigger(direct_send=False, extra_prompt="agent")
    trigger_plain = Trigger(direct_send=True, extra_prompt="plain")
    with patch('astrbot_plugin_lite_initiative.decision.run_trigger_agent', return_value=("agent", True)) as mock_agent:
        with patch('astrbot_plugin_lite_initiative.decision.run_trigger_plain', return_value=("plain", True)) as mock_plain:
            config_reader = ConfigReader({})
            text, sent = await run_trigger(mock_context, config_reader, trigger_agent)
            mock_agent.assert_called_once()
            text, sent = await run_trigger(mock_context, config_reader, trigger_plain)
            mock_plain.assert_called_once()

@pytest.mark.asyncio
async def test_save_proactive_history(mock_context):
    conv = MagicMock()
    conv.history = '[]'
    mock_context.conversation_manager.get_curr_conversation_id = AsyncMock(return_value="cid")
    mock_context.conversation_manager.get_conversation = AsyncMock(return_value=conv)
    await save_proactive_history(mock_context, TEST_SESSION, "response")
    # 验证 update_conversation 被调用，且 history 更新
    mock_context.conversation_manager.update_conversation.assert_called_once()
    args = mock_context.conversation_manager.update_conversation.call_args[0]
    assert args[0] == TEST_SESSION
    assert args[1] == "cid"
    history_arg = args[2] if len(args) > 2 else mock_context.conversation_manager.update_conversation.call_args[1]['history']
    assert isinstance(history_arg, list)
    assert len(history_arg) == 2
    assert history_arg[0]["role"] == "user"
    assert history_arg[1]["role"] == "assistant"
    assert history_arg[1]["content"][0]["text"] == "response"
