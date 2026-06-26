#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LiteInitiative - AI 驱动的智能主动闲聊插件
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import Any, Dict, Optional

from astrbot.api import logger
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register

from .time_utils import _get_now_tz, _format_time_delta
from .data_types import Trigger, SessionState
from .config import ConfigReader
from .storage import Storage
from .tools import LLMFunctions
from .decision import run_ai_decision, run_trigger, save_proactive_history


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
        self._config = ConfigReader(config)
        self._lock = asyncio.Lock()
        self._triggers: Dict[str, Trigger] = {}
        self._sessions: Dict[str, SessionState] = {}
        self._last_user_msg: Dict[str, float] = {}
        self._scheduler_task: Optional[asyncio.Task] = None
        self._firing_ids: set = set()
        self._stopped: bool = False
        self._last_daily_minute: str = ""

        # 初始化存储
        self._storage = self._init_storage()
        self._load_all()

        # 注册 LLM 工具
        self._llm_funcs = LLMFunctions(self)
        try:
            # 激活工具
            for tool_name in ["list_triggers", "create_trigger", "delete_trigger", "update_trigger"]:
                self.context.activate_llm_tool(tool_name)
            
            # 手动设置 handler_module_path（AstrBot 的 spec_to_func 没有自动设置）
            llm_tools = self.context.provider_manager.llm_tools
            for func_tool in llm_tools.func_list:
                if func_tool.name in ["list_triggers", "create_trigger", "delete_trigger", "update_trigger"]:
                    func_tool.handler_module_path = self.__class__.__module__
            
            logger.info("[LiteInitiative] LLM 工具注册成功")
        except Exception as e:
            logger.warning(f"[LiteInitiative] LLM 工具注册失败: {e}")

    def _init_storage(self) -> Storage:
        try:
            from astrbot.api.star import StarTools
            base = StarTools.get_data_dir() / "astrbot_plugin_lite_initiative"
        except Exception:
            import os
            base = os.path.join(os.getcwd(), "data", "plugin_data", "astrbot_plugin_lite_initiative")
        return Storage(str(base))

    def _load_all(self):
        self._triggers = self._storage.load_triggers()
        self._sessions, self._last_user_msg = self._storage.load_states()

        # 启动时按会话分别修剪
        self._enforce_max_triggers()

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
        for s in self._sessions.values():
            if s.timeout_task:
                s.timeout_task.cancel()
        self._storage.save_triggers(self._triggers)
        self._storage.save_states(self._sessions, self._last_user_msg)
        logger.info("[LiteInitiative] 插件已停用")

    # ─────────────────────── 触发器管理 ───────────────────────

    def _enforce_max_triggers(self):
        """按每个会话分别限制触发器数量，超出时删除最早创建的。"""
        max_n = self._config.get_max_triggers()
        
        # 按 session 分组
        sessions = {}
        for t in self._triggers.values():
            sessions.setdefault(t.session, []).append(t)
        
        to_delete = []
        for session, triggers in sessions.items():
            if len(triggers) <= max_n:
                continue
            # 按创建时间排序，保留最新的 max_n 个
            sorted_t = sorted(triggers, key=lambda t: t.created_at)
            for t in sorted_t[:len(triggers) - max_n]:
                to_delete.append(t.trigger_id)
        
        for tid in to_delete:
            del self._triggers[tid]
    
        if to_delete:
            self._storage.save_triggers(self._triggers)

    def _get_or_create_session(self, umo: str) -> SessionState:
        if umo not in self._sessions:
            self._sessions[umo] = SessionState()
        return self._sessions[umo]

    # ─────────────────────── 消息事件 ───────────────────────

    @filter.on_llm_response()
    async def _on_llm_response(self, event: AstrMessageEvent, _response=None):
        """AI 回复后启动超时计时"""
        if event.get_extra("lite_initiative_proactive"):
            return
        umo = event.unified_msg_origin
        if not self._is_user_whitelisted(umo):
            return
        
        async with self._lock:
            s = self._get_or_create_session(umo)
            s.last_ai_reply_unix = time.time()
            if s.timeout_task:
                s.timeout_task.cancel()
                s.timeout_task = None
            timeout_sec = self._config.get_decision_timeout()
            s.timeout_task = asyncio.create_task(self._timeout_decision(umo, timeout_sec))
            logger.debug(f"[LiteInitiative] 超时计时启动: {umo}, {timeout_sec}s")

    @filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE)
    async def _on_user_message(self, event: AstrMessageEvent):
        """用户发消息：更新活跃时间，清空本会话所有触发器"""

        umo = event.unified_msg_origin

        # 白名单检查
        if not self._is_user_whitelisted(umo):
            return
        
        async with self._lock:
            self._last_user_msg[umo] = time.time()
            s = self._get_or_create_session(umo)
            s.last_user_msg_unix = time.time()

            # 取消超时计时
            if s.timeout_task:
                s.timeout_task.cancel()
                s.timeout_task = None
                logger.debug(f"[LiteInitiative] 用户发消息，取消超时: {umo}")

            # 如果正在决策中，标记取消
            if s.decision_in_progress:
                s.decision_in_progress = False
                logger.debug(f"[LiteInitiative] 用户发消息，中断决策: {umo}")

            # 清空本会话所有触发器
            to_remove = [tid for tid, t in self._triggers.items() if t.session == umo]
            for tid in to_remove:
                del self._triggers[tid]
                logger.debug(f"[LiteInitiative] 清空触发器: {tid}")

            if to_remove:
                self._storage.save_triggers(self._triggers)

    # ─────────────────────── 超时决策 ───────────────────────

    async def _timeout_decision(self, umo: str, timeout_sec: int):
        if not self._is_user_whitelisted(umo):
            return
        
        try:
            await asyncio.sleep(timeout_sec)
        except asyncio.CancelledError:
            return

        async with self._lock:
            s = self._sessions.get(umo)
            if not s:
                return
            # 检查用户是否在超时期间发过消息
            if s.last_user_msg_unix > s.last_ai_reply_unix:
                return
            # 防重入
            if s.decision_in_progress:
                return
            s.decision_in_progress = True

        now_ts = time.time()
        last_active = max(s.last_user_msg_unix or 0, s.last_ai_reply_unix or 0)
        silence_sec = now_ts - last_active
        logger.info(f"[LiteInitiative] 超时决策触发: {umo}, 沉默 {_format_time_delta(silence_sec)}")

        try:
            trigger_list = self._list_for_session(umo)
            await run_ai_decision(
                context=self.context,
                config_reader=self._config,
                umo=umo,
                trigger_list=trigger_list,
                silence_sec=silence_sec,
                decision_prompt=self._config.get_decision_prompt(),
                max_history=self._config.get_decision_max_history(),
            )
        except Exception as e:
            logger.error(f"[LiteInitiative] 超时决策异常({umo}): {e}", exc_info=True)
        finally:
            async with self._lock:
                if umo in self._sessions:
                    self._sessions[umo].decision_in_progress = False

    # ─────────────────────── 每日分析 ───────────────────────

    async def _daily_analysis_check(self):
        now = _get_now_tz(self._config.get_tz())
        times = self._config.get_daily_analysis_times()
        if not times or (now.hour, now.minute) not in times:
            return

        minute_key = now.strftime("%Y%m%d%H%M")
        if self._last_daily_minute == minute_key:
            return
        self._last_daily_minute = minute_key

        now_ts = time.time()
        inactive_h = self._config.get_inactive_threshold_hours()
        targets = [
            umo for umo, last in self._last_user_msg.items()
            if inactive_h <= 0 or (now_ts - last) < inactive_h * 3600
        ]
        # 过滤白名单
        targets = [umo for umo in targets if self._is_user_whitelisted(umo)]
        if not targets:
            return

        logger.info(f"[LiteInitiative] 每日分析: {len(targets)} 个会话")
        for umo in targets:
            try:
                trigger_list = self._list_for_session(umo)
                await run_ai_decision(
                    context=self.context,
                    config_reader=self._config,
                    umo=umo,
                    trigger_list=trigger_list,
                    silence_sec=now_ts - self._last_user_msg.get(umo, now_ts),
                    decision_prompt=self._config.get_daily_analysis_prompt(),
                    max_history=self._config.get_daily_analysis_max_history(),
                )
            except Exception as e:
                logger.error(f"[LiteInitiative] 每日分析失败({umo}): {e}")

    def _list_for_session(self, session: str = "") -> list:
        tlist = []
        for t in self._triggers.values():
            if not session or t.session == session:
                tlist.append(t.to_dict())
        tlist.sort(key=lambda x: x.get("fire_at_unix", 0))
        return tlist

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

        async with self._lock:
            for t in list(self._triggers.values()):
                if now_ts >= t.fire_at_unix and t.trigger_id not in self._firing_ids:
                    logger.info(f"[LiteInitiative] 触发器到期: {t.trigger_id}")
                    asyncio.create_task(self._execute_trigger(t))

            # 清理过期超过 24h 的触发器
            expired = [tid for tid, t in self._triggers.items() if t.fire_at_unix < now_ts - 86400]
            for tid in expired:
                del self._triggers[tid]
            if expired:
                self._storage.save_triggers(self._triggers)

    async def _execute_trigger(self, trigger: Trigger):
        if trigger.trigger_id in self._firing_ids:
            return
        self._firing_ids.add(trigger.trigger_id)
        try:
            umo = trigger.session or ""
            if not self._is_user_whitelisted(umo):

                # 非白名单用户，直接删除触发器并返回
                async with self._lock:
                    if trigger.trigger_id in self._triggers:
                        del self._triggers[trigger.trigger_id]
                        self._storage.save_triggers(self._triggers)
                return
            response_text, sent = await run_trigger(self.context, self._config, trigger)
            if sent and response_text:
                await save_proactive_history(self.context, umo, response_text)
                logger.info(f"[LiteInitiative] 触发器回复已发送: {trigger.trigger_id}")
        except Exception as e:
            logger.error(f"[LiteInitiative] 触发器执行失败({trigger.trigger_id}): {e}", exc_info=True)
        finally:
            self._firing_ids.discard(trigger.trigger_id)
            async with self._lock:
                if trigger.trigger_id in self._triggers:
                    del self._triggers[trigger.trigger_id]
                    self._storage.save_triggers(self._triggers)

    # ─────────────────────── 用户指令 ───────────────────────

    @filter.command("li_help")
    async def _cmd_help(self, event: AstrMessageEvent):
        """查看 LiteInitiative 插件帮助"""
        yield event.plain_result(
            "LiteInitiative 插件使用指南：\n\n"
            "核心功能：\n"
            "• 超时决策：AI 回复后等待，用户不回复则 AI 判断是否主动聊天\n"
            "• 每日分析：定时分析历史对话，决定是否主动发起\n"
            "• 触发器队列：AI 用函数工具增删改查\n"
            "• 睡眠保护：触发器不会在睡眠时段触发\n"
            "• 用户消息清空：用户发消息会清空所有触发器\n\n"
            "命令：/li_help /li_list /li_status /li_clear\n\n"
            "注意：非闲聊的定时任务请用平台的 future_task 工具！"
        )

    @filter.command("li_list")
    async def _cmd_list(self, event: AstrMessageEvent):
        """列出当前所有触发器"""
        tlist = self._list_for_session(event.unified_msg_origin)
        if not tlist:
            yield event.plain_result("当前没有触发器。")
            return
        tz = self._config.get_tz()
        lines = [f"当前共有 {len(tlist)} 个触发器："]
        for i, t in enumerate(tlist, 1):
            fire_dt = datetime.fromtimestamp(t["fire_at_unix"])
            try:
                import zoneinfo
                fire_str = fire_dt.astimezone(zoneinfo.ZoneInfo(tz)).strftime("%Y-%m-%d %H:%M:%S") if tz else fire_dt.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                fire_str = fire_dt.strftime("%Y-%m-%d %H:%M:%S")
            extra_preview = (t.get("extra_prompt") or "无")[:40]
            lines.append(f"{i}. [{t['trigger_id']}] 触发={fire_str} | agent={t.get('use_agent', True)} | {extra_preview}")
        yield event.plain_result("\n".join(lines))

    @filter.command("li_clear")
    async def _cmd_clear(self, event: AstrMessageEvent):
        """清空所有触发器（需管理员）"""
        if event.role != "admin":
            yield event.plain_result("❌ 只有管理员可以使用此命令。")
            return
        async with self._lock:
            count = len(self._triggers)
            self._triggers.clear()
            self._storage.save_triggers(self._triggers)
        yield event.plain_result(f"✅ 已清空 {count} 个触发器。")

    @filter.command("li_status")
    async def _cmd_status(self, event: AstrMessageEvent):
        """查看插件状态"""
        umo = event.unified_msg_origin
        last_user = self._last_user_msg.get(umo, 0)
        yield event.plain_result(
            f"LiteInitiative 状态：\n"
            f"总触发器：{len(self._triggers)}\n"
            f"本会话触发器：{len(self._list_for_session(umo))}\n"
            f"最后用户消息：{datetime.fromtimestamp(last_user).strftime('%Y-%m-%d %H:%M:%S') if last_user else '无'}\n"
            f"睡眠时段：{self._config.get_sleep_hours()}\n"
            f"时区：{self._config.get_tz()}\n"
            f"最大触发器：{self._config.get_max_triggers()}\n"
            f"超时等待：{self._config.get_decision_timeout()}s\n"
            f"每日分析：{', '.join(f'{h}:{m:02d}' for h, m in self._config.get_daily_analysis_times())}\n"
        )

    def _is_user_whitelisted(self, umo: str) -> bool:
        """检查 unified_msg_origin 是否在白名单内"""
        whitelist = self._config.get_whitelist()
        if not whitelist:
            return True
        try:
            # unified_msg_origin 格式: platform_id:message_type:session_id
            parts = umo.split(":", 2)
            if len(parts) == 3:
                user_id = parts[2]  # 对于私聊，即 QQ 号
                return user_id in whitelist
        except Exception:
            pass
        return False