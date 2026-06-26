# Changelog

All notable changes to this project will be documented in this file.

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
- **触发器上限策略**：从“静默丢弃最早触发器”改为“拒绝创建并返回完整列表”，增强 AI 可感知性
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