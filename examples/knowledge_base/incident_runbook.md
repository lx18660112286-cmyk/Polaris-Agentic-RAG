# Incident Runbook — 线上事故排查

本文档是生产事故的处理流程，围绕 Mercury Commerce Platform。

## 常见症状与关键字

| 症状 | 日志关键字 | 初步判断 |
|---|---|---|
| Order Service 5xx 突增 | `ORDER_SAVE_FAILED` | 写库异常 |
| 订单查询超时 | `ORDER_QUERY_TIMEOUT` | 缓存/数据库故障 |
| 数据库连接耗尽 | `DB_CONNECTION_POOL_EXHAUSTED` | 连接池打满 |
| 队列堆积 | `ORDER_CREATED_PUBLISH_FAILED` | 发布消息失败 |
| 认证大面积 401 | `TOKEN_VALIDATION_FAILED` | Auth Service 或公钥异常 |

## trace_id 约定

- 每个请求由 API Gateway 分配 `trace_id`（格式 `mercury-<8位hex>`），写入响应头 `X-Trace-Id`。
- 所有服务日志必须包含 `trace_id` 字段。
- 排查时先取 `trace_id`，再按 request 维度检索所有服务日志，不要直接全量 grep。

## 排查第一步

1. 确认受影响的异常指标：5xx 错误率、P95 延迟、队列积压。
2. 用 `trace_id` 定位具体请求链路，判断故障发生在哪一跳。
3. 对照上表关键字缩小范围。

## 回滚决策

满足以下任一条件，直接回滚 Order Service（回滚步骤见 deployment.md，回滚到 `order-v2.4.0`）：

- 5xx 错误率超过 5% 且持续 10 分钟以上。
- `DB_CONNECTION_POOL_EXHAUSTED` 在 5 分钟内出现超过 3 次。
- 订单创建成功率低于 95% 且与本次发布相关。

回滚不是唯一手段。若根因明确是慢 SQL 或缓存抖动，可以先修复再继续观察，但必须在 30 分钟内给出决策，且 `trace_id` 证据必须随事故记录留存。

## 恢复后动作

- 确认错误率回落、队列恢复正常消费。
- 保留事故期间的 `trace_id` 样本与日志片段供事后复盘。
- 更新本文档中的关键字表（如果出现了未收录的模式）。