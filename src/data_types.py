"""
LiteInitiative - 数据结构定义
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class Trigger:
    """触发器数据模型"""
    trigger_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    fire_at_unix: float = 0.0
    session: str = ""
    extra_prompt: str = ""
    direct_send: bool = True
    created_at: float = field(default_factory=time.time)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "trigger_id": self.trigger_id,
            "fire_at_unix": self.fire_at_unix,
            "session": self.session,
            "extra_prompt": self.extra_prompt,
            "direct_send": self.direct_send,
            "created_at": self.created_at,
            "extra": self.extra,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Trigger:
        t = cls()
        for k, v in data.items():
            if hasattr(t, k):
                setattr(t, k, v)
                
        # 兼容旧数据：若没有 direct_send 字段，设置默认 False
        if not hasattr(t, "direct_send") or t.direct_send is None:
            t.direct_send = False

        # 兼容旧数据：丢弃 source 字段
        return t


@dataclass
class SessionState:
    """会话状态（单一职责：管理单个会话的所有运行时状态）"""
    last_ai_reply_unix: float = 0.0
    last_user_msg_unix: float = 0.0
    timeout_task: Optional[Any] = None      # asyncio.Task
    decision_in_progress: bool = False       # 防重入标志

    def to_dict(self) -> dict:
        return {
            "last_ai_reply_unix": self.last_ai_reply_unix,
            "last_user_msg_unix": self.last_user_msg_unix,
        }

    @classmethod
    def from_dict(cls, data: dict) -> SessionState:
        return cls(
            last_ai_reply_unix=data.get("last_ai_reply_unix", 0.0),
            last_user_msg_unix=data.get("last_user_msg_unix", 0.0),
        )
