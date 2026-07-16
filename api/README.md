# API Service

FastAPI 后端服务，包含用户认证和 RBAC 权限控制。

## 核心能力

- JWT Access Token（默认 8 小时）
- Refresh Session（HttpOnly Cookie，默认 30 天，刷新轮换）
- RBAC（用户-角色-权限）
- 用户管理接口（需 `user.manage`）

## 本地开发

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r api/requirements.txt
python -m uvicorn api.app.main:app --reload --host 0.0.0.0 --port 8000
```

## 主要接口

- `GET /health`
- `GET /api/v1/ping`
- `POST /api/v1/auth/register`
- `POST /api/v1/auth/login`
- `POST /api/v1/auth/refresh`
- `POST /api/v1/auth/logout`
- `GET /api/v1/auth/me`
- `GET /api/v1/users`
