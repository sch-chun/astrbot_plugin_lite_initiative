#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LiteInitiative - 数据模型模块
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class Trigger:
    """触发器数据模型"""
    trigger_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    fire_at_unix: float = 0.0
    session: str = ""
    extra_prompt: str = ""
    use_agent: bool = True
    source: str = "unknown"
    created_at: float = field(default_factory=time.time)
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "trigger_id": self.trigger_id,
            "fire_at_unix": self.fire_at_unix,
            "session": self.session,
            "extra_prompt": self.extra_prompt,
            "use_agent": self.use_agent,
            "source": self.source,
            "created_at": self.created_at,
            "extra": self.extra,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Trigger:
        t = cls()
        for k, v in data.items():
            if hasattr(t, k):
                setattr(t, k, v)
        return t


@dataclass
class SessionRuntime:
    """会话运行时状态"""
    last_ai_reply_unix: float = 0.0
    timeout_fire_task: Optional[Any] = None
    last_user_msg_unix: float = 0.0

    def to_dict(self) -> dict:
        return {
            "last_ai_reply_unix": self.last_ai_reply_unix,
            "last_user_msg_unix": self.last_user_msg_unix,
        }

    @classmethod
    def from_dict(cls, data: dict) -> SessionRuntime:
        return cls(
            last_ai_reply_unix=data.get("last_ai_reply_unix", 0.0),
            last_user_msg_unix=data.get("last_user_msg_unix", 0.0),
        )
