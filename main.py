#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LiteInitiative - AI 驱动的智能主动闲聊插件
"""

from __future__ import annotations

import asyncio
import json
import os
import time

from astrbot.api import logger
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register

# 兼容导入
try:
    from astrbot.core.cron.events import CronMessageEvent
    from astrbot.core.astr_main_agent import build_main_agent, MainAgentBuildConfig
    from astrbot.core.platform.message_session import MessageSession
    from astrbot.core.star.star_handler import EventType
    HAS_AGENT_PIPELINE = True
except ImportError:
    HAS_AGENT_PIPELINE = False

try:
    from astrbot.api import llm_tool
    HAS_LLM_TOOL = True
except ImportError:
    HAS_LLM_TOOL = False
    def llm_tool(*args, **kwargs):
        def decorator(func):
            return func
        return decorator

try:
    from astrbot.core.agent.message import UserMessageSegment, AssistantMessageSegment, TextPart
    HAS_NEW_MESSAGE_API = True
except ImportError:
    HAS_NEW_MESSAGE_API = False

# 本地模块导入
from utils import _get_now_tz, _parse_time_str, _is_in_sleep_hours, _format_time_delta, _parse_trigger_time
from models import Trigger, SessionRuntime
from tools import LLMFunctions


@register(
    "astrbot_plugin_lite_initiative",
    "sch-chun",
    "AI 驱动的智能主动闲聊插件：超时决策 + 定时分析 + AI 函数工具管理触发器队列",
    "0.1.0",
    "https://github.com/sch-chun/astrbot_plugin_lite_initiative",
)
class LiteInitiativePlugin(Star):
    def __init__(self, context: Context, config: Any):
        super().__init__(context)
        self.cfg = config
        self._triggers: Dict[str, Trigger] = {}
        self._session_runtime: Dict[str, SessionRuntime] = {}
        self._last_user_msg_unix: Dict[str, float] = {}
        self._scheduler_task: Optional[asyncio.Task] = None
        self._stopped: bool = False
        self._firing_trigger_ids: set = set()
        self._last_daily_analysis_minute: str = ""
        self._data_dir = ""
        self._trigger_file = ""
        self._state_file = ""
        self._init_paths()
        self._load_triggers()
        self._load_states()
        if HAS_LLM_TOOL:
            self._llm_funcs = LLMFunctions(self)
            self.context.activate_llm_tool("list_triggers")
            self.context.activate_llm_tool("create_trigger")
            self.context.activate_llm_tool("delete_trigger")
            self.context.activate_llm_tool("update_trigger")
            logger.info("[LiteInitiative] LLM 工具注册成功")

    async def initialize(self):
        self._scheduler_task = asyncio.create_task(self._scheduler_loop())
        logger.info("[LiteInitiative] 插件已激活，调度器已启动")

    async def terminate(self):
        self._stopped = True
        if self._scheduler_task:
            self._scheduler_task.cancel()
            try:
                await self._scheduler_task
            except asyncio.CancelledError:
                pass
        for rt in self._session_runtime.values():
            if rt.timeout_fire_task:
                rt.timeout_fire_task.cancel()
        self._save_triggers()
        self._save_states()
        logger.info("[LiteInitiative] 插件已停用")

    # ─────────────────────── 路径与持久化 ───────────────────────
    def _init_paths(self):
        try:
            from astrbot.api.star import StarTools
            base = StarTools.get_data_dir() / "astrbot_plugin_lite_initiative"
        except Exception:
            base = os.path.join(os.getcwd(), "data", "plugin_data", "astrbot_plugin_lite_initiative")
        self._data_dir = str(base)
        os.makedirs(self._data_dir, exist_ok=True)
        self._trigger_file = os.path.join(self._data_dir, "triggers.json")
        self._state_file = os.path.join(self._data_dir, "session_states.json")

    def _save_triggers(self):
        try:
            data = {tid: t.to_dict() for tid, t in self._triggers.items()}
            with open(self._trigger_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"[LiteInitiative] 保存触发器失败: {e}")

    def _load_triggers(self):
        if not os.path.exists(self._trigger_file):
            return
        try:
            with open(self._trigger_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._triggers = {k: Trigger.from_dict(v) for k, v in data.items()}
            logger.info(f"[LiteInitiative] 加载了 {len(self._triggers)} 个触发器")
        except Exception as e:
            logger.error(f"[LiteInitiative] 加载触发器失败: {e}")

    def _save_states(self):
        try:
            data = {sid: rt.to_dict() for sid, rt in self._session_runtime.items()}
            data["last_user_msg_unix"] = self._last_user_msg_unix
            with open(self._state_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"[LiteInitiative] 保存状态失败: {e}")

    def _load_states(self):
        if not os.path.exists(self._state_file):
            return
        try:
            with open(self._state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            for k, v in data.items():
                if k == "last_user_msg_unix":
                    self._last_user_msg_unix = v if isinstance(v, dict) else {}
                else:
                    self._session_runtime[k] = SessionRuntime.from_dict(v)
            logger.info(f"[LiteInitiative] 加载了 {len(self._session_runtime)} 个会话状态")
        except Exception as e:
            logger.error(f"[LiteInitiative] 加载状态失败: {e}")

    # ─────────────────────── 配置读取 ───────────────────────
    def _get_cfg(self, *keys, default=None):
        node = self.cfg
        for key in keys:
            if isinstance(node, dict):
                node = node.get(key)
            else:
                node = getattr(node, key, None)
            if node is None:
                return default
        return node if node is not None else default

    def _get_tz(self) -> Optional[str]:
        return self._get_cfg("timezone") or None

    def _get_sleep_hours(self) -> str:
        return self._get_cfg("sleep_hours") or ""

    def _get_max_triggers(self) -> int:
        return int(self._get_cfg("max_triggers") or 20)

    def _get_decision_timeout(self) -> int:
        return int(self._get_cfg("timeout_decision", "decision_timeout_seconds") or 300)

    def _get_decision_prompt(self) -> str:
        return self._get_cfg("timeout_decision", "decision_prompt") or "你是一个主动闲聊决策助手。"

    def _get_decision_max_history(self) -> int:
        return int(self._get_cfg("timeout_decision", "decision_max_history_messages") or 20)

    def _get_daily_analysis_times(self):
        raw = self._get_cfg("daily_analysis", "daily_analysis_times") or "09:00,14:00,21:00"
        result = []
        for part in raw.split(","):
            part = part.strip()
            t = _parse_time_str(part)
            if t:
                result.append(t)
        return result

    def _get_daily_analysis_prompt(self) -> str:
        return self._get_cfg("daily_analysis", "daily_analysis_prompt") or "你是一个对话分析助手。"

    def _get_daily_analysis_max_history(self) -> int:
        return int(self._get_cfg("daily_analysis", "daily_analysis_max_history_messages") or 50)

    def _get_inactive_threshold_hours(self) -> int:
        return int(self._get_cfg("daily_analysis", "inactive_threshold_hours") or 24)

    def _get_inject_date_tip(self) -> bool:
        return bool(self._get_cfg("inject_date_tip", True))

    def _get_trigger_persist(self) -> bool:
        return bool(self._get_cfg("trigger_persist", True))

    # ─────────────────────── 触发检查 ───────────────────────
    def _enforce_max_triggers(self):
        max_n = self._get_max_triggers()
        if len(self._triggers) <= max_n:
            return
        sorted_triggers = sorted(self._triggers.values(), key=lambda t: t.created_at)
        excess = len(self._triggers) - max_n
        for t in sorted_triggers[:excess]:
            tid = t.trigger_id
            del self._triggers[tid]
            logger.info(f"[LiteInitiative] 超出最大触发器数量，已丢弃触发器 {tid}")

    def _check_sleep_hours(self, fire_at_unix: float) -> bool:
        now = _get_now_tz(self._get_tz())
        tz = self._get_tz()
        fire_dt = datetime.fromtimestamp(fire_at_unix, tz=now.tzinfo if tz else None)
        return _is_in_sleep_hours(fire_dt, self._get_sleep_hours())

    def _check_user_recently_active(self, umo: str, hours: int) -> bool:
        if hours <= 0:
            return True
        last = self._last_user_msg_unix.get(umo, 0)
        if last <= 0:
            return False
        now_ts = time.time()
        return (now_ts - last) < hours * 3600

    # ─────────────────────── 触发器管理 ───────────────────────
    def _list_triggers_for_session(self, session: str = "") -> List[dict]:
        tlist = []
        for t in self._triggers.values():
            if not session or t.session == session:
                tlist.append(t.to_dict())
        tlist.sort(key=lambda x: x.get("fire_at_unix", 0))
        return tlist

    def _create_trigger_internal(
        self,
        fire_at_unix: float,
        session: str = "",
        extra_prompt: str = "",
        use_agent: bool = True,
        source: str = "manual",
        extra: Optional[dict] = None,
    ) -> Optional[Trigger]:
        if self._check_sleep_hours(fire_at_unix):
            now_ts = time.time()
            remaining = fire_at_unix - now_ts
            if remaining > 0:
                sleep_end = self._calc_sleep_end_unix()
                if sleep_end and sleep_end < fire_at_unix:
                    pass
                else:
                    return None
            else:
                return None

        t = Trigger(
            fire_at_unix=fire_at_unix,
            session=session,
            extra_prompt=extra_prompt,
            use_agent=use_agent,
            source=source,
            extra=extra or {},
        )
        self._triggers[t.trigger_id] = t
        self._enforce_max_triggers()
        self._save_triggers()
        return t

    def _delete_trigger_internal(self, trigger_id: str) -> bool:
        if trigger_id in self._triggers:
            del self._triggers[trigger_id]
            self._save_triggers()
            return True
        return False

    def _update_trigger_internal(
        self,
        trigger_id: str,
        fire_at_unix: Optional[float] = None,
        extra_prompt: Optional[str] = None,
        use_agent: Optional[bool] = None,
    ) -> Optional[Trigger]:
        t = self._triggers.get(trigger_id)
        if not t:
            return None
        if fire_at_unix is not None:
            if self._check_sleep_hours(fire_at_unix):
                return None
            t.fire_at_unix = fire_at_unix
        if extra_prompt is not None:
            t.extra_prompt = extra_prompt
        if use_agent is not None:
            t.use_agent = use_agent
        self._save_triggers()
        return t

    def _calc_sleep_end_unix(self) -> Optional[float]:
        now = _get_now_tz(self._get_tz())
        tz = self._get_tz()
        sleep_range = self._get_sleep_hours()
        if not sleep_range or "-" not in sleep_range:
            return None
        parts = sleep_range.split("-", 1)
        t_end = _parse_time_str(parts[1])
        if not t_end:
            return None
        end = now.replace(hour=t_end[0], minute=t_end[1], second=0, microsecond=0)
        if end <= now:
            end = end.replace(day=end.day + 1)
        return end.timestamp()

    # ─────────────────────── 消息事件 ───────────────────────
    @filter.on_llm_response()
    async def _on_llm_response(self, event: AstrMessageEvent, _response=None):
        """AI 回复完成后，启动超时决策计时器"""
        if event.get_extra("lite_initiative_proactive"):
            return
        umo = event.unified_msg_origin
        if umo not in self._session_runtime:
            self._session_runtime[umo] = SessionRuntime()
        rt = self._session_runtime[umo]
        rt.last_ai_reply_unix = time.time()
        if rt.timeout_fire_task:
            rt.timeout_fire_task.cancel()
            rt.timeout_fire_task = None
        timeout_sec = self._get_decision_timeout()
        rt.timeout_fire_task = asyncio.create_task(
            self._timeout_decision(umo, timeout_sec)
        )
        logger.debug(f"[LiteInitiative] 启动超时决策计时器: {umo}, 超时={timeout_sec}s")

    @filter.on_decorate_result()
    async def _on_decorate_result(self, event: AstrMessageEvent, result=None):
        """装饰结果后，启动超时决策计时器"""
        if event.get_extra("lite_initiative_proactive"):
            return
        umo = event.unified_msg_origin
        if umo not in self._session_runtime:
            self._session_runtime[umo] = SessionRuntime()
        rt = self._session_runtime[umo]
        rt.last_ai_reply_unix = time.time()
        if rt.timeout_fire_task:
            rt.timeout_fire_task.cancel()
            rt.timeout_fire_task = None
        timeout_sec = self._get_decision_timeout()
        rt.timeout_fire_task = asyncio.create_task(
            self._timeout_decision(umo, timeout_sec)
        )

    @filter.on_message()
    async def _on_user_message(self, event: AstrMessageEvent):
        """用户发消息时，更新最后活跃时间并清空超时触发器"""
        umo = event.unified_msg_origin
        self._last_user_msg_unix[umo] = time.time()
        if umo not in self._session_runtime:
            self._session_runtime[umo] = SessionRuntime()
        rt = self._session_runtime[umo]
        rt.last_user_msg_unix = time.time()
        if rt.timeout_fire_task:
            rt.timeout_fire_task.cancel()
            rt.timeout_fire_task = None
            logger.debug(f"[LiteInitiative] 用户发消息，取消超时决策: {umo}")
        now_ts = time.time()
        timeout_sec = self._get_decision_timeout()
        to_remove = []
        for t in self._triggers.values():
            if t.session == umo and t.source == "timeout":
                if t.fire_at_unix - now_ts <= timeout_sec + 60:
                    to_remove.append(t.trigger_id)
        for tid in to_remove:
            del self._triggers[tid]
            logger.debug(f"[LiteInitiative] 用户发消息，清空超时触发器: {tid}")
        if to_remove:
            self._save_triggers()

    # ─────────────────────── 超时决策 ───────────────────────
    async def _timeout_decision(self, umo: str, timeout_sec: int):
        try:
            await asyncio.sleep(timeout_sec)
        except asyncio.CancelledError:
            return
        rt = self._session_runtime.get(umo)
        if not rt:
            return
        now_ts = time.time()
        if rt.last_user_msg_unix > rt.last_ai_reply_unix:
            logger.debug(f"[LiteInitiative] 超时决策取消：用户已发新消息 {umo}")
            return
        last_active = max(rt.last_user_msg_unix or 0, rt.last_ai_reply_unix or 0)
        silence_sec = now_ts - last_active
        logger.info(f"[LiteInitiative] 超时决策触发: {umo}, 沉默 {_format_time_delta(silence_sec)}")
        await self._run_ai_decision(
            umo=umo,
            source="timeout",
            silence_sec=silence_sec,
            decision_prompt=self._get_decision_prompt(),
            max_history=self._get_decision_max_history(),
        )

    # ─────────────────────── 每日分析 ───────────────────────
    async def _daily_analysis_check(self):
        now = _get_now_tz(self._get_tz())
        current_hour = now.hour
        current_min = now.minute
        analysis_times = self._get_daily_analysis_times()
        if not analysis_times:
            return
        if (current_hour, current_min) not in analysis_times:
            return
        minute_key = now.strftime("%Y%m%d%H%M")
        if getattr(self, "_last_daily_analysis_minute", "") == minute_key:
            return
        self._last_daily_analysis_minute = minute_key
        now_ts = time.time()
        inactive_hours = self._get_inactive_threshold_hours()
        sessions_to_analyze = []
        for umo, last_ts in self._last_user_msg_unix.items():
            if inactive_hours <= 0 or (now_ts - last_ts) < inactive_hours * 3600:
                sessions_to_analyze.append(umo)
        if not sessions_to_analyze:
            logger.debug("[LiteInitiative] 每日分析：无活跃会话，跳过")
            return
        logger.info(f"[LiteInitiative] 每日分析触发：分析 {len(sessions_to_analyze)} 个会话")
        for umo in sessions_to_analyze:
            try:
                await self._run_ai_decision(
                    umo=umo,
                    source="daily_analysis",
                    silence_sec=now_ts - self._last_user_msg_unix.get(umo, now_ts),
                    decision_prompt=self._get_daily_analysis_prompt(),
                    max_history=self._get_daily_analysis_max_history(),
                )
            except Exception as e:
                logger.error(f"[LiteInitiative] 每日分析失败({umo}): {e}")

    # ─────────────────────── AI 决策核心 ───────────────────────
    async def _run_ai_decision(
        self,
        umo: str,
        source: str,
        silence_sec: float,
        decision_prompt: str,
        max_history: int,
    ):
        if not HAS_AGENT_PIPELINE:
            logger.warning("[LiteInitiative] Agent Pipeline 不可用，跳过 AI 决策")
            return
        tz = self._get_tz()
        now = _get_now_tz(tz)
        now_str = now.strftime("%Y-%m-%d %H:%M:%S")
        history_text = ""
        try:
            history_text = await self._get_history_text(umo, max_history)
        except Exception as e:
            logger.warning(f"[LiteInitiative] 获取历史消息失败: {e}")
        trigger_list = self._list_triggers_for_session(umo)
        date_tip = ""
        if self._get_inject_date_tip():
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
            f"决策来源：{source}\n\n"
            f"{decision_prompt}\n\n"
            f"要求：\n"
            f"1. 如果需要主动说话，请使用 create_trigger 创建触发器。\n"
            f"   fire_at_unix 使用 UNIX 时间戳（秒）。\n"
            f"   extra_prompt 请写明说什么内容、怎么称呼用户、语气风格等。\n"
            f"   source 字段填入 '{source}'。\n"
            f"2. 如果认为不需要主动说话，或者觉得触发器过多/时间冲突，请使用 delete_trigger 或 update_trigger 管理。\n"
            f"3. 睡眠时段 {self._get_sleep_hours()} 内不要创建触发器。\n"
            f"4. 对于非闲聊性质的定时任务（如闹钟、提醒、定时报告），请使用 future_task 函数工具（平台内置），不要用本插件的触发器。\n"
            f"5. 用户刚刚发过消息后不要立即创建触发器，至少等待一段时间。"
        )
        try:
            session = MessageSession.from_str(umo)
            cron_event = CronMessageEvent(
                context=self.context,
                session=session,
                message=full_prompt,
                extras={"lite_initiative_decision": True, "source": source},
            )
            astr_conf = self.context.get_config(umo=umo)
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
            config = MainAgentBuildConfig(**{k: v for k, v in config_kwargs.items() if k in config_fields})
            result = await build_main_agent(
                event=cron_event,
                plugin_context=self.context,
                config=config,
                provider=None,
                req=None,
                apply_reset=False,
            )
            if not result or not result.agent_runner:
                return
            runner = result.agent_runner
            async for _ in runner.step_until_done(30):
                pass
            llm_resp = runner.get_final_llm_resp()
            if llm_resp and llm_resp.completion_text:
                logger.info(f"[LiteInitiative] AI 决策完成({umo}): {llm_resp.completion_text[:80]}...")
        except Exception as e:
            logger.error(f"[LiteInitiative] AI 决策失败({umo}): {e}", exc_info=True)

    # ─────────────────────── 触发器执行 ───────────────────────
    async def _execute_trigger(self, trigger: Trigger):
        if trigger.trigger_id in self._firing_trigger_ids:
            return
        self._firing_trigger_ids.add(trigger.trigger_id)
        try:
            umo = trigger.session or ""
            logger.info(f"[LiteInitiative] 触发器执行: {trigger.trigger_id}, 会话={umo}")
            response_text, sent = await self._run_trigger(trigger)
            if sent and response_text:
                await self._save_proactive_history(umo, response_text)
                logger.info(f"[LiteInitiative] 触发器回复已发送: {trigger.trigger_id}")
        except Exception as e:
            logger.error(f"[LiteInitiative] 触发器执行失败({trigger.trigger_id}): {e}", exc_info=True)
        finally:
            self._firing_trigger_ids.discard(trigger.trigger_id)
            self._delete_trigger_internal(trigger.trigger_id)

    async def _run_trigger(self, trigger: Trigger) -> Tuple[Optional[str], bool]:
        if trigger.use_agent and HAS_AGENT_PIPELINE:
            return await self._run_trigger_agent(trigger)
        return await self._run_trigger_plain(trigger)

    async def _run_trigger_agent(self, trigger: Trigger) -> Tuple[Optional[str], bool]:
        try:
            umo = trigger.session or ""
            session = MessageSession.from_str(umo)
            cron_event = CronMessageEvent(
                context=self.context,
                session=session,
                message=trigger.extra_prompt or "你决定主动和用户聊聊天吧，自然一点。",
                extras={"lite_initiative_proactive": True, "trigger_id": trigger.trigger_id},
            )
            astr_conf = self.context.get_config(umo=umo)
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
            config = MainAgentBuildConfig(**{k: v for k, v in config_kwargs.items() if k in config_fields})
            result = await build_main_agent(
                event=cron_event,
                plugin_context=self.context,
                config=config,
                provider=None,
                req=None,
                apply_reset=False,
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

    async def _run_trigger_plain(self, trigger: Trigger) -> Tuple[Optional[str], bool]:
        try:
            umo = trigger.session or ""
            text = trigger.extra_prompt or "主动来打个招呼吧~"
            await self._send_text(umo, text, None)
            return text, True
        except Exception as e:
            logger.error(f"[LiteInitiative] 降级发送失败: {e}")
            return None, False

    async def _send_text(self, umo: str, text: str, event: Optional[AstrMessageEvent]) -> bool:
        try:
            session = MessageSession.from_str(umo)
            await session.send(text)
            return True
        except Exception:
            pass
        return False

    async def _save_proactive_history(self, umo: str, response_text: str, conversation=None):
        try:
            if conversation is None:
                conv_mgr = self.context.conversation_manager
                if not conv_mgr:
                    return
                curr_cid = await conv_mgr.get_curr_conversation_id(umo)
                if not curr_cid:
                    return
                conversation = await conv_mgr.get_conversation(umo, curr_cid)
            if not conversation:
                return
            cid = conversation.cid
            await self._add_message_pair_to_history(umo, cid, conversation, "[LiteInitiative主动]", response_text)
        except Exception as e:
            logger.warning(f"[LiteInitiative] 保存历史失败: {e}")

    async def _add_message_pair_to_history(self, umo: str, cid: str, conversation, prefix: str, text: str):
        try:
            if HAS_NEW_MESSAGE_API:
                history = getattr(conversation, "messages", None)
                if history is not None:
                    history.append(
                        UserMessageSegment(
                            role="user",
                            content=[TextPart(text=prefix)],
                        )
                    )
                    history.append(
                        AssistantMessageSegment(
                            role="assistant",
                            content=[TextPart(text=text)],
                        )
                    )
        except Exception as e:
            logger.debug(f"[LiteInitiative] 写入历史跳过: {e}")

    async def _get_history_text(self, umo: str, max_messages: int) -> str:
        try:
            conv_mgr = self.context.conversation_manager
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

    # ─────────────────────── 调度器 ───────────────────────
    async def _scheduler_loop(self):
        try:
            while not self._stopped:
                await asyncio.sleep(30)
                if self._stopped:
                    break
                await self._tick()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[LiteInitiative] Scheduler error: {e}")
        finally:
            logger.info("[LiteInitiative] Scheduler stopped.")

    async def _tick(self):
        now_ts = time.time()
        try:
            await self._daily_analysis_check()
        except Exception as e:
            logger.error(f"[LiteInitiative] 每日分析检查失败: {e}")
        for t in list(self._triggers.values()):
            if now_ts >= t.fire_at_unix:
                if t.trigger_id in self._firing_trigger_ids:
                    continue
                logger.info(f"[LiteInitiative] 触发器到期: {t.trigger_id}, 会话={t.session}")
                asyncio.create_task(self._execute_trigger(t))
        expired = [
            tid for tid, t in self._triggers.items()
            if t.fire_at_unix < now_ts - 86400
        ]
        for tid in expired:
            del self._triggers[tid]
        if expired:
            self._save_triggers()

    # ─────────────────────── 用户指令 ───────────────────────
    @filter.command("li_help")
    async def _cmd_help(self, event: AstrMessageEvent):
        """查看 LiteInitiative 插件帮助"""
        help_text = (
            "LiteInitiative 插件使用指南：\n\n"
            "核心功能：\n"
            "1. 超时决策：AI 回复后等待一段时间，如果用户没回复，AI 会自动判断是否要主动找用户聊天\n"
            "2. 每日分析：在设定时间点分析历史对话，AI 判断是否要主动发起聊天\n"
            "3. 触发器队列：AI 通过函数工具管理触发器，可增删改查\n"
            "4. 睡眠时段：触发器不会在睡眠时段内触发\n"
            "5. 用户消息清空超时：用户发消息后，超时触发器会被清空\n\n"
            "可用命令：\n"
            "/li_help - 查看帮助\n"
            "/li_list - 列出所有触发器\n"
            "/li_status - 查看插件状态\n"
            "/li_clear - 清空所有触发器（管理员）\n\n"
            "注意：非闲聊性质的定时任务请使用 AstrBot 内置的 future_task 函数工具！"
        )
        yield event.plain_result(help_text)

    @filter.command("li_list")
    async def _cmd_list(self, event: AstrMessageEvent):
        """列出当前所有触发器"""
        umo = event.unified_msg_origin
        tlist = self._list_triggers_for_session(umo)
        if not tlist:
            yield event.plain_result("当前没有触发器。")
            return
        lines = [f"当前共有 {len(tlist)} 个触发器："]
        for i, t in enumerate(tlist, 1):
            fire_dt = datetime.fromtimestamp(t["fire_at_unix"])
            tz = self._get_tz()
            try:
                import zoneinfo
                if tz:
                    fire_str = fire_dt.astimezone(zoneinfo.ZoneInfo(tz)).strftime("%Y-%m-%d %H:%M:%S")
                else:
                    fire_str = fire_dt.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                fire_str = fire_dt.strftime("%Y-%m-%d %H:%M:%S")
            sid = t.get("session") or "当前"
            src_name = t.get("source", "unknown")
            extra_preview = (t.get("extra_prompt") or "无")[:40]
            lines.append(
                f"{i}. [{t['trigger_id']}] 触发={fire_str} | 会话={sid} | "
                f"来源={src_name} | agent={t.get('use_agent', True)} | 提示词={extra_preview}"
            )
        yield event.plain_result("\n".join(lines))

    @filter.command("li_clear")
    async def _cmd_clear(self, event: AstrMessageEvent):
        """清空所有触发器（需管理员）"""
        if event.role != "admin":
            yield event.plain_result("❌ 只有管理员可以使用此命令。")
            return
        count = len(self._triggers)
        self._triggers.clear()
        self._save_triggers()
        yield event.plain_result(f"✅ 已清空 {count} 个触发器。")

    @filter.command("li_status")
    async def _cmd_status(self, event: AstrMessageEvent):
        """查看插件状态"""
        umo = event.unified_msg_origin
        last_user = self._last_user_msg_unix.get(umo, 0)
        status = (
            "LiteInitiative 状态：\n"
            f"总触发器数：{len(self._triggers)}\n"
            f"本会话触发器数：{len(self._list_triggers_for_session(umo))}\n"
            f"最后用户消息：{datetime.fromtimestamp(last_user).strftime('%Y-%m-%d %H:%M:%S') if last_user else '无'}\n"
            f"睡眠时段：{self._get_sleep_hours()}\n"
            f"时区：{self._get_tz()}\n"
            f"最大触发器：{self._get_max_triggers()}\n"
            f"超时决策等待：{self._get_decision_timeout()}s\n"
            f"每日分析时间：{', '.join(f'{h}:{m:02d}' for h, m in self._get_daily_analysis_times())}\n"
            f"停用阈值：{self._get_inactive_threshold_hours()}h\n"
            f"Agent Pipeline：{'可用' if HAS_AGENT_PIPELINE else '不可用（降级模式）'}"
        )
        yield event.plain_result(status)
