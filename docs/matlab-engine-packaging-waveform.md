# 故障判别引擎（`waveform-engine`）编译打包说明

> 面向"下一个接手的人"：从 MATLAB 源码到平台判别任务真正跑起来。
> 判别引擎和单风机引擎是两套独立 Runtime（R2023a vs R2025a），镜像、队列、部署卷都不共用。
> 单风机那份见 `docs/matlab-engine-packaging-wind-turbine.md`。
>
> 模块 slug 以引擎管理页 / `GET /api/v1/fault-matlab/modules` 返回为准。历史默认 slug 是
> `waveform_diagnosis`（`api/app/tasks/sync_matlab_engine_task.py:15`），本文统一写 `waveform-engine`
> 只是沿用任务里的叫法——**操作前先确认实际 slug**。

---

## 1. 产物与运行形态

| 项 | 值 | 依据 |
|---|---|---|
| 可执行入口 | `RunWaveAnalysisModule`（Linux ELF，无后缀） | `api/app/services/fault_matlab_engine_service.py:39` |
| 启动脚本 | `run_RunWaveAnalysisModule.sh`（必需文件之一） | 同上 |
| MATLAB Runtime | **R2023a**（glnxa64） | `api/Dockerfile.mcrbase` 的 `MCR_VERSION` |
| 基础镜像 | `fquiz-mcr-base:r2023a`（`python:3.11-slim-bookworm` + Linux MCR） | `api/Dockerfile.matlab` |
| worker 镜像 | `fquiz-matlab-worker`（由 `api/Dockerfile.matlab` 构建） | `.github/workflows` 的 `build-matlab-worker` |
| 消费队列 | `matlab-diagnostics`（判别任务与引擎同步任务共用） | `api/Dockerfile.matlab` 的 `CMD`、`api/app/tasks/fault_diagnosis_tasks.py:80` |
| 部署目录（容器内） | `/app/matlab-wave` | `api/Dockerfile.matlab`、`deploy/pro-deploy/compose.yml` |
| 目录来源 | 环境变量 `FAULT_DIAG_MATLAB_COMPILED_DIR` | `api/app/core/config.py:204` |
| 宿主机卷 | `./data/matlab-worker/matlab-wave:/app/matlab-wave` | `deploy/pro-deploy/compose.yml` |

引擎是**外部卷**，不在镜像里：换引擎版本只替换卷内文件，不重建镜像。镜像只在 `Dockerfile.matlab` 或判别相关 Python 代码变更时才重建（17.6GB，构建有专门的 skip 判断）。

---

## 2. 引擎模块配置

模块清单存在数据库 `system_param.matlab_engine.modules`（JSON），版本记录存 `matlab_engine.versions.<slug>`，引擎包存对象存储 `matlab-engine/release/<slug>/<version_hash>/engine.zip`（草稿在 `matlab-engine/draft/` 下）。

判别模块关键字段：

| 字段 | 判别（waveform） | 单风机（wind_turbine_calc） |
|---|---|---|
| `required_files` | `["RunWaveAnalysisModule", "run_RunWaveAnalysisModule.sh"]` | `["main_angle.exe", "run_main_angle.sh"]`（注意 `.exe`，见单风机文档 §4） |
| `worker_deploy_path` | `/app/matlab-wave` | `/app/matlab-wind` |
| `worker_queue` | `matlab-diagnostics` | `matlab-wind` |
| Runtime | R2023a | R2025a |
| 基础镜像 | `fquiz-mcr-base:r2023a` | `fquiz-matlab-runtime:r2025a`（MathWorks 官方 `matlab-runtime:r2025a` 转存） |
| worker 镜像 | `fquiz-matlab-worker` | `fquiz-matlab-wind-worker:r2025a` |
| 宿主机卷 | `./data/matlab-worker/matlab-wave` | `./data/matlab-wind` |
| 额外环境变量 | `FAULT_DIAG_MATLAB_COMPILED_DIR` | `AGREE_TO_MATLAB_RUNTIME_LICENSE=yes`、`WIND_TURBINE_CALC_*` |

`worker_queue` 缺省值是 `matlab-diagnostics`（`fault_matlab_engine_service.py:42`），历史模块没写这个字段时按它兜底。**不要把单风机模块的 `worker_queue` 改成 `matlab-diagnostics`**，那台机器没有 R2025a Runtime。

修改方式：引擎管理页「编辑模块」，或 `PUT /api/v1/fault-matlab/modules/{slug}`（`required_files`、`worker_deploy_path`、`worker_queue` 三个字段都可改）。

---

## 3. 调用契约

平台调用方式见 `api/app/services/fault_diagnosis_service.py:423` 的 `_try_matlab_wave_enhancement`：

```bash
/app/matlab-wave/RunWaveAnalysisModule <输入目录绝对路径> <输出根目录绝对路径>
```

- **只有两个位置参数**：暂存输入目录、输出根目录。
- 当前代码是**直接执行 ELF**（`command = [str(executable)]`），不经过 `run_RunWaveAnalysisModule.sh`；脚本仍被 `required_files` 强制要求，用于交付完整性与手工冒烟。因此二进制必须能靠镜像的 `LD_LIBRARY_PATH` 直接起来（`Dockerfile.matlab` / `Dockerfile.mcrbase` 已设）。
- 输入目录内容（由后端铺设）：
  - 行波数据文件（原样拷贝；`.txt` 会被清掉 `CurrentDataInput = ...` 行尾多余逗号，避免引擎内部 `assert(all(isfinite(x)))` 失败）；
  - `录波故障相<A|B|C>.txt`（内容形如 `录波故障相=A`）；
  - `幅值<xx>kA_耐雷水平<yy>kA.txt`（两行：`幅值=...` / `耐雷水平=...`）。
- 输出契约：
  - `<输出根目录>/最新结果路径.txt` —— 内容是**本次运行产物目录**的路径（一行）；
  - `<该目录>/wave_module_prediction.txt` —— 判别结果。
- 退出码非 0、或缺 `最新结果路径.txt`、或缺 `wave_module_prediction.txt`，都判引擎失败：判别任务变 `failed`，**不再静默降级**到 Python 启发式规则（引擎有问题必须可见）。
- 超时 600s；超时会被 kill 并报错。
- stdout / stderr 合并逐行转发到任务监控，前缀 `[MATLAB]`。这是排查引擎内部错误的第一现场。

> 注意：`waveform_engine_v2.exe` / `waveform_engine.exe`（Windows + Wine）是旧交付形态，代码仍兼容（`exe_names` 顺序里排在 `RunWaveAnalysisModule` 之前），但当前 Linux 方案不用它们。

---

## 4. 编译（Linux R2023a）

### 4.1 前提

- MATLAB **R2023a** + MATLAB Compiler（版本必须与 Runtime 一致；R2026a 的 Windows 产物是另一条 Wine 路线，别混）。
- 源码：`RunWaveAnalysisModule.m` 及其模型/数据依赖（CTF 内需要有完整判定模型）。

### 4.2 mcc 命令

```bash
cd /path/to/src
matlab -batch "mcc -m RunWaveAnalysisModule.m \
  -a <模型文件或数据目录> \
  -d build/RunWaveAnalysisModule \
  -o RunWaveAnalysisModule"
```

- `-a` 把非 `.m` 依赖（模型、查找表、配置）打进 CTF；`.m` 依赖 mcc 会自动分析，显式写上也更稳。
- `-d` 输出目录、`-o` 可执行名，保持 `RunWaveAnalysisModule` 不要改——平台按这个名字找入口。
- 产物目录里通常会看到：

```
RunWaveAnalysisModule      # ELF 可执行文件
run_RunWaveAnalysisModule.sh
mccExcludedFiles.log
readme.txt
requiredMCRProducts.txt    # 构建/打包时生成，一起带上
```

`requiredMCRProducts.txt` 记录本产物需要的 MCR 产品集，交付时与 `readme.txt` 一并放进 ZIP，便于对方核对 Runtime 版本与工具箱。

### 4.3 冒烟（可选，但在上传前值得做）

```bash
# 在一个临时目录里造最小输入，然后：
LD_LIBRARY_PATH=/opt/mcr/R2023a/runtime/glnxa64:/opt/mcr/R2023a/bin/glnxa64:/opt/mcr/R2023a/sys/os/glnxa64 \
  ./RunWaveAnalysisModule /tmp/wave_in /tmp/wave_out
echo "rc=$?"
cat /tmp/wave_out/最新结果路径.txt
```

注意两点：

- R2023a 的 MCR 在过新的发行版（Debian 13 / glibc 2.41+）上会段错误，必须用 `python:3.11-slim-bookworm` 这一档基础；镜像里还会用 `api/clear_execstack.py` 清掉 MCR 库的 RWE `GNU_STACK` 标记，否则新 glibc 直接拒绝加载。这两件事已经在 `Dockerfile.mcrbase` 里做好，不要在应用侧绕。
- 本机没有 MCR 时，冒烟只能在 worker 容器或同版本 Runtime 机器上做。

---

## 5. 打包 ZIP

在 Linux 上打（保留可执行位、避免中文名编码问题）：

```bash
cd build/RunWaveAnalysisModule
chmod 755 RunWaveAnalysisModule run_RunWaveAnalysisModule.sh
zip -X -r /tmp/waveform-engine-linux-r2023a-v1.2.0.zip \
  RunWaveAnalysisModule run_RunWaveAnalysisModule.sh requiredMCRProducts.txt readme.txt
```

期望结构（平铺最好）：

```
waveform-engine-linux-r2023a-v1.2.0.zip
├── RunWaveAnalysisModule
├── run_RunWaveAnalysisModule.sh
├── requiredMCRProducts.txt
├── readme.txt
└── （模型/数据依赖，如 *.mat、模型目录）
```

带一层包装目录（如 `RunWaveAnalysisModule_linux_R2023a/`）也能用：同步任务会拍平，但**只在"根目录没有任何已知可执行文件、且顶层只有一个目录"时**才拍。嵌套两层、或根目录混着文件和目录时不会拍，只会留下一个空壳目录和一句 `[flatten] No single wrapper dir to flatten`。

---

## 6. 上传 / 发布 / 同步

1. **上传即发布**：引擎管理页选判别模块 →「上传新包」→ ZIP + 版本号 + 变更日志。接口 `POST /api/v1/fault-matlab/modules/{slug}/upload`。
   - 上传前 `_validate_zip_content` 会按模块 `required_files` 检查 **basename**，缺一个直接 400：`ZIP 包缺少必需文件: ...`。
   - 同一 `version_hash`（sha256 前 16 位）重复上传会被拒；版本号也不能重复。
2. **选版本「生效」**：`POST /api/v1/fault-matlab/modules/{slug}/versions/{version_hash}/sync`，按模块 `worker_queue` 投递同步任务。
3. **同步任务**（`api/app/tasks/sync_matlab_engine_task.py`，队列 `matlab-diagnostics`，在 matlab-worker 容器内跑）依次做：
   1. 从对象存储下载 `matlab-engine/releases/<slug>/<hash>/engine.zip`；
   2. 把当前 `/app/matlab-wave` 备份到 `/app/matlab-wave_backup_<hash>`；
   3. 清空目标目录，解压，按 `fix_gbk_zip_filename` 还原中文名；
   4. `_flatten_wrapper_dir` 拍平单层包装目录；
   5. 对 `KNOWN_EXE_NAMES` 里的文件补 `755`；
   6. 打印 `Found executables: ...`；
   7. `mark_version_deployed` 回写 `is_active` / `deployed_at`（页面显示「Worker 已部署」）。
   任务日志走任务监控，任务结束后另存对象存储 `logs/<task_id>.log`。
4. 回退：在旧版本行点「生效」即可，同步任务会把旧包重新解压回去，同时把 `is_active` 移到那条记录上。同 hash 可能存在多条发布记录（回退后重新发布），只有列表中**最靠前的一条**会被标记生效。

---

## 7. 常见故障排查

| 现象 | 检查点 |
|---|---|
| 上传 400：`ZIP 包缺少必需文件: xxx` | ZIP 里文件是否真叫 `RunWaveAnalysisModule` / `run_RunWaveAnalysisModule.sh`（含大小写）；是否被多套了一层目录（校验用的是 basename，理论上不影响，但解压后位置会错）；`required_files` 是否被误改成 `.exe` |
| 上传后文件名是乱码 | Windows 打包工具按 GBK 写名且没置 UTF-8 flag。同步任务会按 cp437 → UTF-8/GBK 还原（LP-530），能救回来；根治是改用 Linux `zip -X` |
| 同步后执行 `Permission denied` | ZIP 不带 Unix 权限位。同步任务会给已知入口补 755；若新增了别的可执行名，要登记进 `KNOWN_EXE_NAMES`（`sync_matlab_engine_task.py:19`） |
| 同步任务一直 `pending`/排队 | `matlab-diagnostics` 没有消费者：`docker compose ps` 看 `matlab-worker`（分离部署时是 worker 机器上的容器）是否在跑；`celery -A ... inspect active_queues` 确认队列名。**33.2 本机不要再起第二个 `matlab-diagnostics` 消费者**，否则同步可能落到没挂引擎卷的机器上 |
| 同步成功但判别任务报"未找到可执行文件" | `FAULT_DIAG_MATLAB_COMPILED_DIR` 是否指向 `/app/matlab-wave`；容器内 `ls -l /app/matlab-wave` 确认文件在根目录；`check_worker_env.py` 第 4 节自检会直接列出已部署可执行文件 |
| 判别任务日志里 `[MATLAB]` 报缺库 / 启动即崩 | Runtime 版本不匹配（R2023a 产物必须配 R2023a MCR）；或系统 glibc 过新导致 MCR 段错误（必须用 bookworm 基础镜像） |
| 判别任务报 `returncode=249` | 行波输入里的非数值触发了引擎内部 assert（历史坑：`CurrentDataInput` 行尾多余逗号）。后端已清洗，仍出现说明输入文件格式又有新变体，拿任务日志里的 `[MATLAB]` 输出定位 |
| 判别任务失败但"以前能降级跑通" | 现在引擎已部署时**故意不降级**：失败就是失败。宁可暴露问题，也不返回启发式假结果 |
| 页面「已部署」标记指错版本 | 标记是全局单值，只适合一台 worker；回退/重发同 hash 时以列表最靠前的记录为准 |

---

## 8. 验收

1. 上传新版本 → 在版本列表点「生效」。
2. 任务监控看同步任务：出现 `Set executable bit` / `Found executables: RunWaveAnalysisModule` / `Recorded version ... as deployed in worker`，页面该版本带「Worker 已部署」。
3. 跑一次故障分析（任务进 `matlab-diagnostics`）：
   - 任务日志里能看到 `[MATLAB]` 逐行输出，且以 `Fault diagnosis MATLAB completed for ...: prediction=...` 结束；
   - 分析详情里出现行波判别结论，不再是 Python 启发式兜底。
4. 引擎版本核对：判别分析记录**不落库**引擎版本（`wind_turbine_calc_job` 才有 `engine_version_hash/tag`），所以以引擎管理页的「Worker 已部署」标记 + `deployed_at` 为准；需要更硬的证据就看 worker 容器内 `/app/matlab-wave` 的文件时间戳，或同步任务日志里的版本 hash。

---

## 9. 与单风机的差异速查

| 容易踩的点 | 判别 | 单风机 |
|---|---|---|
| Runtime | R2023a | R2025a（缺 `AGREE_TO_MATLAB_RUNTIME_LICENSE=yes` 直接退出） |
| 队列 | `matlab-diagnostics` | `matlab-wind` |
| 部署目录 | `/app/matlab-wave` | `/app/matlab-wind` |
| 入口 | `RunWaveAnalysisModule`（两个 argv：输入目录、输出根目录） | `main_angle`（零 argv，读 cwd 的 `params.json`） |
| 启动脚本 | 必需文件，但当前不走它 | 必需文件，**实际由 `bash run_main_angle.sh` 启动** |
| 产物交互 | `最新结果路径.txt` + `wave_module_prediction.txt` | `results/failure_rate_by_theta.csv` |
| 失败语义 | 抛错让任务失败，不降级 | 退出码非 0 即失败 |
