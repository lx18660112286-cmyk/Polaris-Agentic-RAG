# Authentication & API Access

Mercury Commerce Platform 使用 JWT access token 认证。本文档适用于所有调用方（前端、服务端、脚本）。

## Access Token

- 通过 `POST /auth/token` 使用客户端凭证（client_id + client_secret）或用户名密码换取。
- `access_token` 有效期 **30 分钟**。
- 调用受保护接口时放在 `Authorization: Bearer <token>` 请求头。
- token 的 `scope` 字段决定可访问资源，例如 `order:read`、`order:write`。

## Token 过期与刷新

- access token 过期后必须使用 refresh token 换取新的 access token：
  `POST /auth/refresh` body 携带 `{"refresh_token": "..."}`。
- `refresh_token` 有效期 **7 天**。
- 每次刷新返回一组新的 access token + refresh token（刷新令牌轮换机制），旧 refresh token 立即失效。

## 401 与 403 的区别

| 场景 | 状态码 | 原因 |
|---|---|---|
| 请求头缺少 token | 401 | 未认证 |
| token 已过期 | 401 | 凭证过期 |
| token 签名无效 | 401 | 伪造或篡改 |
| token 有效但 scope 不足 | 403 | 权限不足 |
| token 有效但账号被禁用 | 403 | 账号状态异常 |

判断顺序：先判 401（凭证本身无效），再判 403（凭证有效但无权限）。调用方不应把 403 当作 401 去做刷新重试，刷新重试只会浪费一次刷新令牌周期。

## 常见故障

- `401 invalid_grant`：refresh token 已轮换或过期，需要用户重新登录。
- `403 insufficient_scope`：token scope 不包含所请求资源，需要重新签发更高权限的 token。