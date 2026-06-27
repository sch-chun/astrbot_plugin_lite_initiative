#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LiteInitiative - AI 决策与执行模块
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional, Tuple

from astrbot.api import logger
from astrbot.api.event import MessageChain
from astrbot.api.message_components import Plain

from astrbot.core.cron.events import CronMessageEvent
from astrbot.core.astr_main_agent import build_main_agent, MainAgentBuildConfig
from astrbot.core.platform.message_session import MessageSession
from astrbot.core.agent.message import UserMessageSegment, AssistantMessageSegment, TextPart

from .time_utils import _get_now_tz, _format_time_delta, calc_sleep_end_unix
from .data_types import Trigger


def build_agent_config(context, umo: str) -> Optional[MainAgentBuildConfig]:
    """构建 MainAgentBuildConfig，返回 MainAgentBuildConfig 实例或 None"""
    try:
        astr_conf = context.get_config(umo=umo)
        provider_settings = astr_conf.get("provider_settings", {}) if astr_conf else {}
        config_fields = getattr(MainAgentBuildConfig, "__dataclass_fields__", {})
        config_kwargs = {
            "tool_call_timeout": provider_settings.get("tool_call_timeout", 120),
            "tool_schema_mode": provider_settings.get("tool_schema_mode", "full"),
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


async def get_history_text(context, umo: str, max_messages: int) -> str:
    """获取会话历史消息文本"""
    try:
        conv_mgr = context.conversation_manager
        if not conv_mgr:
            return ""
        curr_cid = await conv_mgr.get_curr_conversation_id(umo)
        if not curr_cid:
            return ""
        conv = await conv_mgr.get_conversation(umo, curr_cid)
        if not conv:
            return ""
        messages = getattr(conv, "messages", []) or []
        lines = []
        for msg in messages[-max_messages:]:
            role = getattr(msg, "role", "unknown")
            content_parts = getattr(msg, "content", []) or []
            text_parts = []
            for part in content_parts:
                if hasattr(part, "text"):
                    text_parts.append(part.text)
                elif isinstance(part, str):
                    text_parts.append(part)
            text = "".join(text_parts).strip()
            if text:
                role_str = "用户" if role == "user" else "AI"
                lines.append(f"{role_str}: {text}")
        return "\n".join(lines)
    except Exception as e:
        logger.warning(f"[LiteInitiative] 获取历史消息失败: {e}")
        return ""


async def run_ai_decision(
    context,
    config_reader,
    umo: str,
    trigger_list: list,
    silence_sec: float,
    decision_prompt: str,
    max_history: int,
) -> bool:
    """运行 AI 决策，返回是否成功"""
    tz = config_reader.get_tz()
    now = _get_now_tz(tz)
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    
    history_text = await get_history_text(context, umo, max_history)
    
    date_tip = ""
    if config_reader.get_inject_date_tip():
        date_tip = (
            f"\n当前时间: {now_str}\n"
            f"时区: {tz or '系统默认'}\n"
            f"沉默时长: {_format_time_delta(silence_sec)}\n"
            f"会话 ID: {umo}\n"
        )
    
    full_prompt = (
        f"{date_tip}\n"
        f"历史对话（最近消息）：\n"
        f"{history_text if history_text else '(无历史消息)'}\n\n"
        f"当前触发器队列：\n"
        f"{json.dumps(trigger_list, ensure_ascii=False, indent=2) if trigger_list else '(无)'}\n\n"
        f"{decision_prompt}\n\n"
        f"要求：\n"
        f"1. 如果需要主动说话，请使用 create_trigger 创建触发器。\n"
        f"   fire_at_str 使用自然语言时间，例如：'21:30:00'（今天21:30，若已过则次日）、'After 1 hour 30 minutes'（1小时30分钟后）、'After 01:30:00'（1小时30分钟后）。\n"
        f"   extra_prompt 请写明说什么内容、怎么称呼用户、语气风格、有没有需要完成的任务，会不会需要使用以及使用哪些 Agent 能力等。\n"
        f"2. 如果认为不需要主动说话，或者觉得触发器过多/时间冲突，请使用 delete_trigger 或 update_trigger 管理。\n"
        f"3. 睡眠时段 {config_reader.get_sleep_hours()} 内不要创建触发器。\n"
        f"4. 对于非闲聊性质的定时任务（如闹钟、提醒、定时报告），请使用 future_task 函数工具（平台内置），不要用本插件的触发器。"
        f"future_task 创建的定时任务不会被用户消息清空。\n"
        f"5. 用户刚刚发过消息后不要立即创建触发器，至少等待一段时间。"
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
 
        result = await build_main_agent(
            event=cron_event,
            plugin_context=context,
            config=config,
            provider=None,
            req=None,
            apply_reset=True,   # ← 修复！apply_reset=True 确保 agent_runner 初始化 _state
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


async def run_trigger(context, config_reader, trigger: Trigger) -> Tuple[Optional[str], bool]:
    """执行触发器，返回 (回复文本, 是否发送成功)"""
    # 根据 use_agent 选择执行方式
    if trigger.use_agent:
        return await run_trigger_agent(context, trigger)
    else:
        return await run_trigger_plain(context, trigger)


async def run_trigger_agent(context, trigger: Trigger) -> Tuple[Optional[str], bool]:
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
        
        config = build_agent_config(context, umo)
        if not config:
            return None, False
        
        result = await build_main_agent(
            event=cron_event,
            plugin_context=context,
            config=config,
            provider=None,
            req=None,
            apply_reset=True,   # ← 同样修复 run_trigger_agent
        )
        
        if not result or not result.agent_runner:
            return None, False
        
        runner = result.agent_runner
        async for _ in runner.step_until_done(30):
            pass
        
        llm_resp = runner.get_final_llm_resp()
        sent = getattr(cron_event, "_has_send_oper", False)
        if llm_resp and llm_resp.completion_text:
            return llm_resp.completion_text.strip(), sent
        return None, sent
    except Exception as e:
        logger.error(f"[LiteInitiative] Agent 执行失败: {e}", exc_info=True)
        return None, False


async def run_trigger_plain(context, trigger: Trigger) -> Tuple[Optional[str], bool]:
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


async def save_proactive_history(context, umo: str, response_text: str):
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
        history = getattr(conversation, "messages", None)
        if history is not None:
            history.append(
                UserMessageSegment(
                    role="user",
                    content=[TextPart(text="[LiteInitiative主动]")],
                )
            )
            history.append(
                AssistantMessageSegment(
                    role="assistant",
                    content=[TextPart(text=response_text)],
                )
            )
    except Exception as e:
        logger.warning(f"[LiteInitiative] 保存历史失败: {e}")