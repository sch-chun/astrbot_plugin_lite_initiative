# Changelog

All notable changes to this project will be documented in this file.

## [0.2.3] - 2026-07-01

### Added

- 增加概率筛选功能

## [0.2.2] - 2026-06-28

## Fixed

- 修复 /li_list 的错误字段
- 修复错误地同步调用 get_provider_by_id 导致提供商配置无法生效的问题

## Changed

- 模块文件全部移至 src 下
- 删除沉默时间提醒，避免 AI 过于谨慎

## [0.2.1] - 2026-06-28

### Fixed

- **UpdateTriggerTool 字段名错误**：`update_trigger` 工具参数和代码中使用了已废弃的 `use_agent` 字段名，应为 `direct_send`，导致更新触发器时抛出 `AttributeError`
- **tool_schema_mode 未强制设置**：`build_agent_config` 从 `provider_settings` 读取 `tool_schema_mode`，某些 provider 可能默认 `skills_like` 模式，导致工具调用失败。现在强制设为 `"full"`
- **save_proactive_history 静默失败**：尝试访问 `conversation.messages` 但 `Conversation` 数据类无此属性（应为 `conversation.history`，JSON 字符串）。现在使用纯 dict 格式并正确调用 `conv_mgr.update_conversation()`
- **get_suggest_direct_send() 读取错误键**：`ConfigReader.get_suggest_direct_send()` 误读 `suggest_direct_send_prompt` 键，实际应为 `suggest_direct_send`
- **run_trigger 逻辑反转**：`direct_send=True` 时错误调用 Agent 模式，`direct_send=False` 时错误走纯文本。现已修正为 `True` 走纯文本，`False` 走 Agent

### Changed

- **decision.py**：移除不再使用的 `UserMessageSegment`、`AssistantMessageSegment`、`TextPart`、`Plain` 导入
- **save_proactive_history**：改用纯 dict 格式（与 DB 存储格式一致），正确处理空历史字符串

### Documentation

- README 移除已删除的配置项 `decision_max_history_messages` 和 `daily_analysis_max_history_messages`
- README 新增 `decision_provider`、`min_trigger_delay`、`suggest_direct_send`、`suggest_direct_send_prompt` 配置说明
- README 修正"用户消息清空所有触发器"为"清空即将触发的触发器"

## [0.2.0] - 2026-06-28

### Added

- **决策专用模型提供商**：新增配置项 `decision_provider`，可为超时决策和每日分析指定独立的 LLM 提供商，留空则使用主代理默认模型
- **最小触发器延迟**：新增 `min_trigger_delay` 配置，强制 AI 在短时间主动时使用 `send_message_to_user` 直接发送，避免额外 LLM 调用（对昂贵模型尤其有用）
- **短延迟直接发送建议**：新增 `suggest_direct_send` 和 `suggest_direct_send_prompt` 配置，决策时提示 AI 在需短时间内发送主动消息时直接发送，减少触发器创建
- **调试命令**：新增 `/li_debug_timeout` 和 `/li_debug_daily`，便于手动触发决策进行测试

### Changed

- **决策流程重构**：
  - 统一 `_perform_decision` 核心方法，超时决策和每日分析共用同一逻辑，消除代码重复
  - 决策时不再手动获取历史消息，依赖 AstrBot 上下文自动传递，减少耦合
  - 支持决策专用 provider，自动降级至默认模型
- **触发器字段重命名**：`use_agent` 改为 `direct_send`，语义更明确（`True`=直接发送原文，`False`=走 Agent 能力生成内容）
- **用户消息清空策略优化**：用户发送新消息时，仅清空本会话中**即将触发**（在超时窗口内）的触发器，而非全部清空，避免误删远期触发器
- **工具注册方式升级**：从 `@llm_tool` 函数装饰器迁移至 `FunctionTool` 类方式，符合 AstrBot 4.x 新规范，工具内部直接持有插件实例，提升类型安全性和可维护性
- **存储健壮性**：加载会话状态时过滤无效的 `unified_msg_origin`，避免脏数据污染

### Removed

- 移除 `decision_max_history_messages` 和 `daily_analysis_max_history_messages` 配置（历史消息由 AstrBot 上下文管理，无需插件单独控制）

### Fixed

- 修复决策过程中可能因无效 UMO 导致的崩溃
- 修复旧版本触发器数据中缺少 `direct_send` 字段时的兼容性问题（自动设为 `False`）
- 修复每日分析时未正确检查用户不活跃阈值的问题

## [0.1.0] - 2026-06-26

### Added

- 初始版本发布
- 超时决策机制：AI 回复后等待用户，超时后由 AI 判断是否主动发起闲聊
- 每日定时分析：在配置的时间点分析历史对话，自动创建触发器
- 触发器队列管理：AI 通过 `create_trigger`、`delete_trigger`、`update_trigger`、`list_triggers` 四个工具自主管理触发器
- 按会话分别限制触发器数量（`max_triggers`）
- 睡眠时段保护：触发器不会在配置的睡眠时段内触发
- 用户消息清空触发器：用户发送新消息时自动清空当前会话所有触发器并取消超时计时
- 持久化存储：支持触发器队列和会话状态的 JSON 持久化
- 白名单机制：可配置仅允许指定用户使用插件功能

### Changed

- **配置系统重构**：遵循 AstrBot 官方配置规范，将 `_conf_schema.json` 改为扁平结构，移除无效的外层包装和分组标记
- **触发器上限策略**：从"静默丢弃最早触发器"改为"拒绝创建并返回完整列表"，增强 AI 可感知性
- **触发器作用域**：从全局限制改为按会话分别限制，避免不同会话相互影响
- **导入优化**：将 `types.py` 重命名为 `data_types.py`，避免与 Python 标准库冲突
- **类型安全**：移除条件导入，直接依赖 AstrBot 核心类，消除 Pylance 类型警告
- **工具说明**：完善所有 LLM 工具的 docstring，明确区分临时触发器与持久任务 (`future_task`)

### Fixed

- 修复 `_conf_schema.json` 未遵循 AstrBot 配置接口的问题
- 修复 `from types import` 导入标准库而非本地模块的问题
- 修复 `@filter.on_message` 装饰器未被 Pylance 识别的问题
- 修复 `build_agent_config` 返回类型不明确导致的参数类型错误
- 修复 `MessageSession.send` 等条件导入导致的类型检查警告

### Removed

- 移除 `_conf_schema.json` 中非标准的 `schema` 和 `ui` 外层包装
- 移除 `config.py` 中不必要的递归 `_get` 方法
- 移除 `decision.py` 中的条件导入（`try...except ImportError`）逻辑