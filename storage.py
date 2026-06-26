#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LiteInitiative - 持久化存储模块
"""

from __future__ import annotations

import json
import os
from typing import Dict, Optional

from astrbot.api import logger
from types import Trigger, SessionState


class Storage:
    """JSON 文件持久化存储"""
    
    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        self.trigger_file = os.path.join(data_dir, "triggers.json")
        self.state_file = os.path.join(data_dir, "session_states.json")
    
    def save_triggers(self, triggers: Dict[str, Trigger]):
        try:
            data = {tid: t.to_dict() for tid, t in triggers.items()}
            with open(self.trigger_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"[LiteInitiative] 保存触发器失败: {e}")
    
    def load_triggers(self) -> Dict[str, Trigger]:
        if not os.path.exists(self.trigger_file):
            return {}
        try:
            with open(self.trigger_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            result = {k: Trigger.from_dict(v) for k, v in data.items()}
            logger.info(f"[LiteInitiative] 加载了 {len(result)} 个触发器")
            return result
        except Exception as e:
            logger.error(f"[LiteInitiative] 加载触发器失败: {e}")
            return {}
    
    def save_states(self, sessions: Dict[str, SessionState], last_user_msg: Dict[str, float]):
        try:
            data = {sid: s.to_dict() for sid, s in sessions.items()}
            data["last_user_msg_unix"] = last_user_msg
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"[LiteInitiative] 保存状态失败: {e}")
    
    def load_states(self) -> tuple[Dict[str, SessionState], Dict[str, float]]:
        if not os.path.exists(self.state_file):
            return {}, {}
        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            sessions = {}
            last_user_msg = {}
            for k, v in data.items():
                if k == "last_user_msg_unix":
                    last_user_msg = v if isinstance(v, dict) else {}
                else:
                    sessions[k] = SessionState.from_dict(v)
            logger.info(f"[LiteInitiative] 加载了 {len(sessions)} 个会话状态")
            return sessions, last_user_msg
        except Exception as e:
            logger.error(f"[LiteInitiative] 加载状态失败: {e}")
            return {}, {}
