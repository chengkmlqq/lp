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
- `GET /api/v1/system/bootstrap`（公开，返回 `default_lang`）

## 系统语言（APP_LANGUAGE）

环境变量 `APP_LANGUAGE`（`zh` / `en`，默认 `zh`，别名 `zh-CN`/`cn`/`chinese`、`en-US`/`english`
自动归一化，非法值回落 `zh` 并打 warning）是**唯一的语言配置源**：

- 决定**后端产物**的默认语言：任务日志正文、故障判别 WS `step` 阶段文案、Word 报告；
- 决定**前端首次访问的默认界面语言**（`GET /api/v1/system/bootstrap` 下发，无需鉴权）；
- 进程启动时读取一次，运行期不再查库、不热更新 —— **修改后需重启 api 与 worker**，
  且两者必须配置为同一值，否则任务日志语言会与 api 不一致。

页面上的语言切换按钮仍然保留：用户手动选择写入 `localStorage`，后续访问以用户选择优先；
页面切换**不再**影响后端产物语言（原 `X-Lang` 自动附带已移除）。若某个调用方仍需要
按当次请求覆盖语言，显式传 `X-Lang` 依然有效，任务发布时会把发起者语言快照进
Celery 消息头，worker 优先使用任务级语言、缺省回落 `APP_LANGUAGE`。

历史遗留的系统参数 `app.language` 已废弃：启动时（`_auto_seed_baseline` 的同一把锁内）
幂等删除存量行，参数配置表中不再出现「系统语言」。

明确不翻译、原样保留：

- ATP/wine 引擎原始 stdout/stderr 与 `.lis/.log` 运行产物（外部进程输出）；
- traceback / 异常字符串中的中文；
- 历史日志（Redis Stream / MinIO 已落盘内容不回溯，仅新任务生效）。

未命中翻译词典的中文片段回落原文，不出现空洞。排障可点日志抽屉的
「下载原始日志」按钮，或调用 `GET /api/v1/admin/task-logs/{task_id}/raw`
下载逐字原文（英文任务在 `logs/{task_id}.raw.log` 另存一份）。
