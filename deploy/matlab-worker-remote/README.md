# MATLAB 判别 Worker · 分离部署（MinIO 走 SSH 隧道）

worker 跑在另一台机器，33.2 只提供 PostgreSQL / Redis / MinIO。三条通道全部经
SSH 隧道回到 33.2 的回环地址，不走公网端口。

```
worker 机器                                        33.2
┌──────────────────────────────┐        ┌────────────────────────────────────┐
│ lp-matlab-tunnel.service     │  ssh   │ sshd :22                           │
│  127.0.0.1:19000 ────────────┼───────►│ 127.0.0.1:9000   lp-minio          │
│  127.0.0.1:15432 ────────────┼───────►│ 127.0.0.1:15432  lp-remote-hub ──► │ lp-pg:5432
│  127.0.0.1:16379 ────────────┼───────►│ 127.0.0.1:16379  lp-remote-hub ──► │ lp-redis:6379
│                              │        └────────────────────────────────────┘
│ lp-matlab-worker (host 网络)  │
└──────────────────────────────┘
```

## 0. 为什么需要 33.2 上的 lp-remote-hub

MinIO 已发布在 `127.0.0.1:9000`，隧道直连即可。但 `lp-pg` / `lp-redis` 只挂在
docker 网络里、没有宿主机端口，而 sshd 跑在宿主机命名空间，解析不了容器名
（docker 内置 DNS `127.0.0.11` 只在容器内生效），所以 `-L 15432:lp-pg:5432`
必然失败。`lp-remote-hub` 用现成的 nginx 镜像（静态编译带 stream 模块）把两条
TCP 通道代理到宿主机回环，且按连接实时解析容器名——上游容器重启换 IP 也不会失效。

部署（一次性，独立 compose 项目，不动主 compose 和任何现有容器）：

```bash
mkdir -p /opt/lp/remote-hub
# 把 deploy/remote-hub/{compose.yml,nginx.conf} 传上去后：
cd /opt/lp/remote-hub
docker compose -p lp-remote-hub -f compose.yml up -d
docker compose -p lp-remote-hub -f compose.yml ps
```

验证（在 33.2 上）：

```bash
ss -lntp | grep -E '15432|16379'          # 两个回环监听
docker run --rm --network host -e PGPASSWORD=<pg密码> \
  pgvector/pgvector:pg17 psql -h 127.0.0.1 -p 15432 -U lp -d lp -c 'select 1'
docker run --rm --network host redis:7-alpine \
  redis-cli -h 127.0.0.1 -p 16379 -a <redis密码> ping
```

## 1. worker 机器准备

```bash
# 镜像来自 ACR，需要先登录（凭据与 33.2 相同）
docker login crpi-u265r07n4blchcqo.cn-shanghai.personal.cr.aliyuncs.com

mkdir -p /opt/lp-worker/{data/app,data/matlab-wave,.ssh}
cd /opt/lp-worker
# 拷入本目录的 compose.yml / check_worker_env.py / .env.example
cp .env.example .env && vi .env            # 填 DB/Redis/MinIO 密码与镜像
```

MATLAB Runtime 已在镜像内（`api/Dockerfile.matlab`），宿主机不需要装 MATLAB。

## 2. 建隧道

```bash
ssh-keygen -t ed25519 -f /opt/lp-worker/.ssh/lp_tunnel -N ""
ssh-copy-id -i /opt/lp-worker/.ssh/lp_tunnel.pub -p 59329 root@111.170.33.2
# 首次手工验证（应无输出、不断开）
ssh -N -p 59329 -i /opt/lp-worker/.ssh/lp_tunnel \
  -L 19000:127.0.0.1:9000 -L 15432:127.0.0.1:15432 -L 16379:127.0.0.1:16379 \
  root@111.170.33.2
```

另开一个终端确认端口通了再继续：

```bash
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:19000/minio/health/live   # 200
```

常驻：

```bash
cp tunnel/tunnel.env.example /opt/lp-worker/tunnel.env && vi /opt/lp-worker/tunnel.env
cp tunnel/lp-matlab-tunnel.service /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now lp-matlab-tunnel
systemctl status lp-matlab-tunnel --no-pager
journalctl -u lp-matlab-tunnel -n 20 --no-pager
```

## 3. 起 worker

```bash
cd /opt/lp-worker
docker compose pull
docker compose up -d
docker compose logs -f --tail=50
```

## 4. 自检（必须全绿再谈业务）

```bash
docker compose run --rm matlab-worker python /app/check_worker_env.py
```

逐项覆盖：配置是否真的指向 127.0.0.1、PG 连接、Redis PING、MinIO 列举+读写删探针、
引擎目录可写性与已部署可执行文件、引擎模块（`worker_deploy_path`、已发布包大小）。

## 5. 上传引擎并同步

1. 平台「引擎管理」上传/发布引擎包（对象存储 `matlab-engine/`）；
2. 点「同步到 Worker」——任务进 `matlab-diagnostics` 队列，由这台 worker 消费：
   下载 `engine.zip` → 备份旧目录 → 解压到 `/app/matlab-wave` → 修 GBK 文件名/扁平化/
   补 755 权限 → 写回「已部署」标记；
3. 同步完成后重跑第 4 步，应看到 `已部署可执行文件: RunWaveAnalysisModule`。

## 6. 注意事项

- **队列只能有一个消费者**：`matlab-diagnostics` 在 33.2 上不要再起 worker，
  否则引擎同步会随机落到没挂引擎卷的机器上（任务成功但引擎没更新）。多机时按
  队列名/主机名拆分。
- **`worker_deploy_path` 要保持 `/app/matlab-wave`**：库里记录的是容器内路径，
  换机器不影响，但别改成宿主路径。
- 「已部署」标记是全局单值：只适合一台 matlab worker。将来多台要改成按 worker 记录。
- 隧道断开时 worker 不会退出，会在 broker 上重试；排查先看
  `systemctl status lp-matlab-tunnel`，再看 `check_worker_env.py`。
- 大文件（引擎包、波形结果）都走隧道，带宽不够时同步会慢，但不会超时失败
  （对象存储客户端默认无整体超时，只有连接超时）。
