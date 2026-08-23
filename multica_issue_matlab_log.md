## 需求描述

故障分析（故障综合判别）调用后台 MATLAB 程序时，任务监控中只能看到调用出入口日志，看不到 MATLAB 实际执行日志，排查 MATLAB 侧问题时无从下手。需要把 MATLAB 实际执行的日志实时打印到任务监控的日志中（前端实时可见 + 任务结束后全量入库）。

### 问题描述

故障分析判别任务链路：

- `run_fault_diagnosis_task`（api/app/tasks/fault_diagnosis_tasks.py，Celery 任务，队列 matlab-diagnostics）
  → `run_fault_diagnosis_with_progress`（api/app/services/fault_diagnosis_service.py:1289）
  → `_try_matlab_wave_enhancement`（api/app/services/fault_diagnosis_service.py:402）
  → `subprocess.run(..., capture_output=True, text=True, timeout=600)`（第 503-509 行）

当前实现中，MATLAB 子进程的 stdout/stderr 被 `capture_output=True` 全部捕获到 `completed.stdout` / `completed.stderr`，但后续代码从未读取、从未打印这两个字段，只判断了 `returncode` 和结果文件（`最新结果路径.txt` / `wave_module_prediction.txt`）是否存在。即 MATLAB 实际执行过程（Runtime 启动、模型加载、计算过程、警告/报错）的日志全部被丢弃。

任务监控日志中目前只能看到（由 api/app/core/task_history_signals.py 的 TaskLogCapture 自动捕获）：
- Celery 边界日志（Task ... succeeded / FAILED + traceback）
- 业务 `logger.info` 出入口（如 `Fault diagnosis MATLAB completed for xxx: prediction=...`，fault_diagnosis_service.py:528）

### 当前行为

任务监控（前端任务监控页 → 日志详情）只有出入口日志，MATLAB 实际执行日志完全不可见。

### 期望行为

MATLAB 实际执行日志（stdout/stderr）实时打印到任务监控日志中：
- 任务运行期间，前端任务监控页可实时看到 MATLAB 执行过程日志（走现有 Redis Stream + SSE 实时通道）
- 任务结束后，全量日志进入 MinIO `logs/{task_id}.log` 持久化

## 实施建议（方案 A：流式读取 + logger 转发）

项目已有完整的实时日志基建，无需新造轮子：

- `api/app/core/task_log_capture.py` 的 TaskLogCapture：worker 进程启动即安装，捕获 logger 输出 / print / Celery 日志 → 内存缓冲 → 周期性 flush 到 Redis Stream（append_task_log_lines）→ 任务结束全量上传 MinIO logs/{task_id}.log。前端 SSE（api/app/api/v1/task_logs.py）实时读取。
- `task_prerun` 时 TaskLogCapture.start(task_id)、`task_postrun` 自动收尾上传（task_history_signals.py），故障诊断任务已在此链路内。

改造点集中在 `fault_diagnosis_service.py` 的 `_try_matlab_wave_enhancement` 一个函数：

1. 将 `subprocess.run(capture_output=True)` 改为 `subprocess.Popen` 逐行读取：
   ```python
   proc = subprocess.Popen(
       [*command, str(staged_input.resolve()), str(output_root.resolve())],
       stdout=subprocess.PIPE, stderr=subprocess.STDOUT,  # 合并两流
       text=True, encoding="utf-8", errors="replace", bufsize=1,
       env=env,
   )
   for line in proc.stdout:  # 逐行实时
       logger.info("[MATLAB] %s", line.rstrip())
   returncode = proc.wait(timeout=600)  # 保留原超时语义
   ```
2. worker 的 root handler → _TeeIO → 当前任务缓冲 → 自动实时进 Redis Stream，前端实时可见；结束后自动进 MinIO 全量日志。
3. 加 `[MATLAB]` 前缀便于与业务日志区分。
4. 注意：Popen 超时需自行处理（wait(timeout=600) 超时后 kill 进程，仍保留已捕获日志并打错误日志）；`completed.returncode` 改用 `proc.wait()` 的返回值；保持原有降级语义（失败返回 (None, None)，由调用方降级到内置 Python 规则）。

## 注意事项

- 保持原有降级语义：MATLAB 调用失败仍返回 (None, None)，调用方降级到内置可解释特征规则（analyze_traveling_waves 启发式分支）。
- 输出量控制：MATLAB 启动横幅等可能行数较多，任务缓冲有 5000 行上限 + 截断标记，无需额外处理。
- 并行安全：_TeeIO 按当前任务动态路由，多任务并发不串线（已有机制）。
- 方案 B（备选，不推荐）：去掉 capture_output 让 MATLAB 直接继承 Python stdout/stderr，由 _TeeIO 自动捕获。零改造但无法加前缀、无法按行处理。仅当方案 A 有兼容性问题时考虑。
- 改动完成后提交并推送 git（dev 分支）触发 CI 构建，不在本地构建镜像。
