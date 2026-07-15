"""
LiteInitiative - AI 决策与执行模块
"""
from __future__ import annotations

import json
from typing import Optional

from astrbot.api import logger
from astrbot.api.event import MessageChain

from astrbot.core.cron.events import CronMessageEvent
from astrbot.core.astr_main_agent import build_main_agent, MainAgentBuildConfig
from astrbot.core.platform.message_session import MessageSession

from .time_utils import _get_now_tz, _format_time_delta
from .data_types import Trigger


def build_agent_config(context, umo: str) -> Optional[MainAgentBuildConfig]:
    """构建 MainAgentBuildConfig，返回 MainAgentBuildConfig 实例或 None"""
    try:
        astr_conf = context.get_config(umo=umo)
        provider_settings = astr_conf.get("provider_settings", {}) if astr_conf else {}
        config_fields = getattr(MainAgentBuildConfig, "__dataclass_fields__", {})
        config_kwargs = {
            "tool_call_timeout": provider_settings.get("tool_call_timeout", 120),
            "tool_schema_mode": "full",
            "streaming_response": False,
            "sanitize_context_by_modalities": provider_settings.get("sanitize_context_by_modalities", False),
            "context_limit_reached_strategy": provider_settings.get("context_limit_reached_strategy", "truncate_by_turns"),
            "llm_compress_instruction": provider_settings.get("llm_compress_instruction", ""),
            "llm_compress_provider_id": provider_settings.get("llm_compress_provider_id", ""),
            "max_context_length": provider_settings.get("max_context_length", -1),
            "dequeue_context_length": provider_settings.get("dequeue_context_length", 1),
            "llm_safety_mode": False,
            "safety_mode_strategy": provider_settings.get("safety_mode_strategy", "system_prompt"),
            "computer_use_runtime": provider_settings.get("computer_use_runtime", "local"),
            "sandbox_cfg": provider_settings.get("sandbox", {}),
            "provider_settings": provider_settings,
            "timezone": astr_conf.get("timezone") if astr_conf else None,
            "max_quoted_fallback_images": provider_settings.get("max_quoted_fallback_images", 20),
        }
        if "llm_compress_keep_recent_ratio" in config_fields:
            config_kwargs["llm_compress_keep_recent_ratio"] = provider_settings.get("llm_compress_keep_recent_ratio", 0.15)
        elif "llm_compress_keep_recent" in config_fields:
            config_kwargs["llm_compress_keep_recent"] = provider_settings.get("llm_compress_keep_recent", 4)

        # 只传入 config_fields 中存在的键
        filtered_kwargs = {k: v for k, v in config_kwargs.items() if k in config_fields}
        return MainAgentBuildConfig(**filtered_kwargs)
    except Exception as e:
        logger.error(f"[LiteInitiative] 构建 AgentConfig 失败: {e}")
        return None


async def run_ai_decision(
    context,
    config_reader,
    umo: str,
    trigger_list: list,
    decision_prompt: str,
) -> bool:
    """运行 AI 决策，返回是否成功"""
    if umo.count(":") < 2:
        logger.error(f"[LiteInitiative] 无效的 UMO：{umo}，跳过决策")
        return False
    
    # 构建动态提示
    tz = config_reader.get_tz()
    now = _get_now_tz(tz)
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    
    date_tip = ""
    if config_reader.get_inject_date_tip():
        date_tip = (
            f"\n当前时间: {now_str}\n"
            f"时区: {tz or '系统默认'}\n"
            f"会话 ID: {umo}\n"
        )

    suggest_direct_send = config_reader.get_suggest_direct_send()
    suggest_prompt = ""
    if suggest_direct_send:
        suggest_prompt = config_reader.get_suggest_direct_send_prompt()
        if not suggest_prompt:
            logger.warning("[LiteInitiative] 未设置直接发送建议提示词，将使用默认提示词")

            # 若未自定义，使用默认
            suggest_prompt = (
                "如果需要立即发送主动消息，或在短时间内（例如 5 分钟以内）主动发送，"
                "请直接使用 `send_message_to_user` 工具发送，无需创建触发器，"
                "这样可以避免一次额外的模型调用。对于更长时间的延迟或需要等待合适时机，"
                "则可以使用 `create_trigger` 创建触发器。"
            )

    # 最小延迟提示（强制限制）
    min_delay = config_reader.get_min_trigger_delay()
    delay_tip = ""
    if min_delay > 0:
        delay_tip = (
            f"⚠️ 硬性限制：触发器必须至少延迟 {min_delay} 秒才能创建。"
            f"若需在 {min_delay} 秒内主动发言，请务必使用 `send_message_to_user` 工具，"
            f"试图创建短时触发器将被拒绝。\n"
        )
    
    full_prompt = (
        f"{date_tip}\n"
        f"当前触发器队列：\n"
        f"{json.dumps(trigger_list, ensure_ascii=False, indent=2) if trigger_list else '(无)'}\n\n"
        f"{decision_prompt}\n\n"
        f"要求：\n"
        f"1. 如果需要主动说话，请使用 create_trigger 创建触发器。\n"
        f"   fire_at_str 使用自然语言时间，例如：'21:30:00'（今天21:30，若已过则次日）、'After 1 hour 30 minutes'（1小时30分钟后）、'After 01:30:00'（1小时30分钟后）。\n"
        f"   extra_prompt 请写明说什么内容、怎么称呼用户、语气风格、有没有需要完成的任务，会不会需要使用以及使用哪些 Agent 能力等。\n"
        f"2. 如果认为不需要主动说话，或者觉得触发器过多/时间冲突，请使用 delete_trigger 或 update_trigger 管理。\n"
        f"3. 睡眠时段 {config_reader.get_sleep_hours()} 内禁止创建触发器，create_trigger 将拒绝创建。\n"
        f"4. 对于非闲聊性质的定时任务（如闹钟、提醒、定时报告），请使用 future_task 函数工具（平台内置），不要用本插件的触发器。"
        f"future_task 创建的定时任务不会被用户消息清空。\n"
        f"5. {suggest_prompt}\n"
        f"{delay_tip}"
    )
    
    try:
        session = MessageSession.from_str(umo)
        cron_event = CronMessageEvent(
            context=context,
            session=session,
            message=full_prompt,
            extras={"lite_initiative_decision": True},
        )
        
        config = build_agent_config(context, umo)
        if not config:
            return False
        
        # 获取决策专用 provider（如有）
        decision_provider_id = config_reader.get_decision_provider()
        provider = None
        if decision_provider_id:
            try:
                provider = await context.provider_manager.get_provider_by_id(decision_provider_id)
                if provider is None:
                    logger.info(f"[LiteInitiative] 未找到提供商 '{decision_provider_id}'，将使用默认模型。")
            except Exception as e:
                logger.warning(f"[LiteInitiative] 获取提供商失败: {e}，使用默认模型。")
 
        result = await build_main_agent(
            event=cron_event,
            plugin_context=context,
            config=config,
            provider=provider,
            req=None,
            apply_reset=True,
        )
        
        if not result or not result.agent_runner:
            return False
        
        runner = result.agent_runner
        async for _ in runner.step_until_done(30):
            pass
        
        llm_resp = runner.get_final_llm_resp()
        if llm_resp and llm_resp.completion_text:
            logger.info(f"[LiteInitiative] AI 决策完成({umo}): {llm_resp.completion_text[:80]}...")
            return True
        return False
    except Exception as e:
        logger.error(f"[LiteInitiative] AI 决策失败({umo}): {e}", exc_info=True)
        return False


async def run_trigger(context, config_reader, trigger: Trigger) -> tuple[Optional[str], bool]:
    """执行触发器，返回 (回复文本, 是否发送成功)"""
    if trigger.direct_send:
        return await run_trigger_plain(context, trigger)
    else:
        return await run_trigger_agent(context, trigger)


async def run_trigger_agent(context, trigger: Trigger) -> tuple[Optional[str], bool]:
    """使用 Agent 能力执行触发器"""
    try:
        umo = trigger.session or ""
        session = MessageSession.from_str(umo)
        cron_event = CronMessageEvent(
            context=context,
            session=session,
            message=trigger.extra_prompt or "你决定主动和用户聊聊天吧，自然一点。",
            extras={"lite_initiative_proactive": True, "trigger_id": trigger.trigger_id},
        )

        cfg = context.get_config(umo=umo)
        trigger_owner = trigger.sender_id
        admin_ids = cfg.get("admin_id", [])
        if trigger_owner in admin_ids:
            cron_event.role = "admin"
        
        config = build_agent_config(context, umo)
        if not config:
            return None, False
        
        result = await build_main_agent(
            event=cron_event,
            plugin_context=context,
            config=config,
            provider=None,
            req=None,
            apply_reset=True,
        )
        
        if not result or not result.agent_runner:
            return None, False
        
        runner = result.agent_runner
        async for _ in runner.step_until_done(30):
            pass
        
        llm_resp = runner.get_final_llm_resp()
        if llm_resp and llm_resp.completion_text:
            text = llm_resp.completion_text.strip()
            chain = MessageChain().message(text)
            logger.info(f"[LiteInitiative] 准备发送主动消息到{umo}")
            await context.send_message(umo, chain)
            return text, True
        return None, False
    except Exception as e:
        logger.error(f"[LiteInitiative] Agent 执行失败: {e}", exc_info=True)
        return None, False


async def run_trigger_plain(context, trigger: Trigger) -> tuple[Optional[str], bool]:
    """降级纯文本发送"""
    try:
        umo = trigger.session or ""
        text = trigger.extra_prompt or "主动来打个招呼吧~"
        chain = MessageChain().message(text)
        await context.send_message(umo, chain)
        return text, True
    except Exception as e:
        logger.error(f"[LiteInitiative] 降级发送失败: {e}")
        return None, False


async def save_proactive_history(context, umo: str, response_text: str) -> None:
    """保存主动发言的历史记录"""
    try:
        conv_mgr = context.conversation_manager
        if not conv_mgr:
            return
        curr_cid = await conv_mgr.get_curr_conversation_id(umo)
        if not curr_cid:
            return
        conversation = await conv_mgr.get_conversation(umo, curr_cid)
        if not conversation:
            return
        
        # conversation.history 是 JSON 字符串
        history_str = conversation.history
        if history_str:
            history = json.loads(history_str)
        else:
            history = []
        
        # 追加主动发言记录（使用纯 dict，与 DB 格式一致）
        history.append({
            "role": "user",
            "content": [{"type": "text", "text": "[LiteInitiative主动]"}]
        })
        history.append({
            "role": "assistant",
            "content": [{"type": "text", "text": response_text}]
        })
        
        # 保存回数据库
        await conv_mgr.update_conversation(umo, curr_cid, history=history)
    except Exception as e:
        logger.warning(f"[LiteInitiative] 保存历史失败: {e}")
