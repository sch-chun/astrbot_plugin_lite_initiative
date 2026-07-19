import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import json

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

from typing import AsyncGenerator


TEST_SESSION = "platform:FriendMessage:user123"


def test_build_agent_config(mock_context: MagicMock) -> None:
    config = build_agent_config(mock_context, TEST_SESSION)
    assert config is not None
    # 模拟get_config异常
    mock_context.get_config = MagicMock(side_effect=Exception("fail"))
    config = build_agent_config(mock_context, TEST_SESSION)
    assert config is None


@pytest.mark.asyncio
async def test_run_ai_decision(mock_context: MagicMock, sample_config_dict: dict) -> None:

    # 模拟 step_until_done 为异步生成器
    async def mock_step_until_done(timeout: int) -> AsyncGenerator:
        yield

    with patch('src.decision.build_main_agent') as mock_build:
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
    with patch('src.decision.build_main_agent') as mock_build:
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
async def test_run_trigger_agent(mock_context: MagicMock) -> None:
    async def mock_step_until_done(timeout: int) -> AsyncGenerator:
        yield

    trigger = Trigger(
        trigger_id="t1",
        session=TEST_SESSION,
        extra_prompt="hello",
        direct_send=False   # 走agent
    )
    with patch('src.decision.build_main_agent') as mock_build:
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
async def test_run_trigger_plain(mock_context: MagicMock) -> None:
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
async def test_run_trigger_dispatch(mock_context: MagicMock) -> None:
    trigger_agent = Trigger(direct_send=False, extra_prompt="agent")
    trigger_plain = Trigger(direct_send=True, extra_prompt="plain")
    with patch('src.decision.run_trigger_agent', return_value=("agent", True)) as mock_agent:
        with patch('src.decision.run_trigger_plain', return_value=("plain", True)) as mock_plain:
            config_reader = ConfigReader({})
            text, sent = await run_trigger(mock_context, config_reader, trigger_agent)
            mock_agent.assert_called_once()
            text, sent = await run_trigger(mock_context, config_reader, trigger_plain)
            mock_plain.assert_called_once()


@pytest.mark.asyncio
async def test_save_proactive_history(mock_context: MagicMock) -> None:
    """
    测试保存主动历史记录的功能
    验证在调用 save_proactive_history 函数后，对话历史是否正确更新
    """
    # 创建一个模拟的对话对象，并设置初始历史记录为空列表
    conv = MagicMock()
    conv.history = '[]'

    # 设置模拟的上下文对象，使其返回特定的会话 ID 和对话对象
    mock_context.conversation_manager.get_curr_conversation_id = AsyncMock(return_value="cid")
    mock_context.conversation_manager.get_conversation = AsyncMock(return_value=conv)

    # 调用要测试的函数，传入模拟上下文、测试会话和响应内容
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


def _make_assistant_msg_with_tool_call(text: str, tool_call_id: str = "call_1", session: str | None = None) -> MagicMock:
    msg = MagicMock()
    msg.role = "assistant"
    tc = MagicMock()
    tc.function = MagicMock()
    tc.function.name = "send_message_to_user"
    args: dict[str, object] = {"messages": [{"type": "plain", "text": text}]}
    if session:
        args["session"] = session
    tc.function.arguments = json.dumps(args)
    tc.id = tool_call_id
    msg.tool_calls = [tc]
    return msg


def _make_tool_result_msg(tool_call_id: str, success: bool = True) -> MagicMock:
    """构造工具返回消息"""
    msg = MagicMock()
    msg.role = "tool"
    msg.tool_call_id = tool_call_id
    msg.content = "Message sent to session ..." if success else "error: something went wrong"
    return msg


def _make_old_history_msg() -> MagicMock:
    """构造一条历史消息（不会被处理）"""
    msg = MagicMock()
    msg.role = "user"
    msg.content = "历史消息"
    return msg


@pytest.mark.asyncio
@patch('src.decision.build_agent_config')
async def test_run_ai_decision_saves_send_message(
    mock_build_config: MagicMock,
    mock_context: MagicMock,
    sample_config_dict: dict
) -> None:
    """正常场景：发送消息应保存历史"""
    mock_build_config.return_value = MagicMock()

    history_msg = _make_old_history_msg()
    assistant_msg = _make_assistant_msg_with_tool_call("你好，主动消息！")
    tool_msg = _make_tool_result_msg("call_1", success=True)

    # 初始 messages 仅包含历史消息
    messages = [history_msg]
    mock_runner = AsyncMock()
    mock_runner.run_context = MagicMock()
    mock_runner.run_context.messages = messages

    async def mock_step_until_done(timeout: int) -> AsyncGenerator:
        # 模拟 step 执行后追加新消息
        messages.append(assistant_msg)
        messages.append(tool_msg)
        yield

    mock_runner.step_until_done = mock_step_until_done
    mock_runner.get_final_llm_resp = MagicMock(return_value=MagicMock(completion_text="完成"))

    with patch('src.decision.build_main_agent', return_value=MagicMock(agent_runner=mock_runner)):
        with patch('src.decision.save_proactive_history') as mock_save:
            config_reader = ConfigReader(sample_config_dict)
            result = await run_ai_decision(
                context=mock_context,
                config_reader=config_reader,
                umo=TEST_SESSION,
                trigger_list=[],
                decision_prompt="prompt"
            )
            assert result is True
            mock_save.assert_awaited_once_with(mock_context, TEST_SESSION, "你好，主动消息！")


@pytest.mark.asyncio
@patch('src.decision.build_agent_config')
async def test_run_ai_decision_cross_session(
    mock_build_config: MagicMock,
    mock_context: MagicMock,
    sample_config_dict: dict
) -> None:
    mock_build_config.return_value = MagicMock()

    target_session = "platform:FriendMessage:target_user"
    history_msg = _make_old_history_msg()
    assistant_msg = _make_assistant_msg_with_tool_call("你好，跨会话消息！", session=target_session)
    tool_msg = _make_tool_result_msg("call_1", success=True)

    messages = [history_msg]
    mock_runner = AsyncMock()
    mock_runner.run_context = MagicMock()
    mock_runner.run_context.messages = messages

    async def mock_step_until_done(timeout: int) -> AsyncGenerator:
        messages.append(assistant_msg)
        messages.append(tool_msg)
        yield

    mock_runner.step_until_done = mock_step_until_done
    mock_runner.get_final_llm_resp = MagicMock(return_value=MagicMock(completion_text="完成"))

    with patch('src.decision.build_main_agent', return_value=MagicMock(agent_runner=mock_runner)):
        with patch('src.decision.save_proactive_history') as mock_save:
            config_reader = ConfigReader(sample_config_dict)
            await run_ai_decision(
                context=mock_context,
                config_reader=config_reader,
                umo=TEST_SESSION,
                trigger_list=[],
                decision_prompt="prompt"
            )
            mock_save.assert_awaited_once_with(mock_context, target_session, "你好，跨会话消息！")


@pytest.mark.asyncio
async def test_run_ai_decision_skip_failed(
    mock_context: MagicMock, sample_config_dict: dict
) -> None:
    """发送失败：不应保存"""
    mock_runner = AsyncMock()
    assistant_msg = _make_assistant_msg_with_tool_call("失败消息")
    tool_msg = _make_tool_result_msg("call_1", success=False)  # 返回 error
    mock_runner.run_context = MagicMock(messages=[assistant_msg, tool_msg])
    mock_runner.step_until_done = AsyncMock()
    mock_runner.get_final_llm_resp = MagicMock(return_value=MagicMock(completion_text="完成"))

    with patch('src.decision.build_main_agent', return_value=MagicMock(agent_runner=mock_runner)):
        with patch('src.decision.save_proactive_history') as mock_save:
            config_reader = ConfigReader(sample_config_dict)
            await run_ai_decision(
                context=mock_context,
                config_reader=config_reader,
                umo=TEST_SESSION,
                trigger_list=[],
                decision_prompt="prompt"
            )
            mock_save.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_ai_decision_no_tool_call(
    mock_context: MagicMock, sample_config_dict: dict
) -> None:
    """无工具调用：不保存"""
    mock_runner = AsyncMock()

    # 只有普通 assistant 消息，无 tool_calls
    msg = MagicMock()
    msg.role = "assistant"
    msg.tool_calls = None
    mock_runner.run_context = MagicMock(messages=[msg])
    mock_runner.step_until_done = AsyncMock()
    mock_runner.get_final_llm_resp = MagicMock(return_value=MagicMock(completion_text="完成"))

    with patch('src.decision.build_main_agent', return_value=MagicMock(agent_runner=mock_runner)):
        with patch('src.decision.save_proactive_history') as mock_save:
            config_reader = ConfigReader(sample_config_dict)
            await run_ai_decision(
                context=mock_context,
                config_reader=config_reader,
                umo=TEST_SESSION,
                trigger_list=[],
                decision_prompt="prompt"
            )
            mock_save.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_ai_decision_holiday_injection(
    mock_context: MagicMock, sample_config_dict: dict
) -> None:
    """测试节假日信息正确注入"""

    # 模拟 chinese_calendar 模块
    with patch.dict('sys.modules', {'chinese_calendar': MagicMock()}) as mock_modules:
        mock_cc = mock_modules['chinese_calendar']
        mock_cc.is_holiday.return_value = True
        mock_cc.get_holiday_detail.return_value = ("春节",)
        mock_cc.is_workday.return_value = False

        # 配置开启注入
        config_dict = {**sample_config_dict, "inject_date_tip": True}
        config_reader = ConfigReader(config_dict)

        # 模拟 build_main_agent 直接返回
        with patch('src.decision.build_main_agent') as mock_build:
            mock_runner = AsyncMock()

            async def mock_step_until_done(timeout: int) -> AsyncGenerator:
                yield

            mock_runner.step_until_done = mock_step_until_done
            mock_runner.get_final_llm_resp = MagicMock(return_value=MagicMock(completion_text="ok"))
            mock_result = MagicMock()
            mock_result.agent_runner = mock_runner
            mock_build.return_value = mock_result

            # 捕获 full_prompt 构建过程
            # 因为 run_ai_decision 内部会构建 full_prompt，我们无法直接获取，但可以验证最终调用 build_main_agent 时的 event.message
            await run_ai_decision(
                context=mock_context,
                config_reader=config_reader,
                umo=TEST_SESSION,
                trigger_list=[],
                decision_prompt="prompt"
            )

            # 检查 build_main_agent 调用中的 event.message 是否包含节假日信息
            call_args = mock_build.call_args
            event = call_args[1]['event']
            assert "📅 今日是 春节。" in event.message_str
            assert "时区" in event.message_str
            assert "会话 ID" in event.message_str

    # 测试非工作日（周末）
    with patch.dict('sys.modules', {'chinese_calendar': MagicMock()}) as mock_modules:
        mock_cc = mock_modules['chinese_calendar']
        mock_cc.is_holiday.return_value = False
        mock_cc.is_workday.return_value = False  # 周末

        config_dict = {**sample_config_dict, "inject_date_tip": True}
        config_reader = ConfigReader(config_dict)

        with patch('src.decision.build_main_agent') as mock_build:
            mock_runner = AsyncMock()

            async def mock_step_until_done(timeout: int) -> AsyncGenerator:
                yield

            mock_runner.step_until_done = mock_step_until_done
            mock_runner.get_final_llm_resp = MagicMock(return_value=MagicMock(completion_text="ok"))
            mock_result = MagicMock()
            mock_result.agent_runner = mock_runner
            mock_build.return_value = mock_result

            await run_ai_decision(
                context=mock_context,
                config_reader=config_reader,
                umo=TEST_SESSION,
                trigger_list=[],
                decision_prompt="prompt"
            )
            event = mock_build.call_args[1]['event']
            assert "📅 今日是非工作日。" in event.message_str

    # 测试工作日
    with patch.dict('sys.modules', {'chinese_calendar': MagicMock()}) as mock_modules:
        mock_cc = mock_modules['chinese_calendar']
        mock_cc.is_holiday.return_value = False
        mock_cc.is_workday.return_value = True

        config_dict = {**sample_config_dict, "inject_date_tip": True}
        config_reader = ConfigReader(config_dict)

        with patch('src.decision.build_main_agent') as mock_build:
            mock_runner = AsyncMock()

            async def mock_step_until_done(timeout: int) -> AsyncGenerator:
                yield

            mock_runner.step_until_done = mock_step_until_done
            mock_runner.get_final_llm_resp = MagicMock(return_value=MagicMock(completion_text="ok"))
            mock_result = MagicMock()
            mock_result.agent_runner = mock_runner
            mock_build.return_value = mock_result

            await run_ai_decision(
                context=mock_context,
                config_reader=config_reader,
                umo=TEST_SESSION,
                trigger_list=[],
                decision_prompt="prompt"
            )
            event = mock_build.call_args[1]['event']
            assert "📅 今日是工作日。" in event.message_str


@pytest.mark.asyncio
async def test_run_ai_decision_holiday_injection_disabled(
    mock_context: MagicMock, sample_config_dict: dict
) -> None:
    """配置关闭时，不注入节假日信息"""
    config_dict = {**sample_config_dict, "inject_date_tip": False}
    config_reader = ConfigReader(config_dict)

    with patch('src.decision.build_main_agent') as mock_build:
        mock_runner = AsyncMock()
        
        async def mock_step_until_done(timeout: int) -> AsyncGenerator:
            yield
        
        mock_runner.step_until_done = mock_step_until_done
        mock_runner.get_final_llm_resp = MagicMock(return_value=MagicMock(completion_text="ok"))
        mock_result = MagicMock()
        mock_result.agent_runner = mock_runner
        mock_build.return_value = mock_result

        await run_ai_decision(
            context=mock_context,
            config_reader=config_reader,
            umo=TEST_SESSION,
            trigger_list=[],
            decision_prompt="prompt"
        )
        event = mock_build.call_args[1]['event']
        assert "📅" not in event.message_str  # 没有节假日符号
        
        # 但日期基础信息应保留（因为 date_tip 独立于 holiday_tip）
        assert "当前时间:" in event.message_str
        assert "时区:" in event.message_str


@pytest.mark.asyncio
async def test_run_ai_decision_holiday_import_error(
    mock_context: MagicMock, sample_config_dict: dict
) -> None:
    """当 chinese_calendar 未安装时，应静默跳过，不报错"""

    # 确保模块不存在
    with patch.dict('sys.modules', {'chinese_calendar': None}):
        config_dict = {**sample_config_dict, "inject_date_tip": True}
        config_reader = ConfigReader(config_dict)

        with patch('src.decision.build_main_agent') as mock_build:
            mock_runner = AsyncMock()
            
            async def mock_step_until_done(timeout: int) -> AsyncGenerator:
                yield

            mock_runner.step_until_done = mock_step_until_done
            mock_runner.get_final_llm_resp = MagicMock(return_value=MagicMock(completion_text="ok"))
            mock_result = MagicMock()
            mock_result.agent_runner = mock_runner
            mock_build.return_value = mock_result

            # 不会抛出异常
            await run_ai_decision(
                context=mock_context,
                config_reader=config_reader,
                umo=TEST_SESSION,
                trigger_list=[],
                decision_prompt="prompt"
            )
            event = mock_build.call_args[1]['event']

            # 应没有节假日信息
            assert "📅" not in event.message_str

            # 但日期基础信息仍然存在
            assert "当前时间:" in event.message_str
