# lp

基于 Next.js + Python（FastAPI）的全栈 Monorepo，内置用户管理与登录认证。

## 目录结构

```text
.
├── web/                 # Next.js 16 + TypeScript + App Router（登录态与用户管理页）
├── api/                 # FastAPI 服务（JWT + Refresh Session + RBAC）
├── scripts/dev.sh       # 前后端一键并行启动脚本
├── .env.example         # 根环境变量模板
└── package.json         # Monorepo 根脚本
```

## 技术栈

- 前端：Next.js 16、React 19、TypeScript
- 后端：FastAPI、SQLAlchemy、PostgreSQL/SQLite、Pydantic Settings
- 认证：JWT Access Token（15m）+ Refresh Session（HttpOnly Cookie, 轮换）
- 权限：RBAC（roles / permissions / user_roles / role_permissions）

## 环境要求

- Node.js >= 20
- Python >= 3.10
- Python 需要可用的 `venv` 和 `pip`（Debian/Ubuntu 可安装 `python3-venv`）

## 快速开始

1. 克隆仓库并进入目录。
2. 安装前端依赖：

   ```bash
   npm --prefix web install
   ```

3. 配置环境变量：

   ```bash
   cp .env.example .env
   cp web/.env.local.example web/.env.local
   ```

4. 准备 Python 环境并安装依赖（示例）：

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   python -m pip install -r api/requirements.txt
   ```

5. 一键启动前后端：

   ```bash
   npm run dev
   ```

## 前端 UI 约定

- 后台与业务页面统一使用 **Radix** 体系组件（优先 `@radix-ui/themes`，必要时使用 `@radix-ui/react-*` primitives）。
- 不再使用 `web/src/components/ui/*` 自定义 UI 封装层（button/input/select/dialog/table/checkbox/textarea 等）。

## 认证接口

- `POST /api/v1/auth/register`
- `POST /api/v1/auth/login`
- `POST /api/v1/auth/refresh`
- `POST /api/v1/auth/logout`
- `GET /api/v1/auth/me`
- `POST /api/v1/users`（需要 `user.manage`，支持管理员自定义用户ID并校验重复）
- `GET /api/v1/users`（需要 `user.manage`）
- `GET /api/v1/users/{id}`（本人或 `user.manage`）
- `PATCH /api/v1/users/{id}`（需要 `user.manage`）
- `POST /api/v1/users/{id}/password`（需要 `user.manage`，重置用户密码）
- `DELETE /api/v1/users/{id}`（需要 `user.manage`，删除用户）
- `POST /api/v1/users/{id}/roles`（需要 `user.manage`）

初始化管理员（可选）：
- 在 `.env` 设置 `INITIAL_ADMIN_EMAIL`、`INITIAL_ADMIN_USER_ID`、`INITIAL_ADMIN_USERNAME`、`INITIAL_ADMIN_PASSWORD`
- 默认值：`INITIAL_ADMIN_USER_ID=admin`、`INITIAL_ADMIN_USERNAME=管理员`
- API 启动时会自动创建并赋予 `admin` 角色

## Docker Compose 部署

- 开发部署目录：`deploy/dev-deploy`
- 生产部署目录：`deploy/pro-deploy`

1. 准备环境变量：

   ```bash
   cp deploy/dev-deploy/.env deploy/dev-deploy/.env.local
   cp deploy/dev-deploy/.env.dev deploy/dev-deploy/.env.dev.local
   ```

2. 构建并启动容器：

   ```bash
   docker compose --env-file deploy/dev-deploy/.env -f deploy/dev-deploy/compose.yml up --build -d
   ```

3. 查看运行状态和日志：

   ```bash
   docker compose --env-file deploy/dev-deploy/.env -f deploy/dev-deploy/compose.yml ps
   docker compose --env-file deploy/dev-deploy/.env -f deploy/dev-deploy/compose.yml logs -f
   ```

4. 访问服务：

- 前端：`http://localhost:3000`
- 后端：`http://localhost:8000/health`
- PostgreSQL：默认连接外部库（`DB_HOST/DB_PORT/DB_NAME/DB_SCHEMA/DB_USERNAME/DB_PASSWORD`）
- 本地 PostgreSQL：`localhost:5434`（可通过 `deploy/dev-deploy/.env` 的 `POSTGRES_PORT` 覆盖）

5. 停止并清理：

   ```bash
   docker compose --env-file deploy/dev-deploy/.env -f deploy/dev-deploy/compose.yml down
   ```

说明：
- `NEXT_PUBLIC_API_BASE_URL` 在 Next.js 中是构建期注入；如果修改该值，需要重新执行 `docker compose --env-file deploy/dev-deploy/.env -f deploy/dev-deploy/compose.yml up --build`。
- 若未显式设置 `DATABASE_URL`，API 会使用 `DB_*` 变量自动组装 PostgreSQL 连接，并将 `DB_SCHEMA` 作为 `search_path`（等价 JDBC 的 `currentSchema` 语义）。
- 若出现跨域（CORS）错误，请在 `.env` 配置：
  - `API_CORS_ORIGINS`：精确来源列表（逗号分隔），如 `https://admin.example.com,http://localhost:3000`
  - `API_CORS_ORIGIN_REGEX`：来源正则（可选），如 `https://.*\\.example\\.com`
  - 支持在 `API_CORS_ORIGINS` 中使用通配符（如 `https://*.example.com`）或 `*`（仅建议开发调试）
- 默认镜像源已配置为 `docker.m.daocloud.io`，并默认使用 `pgvector` 镜像；如你网络环境可直连 Docker Hub，可在 `deploy/dev-deploy/.env` 中覆盖 `POSTGRES_IMAGE / PYTHON_BASE_IMAGE / NODE_BASE_IMAGE`。
