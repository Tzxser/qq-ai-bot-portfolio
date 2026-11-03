# QQ AI Bot 对话机器人

基于 Python、OneBot v11、WebSocket、PostgreSQL 与 Redis 的对话机器人。代码将消息接入、会话管理、模型调用、群路由、限流与持久化拆分为独立模块。

## 主要功能

- 私聊对话与历史上下文管理，支持可配置的大模型服务。
- 群聊允许名单、明确触发条件、消息去重与配额控制。
- PostgreSQL inbox/outbox 状态，支持本地已接收任务的恢复流程。
- 知识条目审核、检索、文本排版与错误提示。
- 容器化部署配置、健康检查、备份与自动化测试。

## 建议阅读

- 接入与路由：`bot/gateway/`、`bot/group/router.py`。
- 会话与模型：`bot/conversation/service.py`、`bot/llm/`。
- 持久化：`bot/persistence/postgres.py`。
- 安全与配额：`bot/security/`、`bot/group/quota.py`。
- 回归场景：`tests/`。

## 验证与范围

原项目曾完成私聊闭环与群功能的真实验收。V2.3 的格式化与任务恢复属于后续增量，文档明确其本地测试使用 mock 和数据库夹具，真实服务器恢复验收尚未完成。历史状态不代表机器人当前在线。

此展示副本没有真实 QQ 账号、群号、联系人、会话记录、服务密钥或服务器配置。`.env.example` 只提供空值和配置示例；知识种子为通用展示内容。使用真实账号与外部模型服务时须自行配置并取得相应授权。

## 本地开发

依赖定义见 `pyproject.toml`，容器依赖见 `docker-compose.test.yml`。可以从离线协议和路由测试开始阅读；连接真实服务需要另外配置。`docs/V23_ACCEPTANCE.md` 保留未完成范围说明。
