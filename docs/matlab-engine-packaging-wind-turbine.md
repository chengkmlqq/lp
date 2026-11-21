# 单风机计算引擎（`wind_turbine_calc`）编译打包说明

> 面向"下一个接手的人"：从 MATLAB 源码到平台上跑出结果的全过程，步骤可直接照做。
> 文中结论以仓库当前代码为准，关键位置标了文件与行号，改动前请先核对。
>
> 引擎模块 slug：`wind_turbine_calc`（`api/app/services/wind_turbine_calc_service.py:45`）
> 算法公式与积分步长**不属于本仓库**，本仓库只对接文件接口；任何"顺手优化算法"的改动都不允许。

---

## 1. 运行形态总览

| 项 | 值 | 依据 |
|---|---|---|
| 编译机 | Linux（与目标 Runtime 同为 R2025a） | `api/Dockerfile.matlab.wind` 头部注释 |
| MATLAB Runtime | R2025a（25.1），`/opt/matlabruntime/R2025a` | `api/Dockerfile.matlab.wind` |
| 可执行入口 | `main_angle`（Linux 无后缀） | `api/app/core/config.py:163` |
| 启动脚本 | `run_main_angle.sh`（**不带参数**） | `api/app/core/config.py:164` |
| worker 镜像 | `fquiz-matlab-wind-worker:r2025a`（`Dockerfile.matlab.wind` 构建） | `.env.example:59` |
| 消费队列 | `matlab-wind`（仅此镜像消费，禁止与 `matlab-diagnostics` 混用） | `api/app/core/config.py:165` |
| 部署目录（容器内） | `/app/matlab-wind`，挂载宿主机 `./data/matlab-wind` | `deploy/pro-deploy/compose.yml` |
| 任务工作目录 | `${WIND_TURBINE_CALC_WORK_ROOT}/wind-turbine-calc/<job_id>` | `api/app/services/wind_turbine_calc_service.py` |

单风机与故障判别是两套**互不兼容**的 Runtime（R2025a vs R2023a），镜像、队列、部署卷都必须分开。把单风机产物丢进判别 worker，只会报"找不到 Runtime 库"。

---

## 2. 接口契约（写代码前必须读）

调用方把编译产物当黑盒，只通过**工作目录里的文件**交互。契约实现见 `api/app/services/wind_turbine_calc.py`（纯函数内核）与 `wind_turbine_calc_service.py:469` 起的 `run_job`。

### 2.1 输入：`<cwd>/params.json`

启动时 **cwd 就是任务工作目录**（例如 `/app/data/wind-turbine-calc/wind-turbine-calc/<job_id>/`），`params.json` 由后端写入该目录，UTF-8、`indent=2`：

```json
{
  "hub_height": 105.5,
  "receptor_radii": [53.6, 63.6, 73.6, 78.6, 82.6],
  "blade_length": 82.6,
  "start_current": 1.0,
  "angle_list": [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110]
}
```

| 字段 | 类型 | 含义 |
|---|---|---|
| `hub_height` | number | 轮毂高度 h（m） |
| `receptor_radii` | number[] | 接闪器径向位置 r_list，严格递增、均 > 0、不得大于 `blade_length` |
| `blade_length` | number | 叶片长度 R（m）；后端缺省时取 `max(receptor_radii)` |
| `start_current` | number | 起始雷电流 Ic（kA），> 0 |
| `angle_list` | number[] | 旋转角（deg），最多 36 个 |

**只从 `cwd` 读 `params.json`，不要用 `mfilename('fullpath')` / `ctfroot` 去拼相对目录**——编译产物解压在 `/app/matlab-wind`，工作目录在别处，用脚本自身路径拼出来的目录一定是错的。

### 2.2 输出：`<cwd>/results/failure_rate_by_theta.csv`

- 路径固定为 `results/failure_rate_by_theta.csv`（相对 cwd；`results/` 需要自己 `mkdir`）。
- 表头必须为 `Theta_deg,FailureRate,FailureRate_pct`（大小写按此写法最稳；解析器也兼容 `theta` / `angle` / `角度` 等别名，见 `wind_turbine_calc.py:147`，但不要依赖它）。
- 每个角度一行，角度升序，与 `angle_list` 一一对应：

```csv
Theta_deg,FailureRate,FailureRate_pct
0,0.00622877556642743,0.622877556642743
10,0.00630627791810152,0.630627791810152
```

- 数值精度：至少保留 12 位有效数字（建议 `%.17g`）。回归基准容差是 **1e-9**，`%.4f` 这类写法必然对不上。
- 建议**每算完一个角度就 flush 一行**：后端按 CSV 数据行数推任务进度（`wind_turbine_calc_service.py` 的进度循环），一次性写完会让进度条一直停在 5%。
- 可选输出 `results/failure_rate_by_theta.png` 或 cwd 下的同名 PNG；没有则由后端用 matplotlib 按 CSV 现画。

### 2.3 退出码与日志

- 退出码 `0` = 成功；非 `0` 一律判失败，任务被标记 `failed`，错误信息里带 stdout 尾部 20 行。
- 退出码 0 但 CSV 缺失或为空 → 同样判失败（"核心程序未产出 results/failure_rate_by_theta.csv 或文件为空"）。
- stdout / stderr 合并重定向到工作目录的 `stdout.log`，随任务日志进任务监控；MATLAB 里的 `fprintf` / `warning` 都会被看到，排查时优先看这里。
- 超时：exe 软 6h / 硬 12h，Celery 软 7h / 硬 13h。软超时会 `SIGTERM` 整个进程组，硬超时 `SIGKILL`。

---

## 3. 编译（Linux R2025a）

### 3.1 前提

- MATLAB **R2025a** + MATLAB Compiler（版本必须与 Runtime 一致，用 R2023a 编出来的包在 R2025a Runtime 上跑不了，反之亦然）。
- 源码三件套：
  - `main_angle.m` —— 入口 wrapper（本次需要新写/改造的部分）
  - `EGM_first_intercept_integral_angle.m` —— 算法函数，**原样带入，不得修改**
  - `scan_first_intercept_angle.m` —— 扫描函数，**原样带入，不得修改**

### 3.2 wrapper 要做的事

`main_angle.m` 是唯一新增的胶水层，职责只有四件：

1. 读当前目录的 `params.json`：

   ```matlab
   params = jsondecode(fileread(fullfile(pwd, 'params.json')));
   ```

2. 用参数重建算法内部结构 `cic`（轮毂高度、接闪器半径列表、叶片长度、起始电流）。**重建方式照抄原程序 `run_*.m` 里的构造顺序**，字段名与量纲保持一致。
3. 按 `params.angle_list` 逐角度调用 `EGM_first_intercept_integral_angle` / `scan_first_intercept_angle`，累加得到该角度的失效率。**公式、积分步长、收敛判据一律照搬，不做任何"等价改写"**。
4. 写 CSV：`results/` 不存在则 `mkdir`，按 2.2 的表头和精度逐行写出并 flush。

参考骨架（只表达结构，算法调用以原程序为准）：

```matlab
function main_angle()
  params = jsondecode(fileread(fullfile(pwd, 'params.json')));
  R = params.blade_length;
  if isempty(R), R = max(params.receptor_radii); end
  cic = build_cic(params.hub_height, params.receptor_radii, R, params.start_current);  % 照抄原程序

  outDir = fullfile(pwd, 'results');
  if ~exist(outDir, 'dir'), mkdir(outDir); end
  fid = fopen(fullfile(outDir, 'failure_rate_by_theta.csv'), 'w');
  fprintf(fid, 'Theta_deg,FailureRate,FailureRate_pct\n');

  for k = 1:numel(params.angle_list)
    theta = params.angle_list(k);
    rate = scan_first_intercept_angle(cic, theta);   % 原算法，不改
    fprintf(fid, '%g,%.17g,%.17g\n', theta, rate, rate * 100);
    fflush(fid);
  end
  fclose(fid);
end
```

编译产物是命令行程序，入口函数带不带参数都行——**参数一律通过 `params.json` 传，不要靠 argv**。

### 3.3 mcc 命令

```bash
cd /path/to/src
matlab -batch "mcc -m main_angle.m \
  -a EGM_first_intercept_integral_angle.m \
  -a scan_first_intercept_angle.m \
  -d build/main_angle \
  -o main_angle"
```

产物目录 `build/main_angle/` 里至少会有：

```
main_angle            # ELF 可执行文件（Linux 无 .exe 后缀）
run_main_angle.sh     # mcc 自动生成的启动脚本
mccExcludedFiles.log
readme.txt
```

### 3.4 改造 `run_main_angle.sh`

mcc 生成的脚本形如 `./run_main_angle.sh <MATLAB_Runtime_安装路径>`，**必须带 Runtime 路径参数**——而调用方是 `bash run_main_angle.sh`，不带任何参数（`wind_turbine_calc_service.py:455` 的 `_resolve_command`）。所以要把脚本改成"Runtime 路径写死、零参数"：

```sh
#!/bin/sh
# 单风机引擎启动脚本：Runtime 路径固定在 matlab-wind 镜像内，调用方不带参数。
APP_DIR=$(cd "$(dirname "$0")" && pwd)
MCR_ROOT=/opt/matlabruntime/R2025a

# R2025a 起 MathWorks Runtime 强制要求显式同意许可，缺这项编译产物启动即退出
export AGREE_TO_MATLAB_RUNTIME_LICENSE=yes
export LD_LIBRARY_PATH="$MCR_ROOT/runtime/glnxa64:$MCR_ROOT/bin/glnxa64:$MCR_ROOT/sys/os/glnxa64:$MCR_ROOT/sys/opengl/lib/glnxa64${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

exec "$APP_DIR/main_angle" "$@"
```

要点：

- `LD_LIBRARY_PATH` 四段与 `Dockerfile.matlab.wind` 里的 `ENV` 完全一致，少一段就可能 `libmwmclmcr.so` 加载失败。
- 用 `APP_DIR` 定位可执行文件是允许的；但**程序内部的数据目录必须用 cwd**，两者不要混（见 2.1）。
- 手动冒烟：`bash run_main_angle.sh`（cwd 里已有 `params.json`）应产出 `results/failure_rate_by_theta.csv`，退出码 0。

---

## 4. 命名、必需文件与目录

| 名称 | 说明 |
|---|---|
| `main_angle` | 可执行文件，Linux 无后缀 |
| `run_main_angle.sh` | 启动脚本，**不带参数** |

引擎模块的 `required_files` 当前种子值写的是 `["main_angle.exe", "run_main_angle.sh"]`（`api/app/services/seed_service.py:938`），而 Linux 产物叫 `main_angle`。上传时 `_validate_zip_content` 按 **basename 精确匹配**（`api/app/services/fault_matlab_engine_service.py:127`），所以：

- 直接传 Linux 包 → 报 `ZIP 包缺少必需文件: main_angle.exe`；
- 修复方式：在引擎管理页编辑 `wind_turbine_calc` 模块，把 `required_files` 改成 `["main_angle", "run_main_angle.sh"]`；或调 `PUT /api/v1/fault-matlab/modules/wind_turbine_calc`。种子只在模块不存在时补齐，不会覆盖已有配置，改完就一直生效。
- 反过来，如果确实打成 `main_angle.exe`（例如在 Windows 上编），也要与实际文件名一致，别一边改名一边不改配置。

部署目录是容器内 `/app/matlab-wind`：

```yaml
matlab-wind-worker:
  volumes:
    - ./data/matlab-wind:/app/matlab-wind
```

同步任务会把 ZIP 解压到这个目录，`worker_deploy_path` 里记的必须是**容器内路径**，不要写宿主机路径。

---

## 5. 打包 ZIP

在 Linux 上打，避免可执行位丢失与中文名编码问题：

```bash
cd build/main_angle
chmod 755 main_angle run_main_angle.sh
zip -X -r /tmp/wind_turbine_calc_linux_R2025a_v1.0.0.zip \
  main_angle run_main_angle.sh readme.txt
```

期望结构（**不要在 ZIP 里再套一层目录**）：

```
wind_turbine_calc_linux_R2025a_v1.0.0.zip
├── main_angle
├── run_main_angle.sh
└── readme.txt
```

多一层包装目录（如 `main_angle_linux_R2025a/`）也能被同步任务拍平（`sync_matlab_engine_task.py` 的 `_flatten_wrapper_dir`），但前提是"只有一层且根目录下没有已知可执行文件"；嵌套两层或同时存在平铺文件时不保证，能不打就别打。

---

## 6. 上传 → 发布 → 生效

1. **上传即发布**：引擎管理页选 `wind_turbine_calc` 模块 →「上传新包」→ 填 ZIP、版本号（如 `v1.0.0`）、变更日志。接口：`POST /api/v1/fault-matlab/modules/wind_turbine_calc/upload`。校验通过即成为已发布版本（没有草稿环节），同一 `version_hash` 重复上传会被拒，版本号也不能重复。
2. **生效（同步到 Worker）**：在该版本行点「生效」（`POST /api/v1/fault-matlab/modules/{slug}/versions/{version_hash}/sync`）。同步任务按模块的 `worker_queue` 路由到 `matlab-wind`，在 worker 容器内执行：
   - 从对象存储拉 `matlab-engine/release/wind_turbine_calc/<hash>/engine.zip`；
   - 备份旧目录到 `/app/matlab-wind_backup_<hash>`；
   - 清空 `/app/matlab-wind` 后解压 → 修 GBK 文件名 → 拍平包装目录 → 对 `KNOWN_EXE_NAMES` 补 `755`；
   - 回写 `is_active` / `deployed_at`，页面显示「Worker 已部署」。
3. 同步任务日志在**任务监控**里看，关键字：`[flatten]`、`Set executable bit on ...`、`Found executables: main_angle`、`Recorded version ... as deployed in worker`。

---

## 7. 反例：为什么不能直接用 `single_turbine_linux_v1.zip`

`single_turbine_linux_v1.zip` 是早期用 `deploy_single_turbine.m` 编的**冒烟程序**，只用来验证"Linux Runtime 能起来"，不满足 LP 契约，上传上去必然跑失败。四个硬伤：

| # | 冒烟包的行为 | LP 契约要求 |
|---|---|---|
| 1 | 入口名是 `single_turbine` 一套 | 入口必须是 `main_angle` + `run_main_angle.sh` |
| 2 | 启动脚本/程序需要 Runtime 路径等参数 | 脚本必须零参数（`bash run_main_angle.sh`） |
| 3 | 不读 `params.json`，参数写死在代码里 | 必须从 cwd 的 `params.json` 读五个字段 |
| 4 | 输出 `output/single_turbine_result.txt` 单个数值 | 必须输出 `results/failure_rate_by_theta.csv` 三列表头 |

结论：它只能作为"环境是否通"的探针，**任何情况下都不要作为版本上传**；看到有人传这个包，直接拦下。

---

## 8. 验收基准

### 8.1 golden case

默认参数：

```
hub_height       = 105.5
receptor_radii   = [53.6, 63.6, 73.6, 78.6, 82.6]
blade_length     = 82.6
start_current    = 1.0
angle_list       = 0,10,20,30,40,50,60,70,80,90,100,110
```

12 个角度的失效率（`api/app/services/wind_turbine_calc.py:26` 的 `GOLDEN_FAILURE_RATES`，容差 **≤ 1e-9**）：

| Theta_deg | FailureRate |
|---|---|
| 0 | 0.00622877556642743 |
| 10 | 0.00630627791810152 |
| 20 | 0.00652826327652078 |
| 30 | 0.00683634573238524 |
| 40 | 0.00714491493890870 |
| 50 | 0.00737805722869206 |
| 60 | 0.00746396580010588 |
| 70 | 0.00737904070704741 |
| 80 | 0.00714485503401852 |
| 90 | 0.00683454583833169 |
| 100 | 0.00652839719423753 |
| 110 | 0.00630859970252665 |

均值 **0.006840169911441951**。

本地对拍（工作目录里有 `results/failure_rate_by_theta.csv` 后）：

```bash
python - <<'PY'
import csv, statistics
golden = [0.00622877556642743,0.00630627791810152,0.00652826327652078,0.00683634573238524,
          0.00714491493890870,0.00737805722869206,0.00746396580010588,0.00737904070704741,
          0.00714485503401852,0.00683454583833169,0.00652839719423753,0.00630859970252665]
rows = list(csv.DictReader(open("results/failure_rate_by_theta.csv", encoding="utf-8-sig")))
rates = [float(r["FailureRate"]) for r in rows]
assert len(rates) == 12, f"行数不对: {len(rates)}"
diffs = [abs(a-b) for a, b in zip(rates, golden)]
print("max diff:", max(diffs))
print("mean:", repr(sum(rates)/len(rates)))
assert max(diffs) <= 1e-9, "超差"
assert abs(sum(rates)/len(rates) - 0.006840169911441951) <= 1e-9
PY
```

### 8.2 平台链路

上传 → 发布 → 生效后：引擎管理页该版本带「Worker 已部署」；单风机计算页新建任务，跑完 12 角度，均值与上表一致；导出 ZIP（`type=all`）里包含 `failure_rate_by_theta.csv`、PNG、`params.json`。

---

## 9. 已知坑

| 现象 | 原因 | 处理 |
|---|---|---|
| 上传报 `ZIP 包缺少必需文件: main_angle.exe` | 模块 `required_files` 仍写 `.exe`，而 Linux 产物无后缀 | 改模块 `required_files`（见 §4） |
| 产物解压后名字是乱码、`chmod` 找不到文件 | Windows 打包工具把中文名按 GBK 写进 ZIP 且未置 UTF-8 flag | 同步任务会按 cp437→UTF-8/GBK 还原（`fix_gbk_zip_filename`，LP-530）；根治办法仍是在 Linux 上用 `zip -X` 打包 |
| 执行报 `Permission denied` | Windows 打的 ZIP 不带 Unix 权限位，解压后没有 x 位 | 同步任务会对已知可执行名补 `755`；新增入口名需登记进 `KNOWN_EXE_NAMES`（`sync_matlab_engine_task.py:19`） |
| 找不到可执行文件，但 ZIP 里明明有 | ZIP 多了包装目录，且根目录还有其它文件导致不满足"单层拍平"条件 | 重新按平铺结构打包 |
| 启动即退出，日志提示许可未同意 | R2025a Runtime 强制 `AGREE_TO_MATLAB_RUNTIME_LICENSE=yes` | 启动脚本里 `export`（§3.4），worker compose 里也设了 |
| `bash: run_main_angle.sh: No such file` / 脚本报缺参数 | 上传的是 mcc 原始脚本，且文件名不对 | 用 §3.4 改造后、命名为 `run_main_angle.sh` 再打包 |
| 任务一直 `pending` | `matlab-wind` 队列没有消费者 | `docker compose ps` 看 `matlab-wind-worker` 是否在跑；不要用 `celery-worker` 顶替 |
| 任务卡在 5% | 产物最后才写 CSV | 每算完一个角度 flush 一行 |
| 结果"看起来对"但回归超差 | 精度截断，或有人改了积分步长 | 用 `%.17g`；算法文件保持原样 |
| 单风机产物放到判别 worker | Runtime 版本不匹配 | 只能进 `matlab-wind`；`matlab-diagnostics` 是 R2023a |

---

## 10. 排查顺序

1. 任务监控 → 该任务日志：看 `启动单风机计算：启动脚本 run_main_angle.sh` 有没有出现，判断走的是脚本还是裸可执行文件。
2. 报错里的 `stdout 尾部`：MATLAB Runtime 的报错（缺库、许可、函数找不到）都在这里。
3. `docker compose exec matlab-wind-worker ls -l /app/matlab-wind`：确认 `main_angle`、`run_main_angle.sh` 存在且有 x 位。
4. 手工复现：进容器、造一个 `params.json`、`bash /app/matlab-wind/run_main_angle.sh`，看退出码和 `results/`。
5. 引擎管理页版本列表：`is_active` 是否指着你以为的那个版本（回退后重新发布会存在同 hash 多条记录，只有最靠前的一条会被标记）。
