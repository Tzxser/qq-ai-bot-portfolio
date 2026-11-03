# V2.3 验收记录

## 已完成的离线实现

- 三方基线重新核对为 `98204d7`，没有回退。
- 数学 plain formatter 与代码/URL 保护。
- Provider 独立结果对象，保留 `usage`、`attempts`、`finish_reason`，可识别长度截断。
- PostgreSQL schema v4：`inbox_tasks`、`outbox_tasks`；接收先落库，生成后先保存答案。
- Bot 重启后等待已验证 OneBot 连接，再恢复本地 `source=live` 任务；恢复路径不会运行历史补取。
- `RECOVERY_HISTORY_ENABLED=false` 保持默认关闭。

## 测试

本地测试使用 mock 和静态/数据库夹具；服务器部署与真实 QQ 验收尚未完成。公式图片真实截图、QQ 离线历史完整性、断电场景和 24 小时观察均未验证，不能写成已通过。

当前服务器 QQ 状态曾回到 `waiting_qrcode`，因此在重新扫码前不进行真实消息验收，也不把 Bot/数据库健康当作 QQ 在线。
