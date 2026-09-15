# Deployment & Rollback

本文档描述 Mercury Commerce Platform 各服务的部署流程与回滚策略。

## 部署方式

Order Service (`mercury-order`) 采用 **blue-green 部署**：

1. 构建镜像并打 tag：`registry.example.com/mercury-order:<version>`。
2. 部署新版本到 green 环境（当前生产为 blue）。
3. 运行健康检查 `GET /healthz` 通过后，将 Gateway 流量从 blue 切到 green。
4. 观察 30 分钟，确认无误后回收 blue。

其他服务（`mercury-gateway`、`mercury-auth`）使用滚动部署，一次替换 20% 实例。

## 环境变量

| 变量 | 说明 |
|---|---|
| `ORDER_DB_DSN` | mercury-db 连接串，格式 `postgres://user:pass@mercury-db:5432/orders` |
| `ORDER_REDIS_DSN` | mercury-cache 连接串 |
| `ORDER_QUEUE_DSN` | mercury-queue 连接串（RabbitMQ amqp 协议） |
| `JWT_ISSUER` | token 签发者，固定为 `mercury-auth` |
| `JWT_PUBLIC_KEY_PATH` | 公钥文件路径，Auth Service 校验 token 使用 |

部署前必须核对：`ORDER_DB_DSN` 指向目标环境的 mercury-db，`JWT_ISSUER` 与环境一致。

## 回滚步骤

以 Order Service 为例，回滚到上一版本 `order-v2.4.0`（当前 green 是 `order-v2.4.1`）：

1. 停止向 green 切流，保留当前 green 实例。
2. 将上一版本镜像 tag 从 `order-v2.4.0` 重新部署到 blue 环境。
3. 健康检查通过后，把 Gateway 流量切回 blue。
4. 观察 30 分钟，确认错误率回落后，下线 green。

## 发布检查清单

- [ ] 数据库 migration 已执行且可回滚（`mercury-db` 只做向前兼容变更）
- [ ] 环境变量已按目标环境核对
- [ ] 新版本镜像健康检查 `/healthz` 通过
- [ ] 灰度切流前备份上一版本镜像 tag
- [ ] 回滚演练：确认 `order-v2.4.0` tag 仍然存在且可拉起