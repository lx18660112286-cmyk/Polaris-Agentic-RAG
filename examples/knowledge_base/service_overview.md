# Service Overview

Mercury Commerce Platform 是统一的虚拟电商系统，本文档是平台的组件级总览。

## 组件清单

| 组件 | 名称 | 职责 |
|---|---|---|
| API Gateway | `mercury-gateway` | 统一入口，负责路由、限流、身份校验分发 |
| Auth Service | `mercury-auth` | 签发/校验 access token 与 refresh token |
| Order Service | `mercury-order` | 订单创建、查询、状态流转、回滚 |
| Database | `mercury-db` | PostgreSQL 16，订单数据主存储 |
| Cache | `mercury-cache` | Redis 7，缓存订单查询结果 |
| Queue | `mercury-queue` | RabbitMQ，`order.created` 事件消息总线 |

## API Gateway

- 所有外部请求先经过 Gateway，再路由到下游服务。
- Gateway 不在业务层做鉴权，只校验 token 是否过期并透传 `X-Trace-Id`。
- critical path 上只做 2 次下游转发，超时阈值 5 秒。

## Auth Service

- 签发 JWT access token，默认有效期 30 分钟。
- 签发 refresh token，默认有效期 7 天，支持轮换。
- 校验时只依赖 `<ISSUER>` 与公钥文件，不落库查询。

## Order Service

- 提供订单创建 `/orders`、订单详情 `/orders/{id}`、订单取消 `/orders/{id}/cancel`。
- 写库走 `mercury-db.orders` 表，读缓存 Key 为 `order:{id}`。
- 创建订单成功后发送 `order.created` 事件到 `mercury-queue`。

## Database / Cache / Queue

- `mercury-db`：`orders` 表含 `id`、`user_id`、`amount`、`status`、`created_at`。
- `mercury-cache`：订单详情缓存 TTL 300 秒。
- `mercury-queue`：`order.created` 消息由下游库存服务消费（库存服务不在这套知识库内）。

## 与其他文档的关系

- 部署与回滚步骤见 `deployment.md`。
- token 鉴权细节见 `api_auth.md`。
- 线上事故排查与 `trace_id` 用法见 `incident_runbook.md`。