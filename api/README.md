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

## 后端产物语言（app.language）

系统参数 `app.language`（`zh` / `en`，默认 `zh`，仅 `status=enabled` 生效，非法值回落 `zh`）
决定**后端产物**的默认语言：任务日志正文、故障判别 WS `step` 阶段文案、Word 报告。
在「系统参数」页修改后，新任务生效；运行中的任务语言在启动时已快照，不会中途变化。

前端 `fetchWithAuth` 统一携带 `X-Lang`（读 localStorage 的 `lp.lang`），任务发布时把
发起者语言快照进 Celery 消息头，worker 优先使用任务级语言、缺省回落 `app.language`。
因此英文界面用户创建的任务日志为英文，中文界面用户仍为中文。

明确不翻译、原样保留：

- ATP/wine 引擎原始 stdout/stderr 与 `.lis/.log` 运行产物（外部进程输出）；
- traceback / 异常字符串中的中文；
- 历史日志（Redis Stream / MinIO 已落盘内容不回溯，仅新任务生效）。

未命中翻译词典的中文片段回落原文，不出现空洞。排障可点日志抽屉的
「下载原始日志」按钮，或调用 `GET /api/v1/admin/task-logs/{task_id}/raw`
下载逐字原文（英文任务在 `logs/{task_id}.raw.log` 另存一份）。
