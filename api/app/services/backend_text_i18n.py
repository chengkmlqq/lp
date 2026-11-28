"""后端产物文本的 中→英 翻译层（LP-22）。

与 ``analysis_text_i18n`` 的区别：那个模块翻译塔详情「分析建议 / 枚举值」（面向
CSV 导出与页面展示）；本模块翻译**任务日志正文、WS 阶段文案、Word 报告文字**，
统一在日志/产物输出入口调用：

- ``translate_log_line`` / ``translate_log_lines``：``TaskLogCapture`` 写 Redis
  Stream 与 MinIO 前，对每一行做翻译。
- ``translate_backend_text``：WS ``step`` 事件、报告文字等纯文本。
- ``translate_report_docx``：对已生成的 docx 逐段翻译（无需改动报告生成逻辑）。

设计约束：
- ``lang != "en"`` 时**逐字返回原文**（中文界面与现状完全一致）。
- 动态值（塔号、进度、数值、路径、异常）通过正则反向引用原样带回，不丢失、不错位。
- 未命中的中文片段原样回落，绝不产生空洞。
- ATP 引擎原始 stdout/stderr 与 traceback 帧不做翻译（``_should_skip_line``）。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, Iterable

_HAS_ZH = re.compile(r"[\u4e00-\u9fff]")

# 引擎原始输出 / traceback 帧：原样保留，不翻译（LP-22 明确不覆盖）。
_SKIP_LINE = re.compile(
    r"^\s*(?:Traceback \(most recent call last\)|File \"|[A-Za-z_][\w.]*(?:Error|Exception|Warning):)"
)

# ───────────────────────── 1) 日志行模板（含动态值，反向引用带回） ─────────────────────────
# 每条规则用 re.sub 命中「中文模板片段」并替换，行首时间戳 / 日志级别等前缀自动保留。
# 替换值可为字符串（反向引用 \1）或 callable（动态枚举值需一并翻译时用）。

_ARRESTER_EN = {"无": "none", "有": "yes", "未装": "none", "已装": "yes"}
_TOWER_TYPE_EN = {
    "鼓型": "guxing", "猫头型": "maotou", "猫头": "maotou",
    "干字型": "ganzi", "酒杯型": "jiubei", "门型": "menxing",
    "上字型": "shangzi", "四回塔": "sihuita", "直流塔": "zhiliu",
}
_SCENE_EN = {"反击": "fanji", "绕击": "raoji"}


def _auto_asset_replacement(m: re.Match[str]) -> str:
    arrester = _ARRESTER_EN.get(m.group(4), m.group(4))
    tower = _TOWER_TYPE_EN.get(m.group(2), m.group(2))
    scene = m.group(3)
    for zh, en in _SCENE_EN.items():
        if scene.startswith(zh):
            scene = en + scene[len(zh):]
            break
    return (
        f"[ATP] Auto-selected asset: voltage={m.group(1)} tower type={tower} "
        f"scene={scene} arrester={arrester}(source={m.group(5)}, hit={m.group(6)}) "
        f"→ asset={m.group(7)} ({m.group(8)})"
    )


_LOG_RULES: list[tuple[str, str | Callable[..., str]]] = [
    # ATP / 防雷计算（fl_analysis_service.py）
    (r"\[ATP\] 开始处理杆塔 (\S+)（第 (\d+)/(\d+) 根）", r"[ATP] Processing tower \1 (no. \2/\3)"),
    (r"\[ATP\] 杆塔 (\S+) 写库前数据库连接已失效，重建连接后继续", r"[ATP] DB connection lost before writing tower \1; reconnected and continuing"),
    (r"\[ATP\] 杆塔\s*(\S*) 计算失败（单塔独立，任务继续）", r"[ATP] Tower \1 calculation failed (per-tower isolated, task continues)"),
    (r"\[ATP\] 绕击 EGM 跳过（塔 (\S+)）", r"[ATP] Shielding-failure EGM skipped (tower \1)"),
    (r"\[EGM\] 风险等级重算失败（保留原值）", r"[EGM] Risk grade recalculation failed (keeping previous value)"),
    (r"\[ATP\] 绕击(\d+)相 DB 链路瞬断（第(\d+)/3 次），换新会话重试", r"[ATP] Phase \1 shielding DB connection dropped (attempt \2/3); retrying with a new session"),
    (r"\[fl-analysis\] 已清理任务 (\S+) 运行结果目录", r"[fl-analysis] Cleaned up run result directory for task \1"),
    (r"\[fl-analysis\] 清理任务 (\S+) 运行结果目录失败", r"[fl-analysis] Failed to clean up run result directory for task \1"),
    (r"\[fl-analysis\] 任务 (\S+) 已取消，跳过队列中的残留消息", r"[fl-analysis] Task \1 cancelled; skipping queued residual messages"),
    (r"\[fl-analysis\] 任务 (\S+) 全部塔计算失败，标记 failed：结果数=0/(\d+)", r"[fl-analysis] All towers failed for task \1, marking failed: results=0/\2"),
    (r"撤销 celery 任务失败：job=(\S+) task=(\S+)", r"Failed to revoke celery task: job=\1 task=\2"),
    (r"取消写状态遇行锁，重试 (\d+)/6：job=(\S+)", r"Row lock while writing cancelled state, retry \1/6: job=\2"),
    (r"任务已被取消，跳过 (\S+) 状态写回：job=(\S+)", r"Task cancelled; skipping \1 state write-back: job=\2"),
    # 地闪分布 / LP 分区 / 雷电流幅值（lightning_tasks.py）
    (r"地闪分布导入任务启动（distribution_id=(\S+)）", r"Ground-flash distribution import task started (distribution_id=\1)"),
    (r"开始渲染地闪密度图（均匀网格）", r"Rendering ground-flash density map (uniform grid)"),
    (r"LP 分区绘图任务启动（distribution=(\S+), line=(\S+)）", r"LP partition plotting task started (distribution=\1, line=\2)"),
    (r"未找到线路记录（line_id=(\S+)）", r"Line record not found (line_id=\1)"),
    (r"线路 (\S+) 无带经纬度杆塔，无法绘图", r"Line \1 has no towers with coordinates; cannot plot"),
    (r"LP 分区密度图渲染完成，开始上传到对象存储", r"LP partition density map rendered; uploading to object storage"),
    (r"LP 分区密度图已上传（(\S+)）", r"LP partition density map uploaded (\1)"),
    (r"开始导入雷电流幅值：(\S+)", r"Importing lightning current amplitude: \1"),
    (r"未找到幅值记录（(\S+)），终止任务", r"Amplitude record not found (\1); aborting task"),
    (r"源文件对象键：(\S+)，文件名：(\S+)", r"Source object key: \1, file name: \2"),
    (r"开始从对象存储读取源文件（(\S+)）", r"Reading source file from object storage (\1)"),
    (r"对象存储读取完成，字节数：(\d+)", r"Object storage read complete, bytes: \1"),
    (r"文件解码完成，文本行数：(\d+)", r"File decoded, text lines: \1"),
    (r"解析完成，采样点数量：(\d+)，解析警告数：(\d+)", r"Parsing complete, samples: \1, parse warnings: \2"),
    (r"解析校验通过，采样点数：(\d+)", r"Parse validation passed, samples: \1"),
    (r"时间轴构建完成，采样间隔：(\S+)us，采样频率：(\S+)Hz", r"Time axis built, interval: \1us, sample rate: \2Hz"),
    (r"自动生成事件编号：(\S+)", r"Auto-generated event id: \1"),
    (r"开始线路雷电流幅值回填：线路ID=(\S+)", r"Backfilling line lightning current amplitudes: line_id=\1"),
    (r"线路杆塔数：(\d+)基", r"Tower count on line: \1"),
    (r"回填任务记录已更新为 processing（ID=(\S+)）", r"Backfill task record updated to processing (ID=\1)"),
    (r"回填参数：region_id=(\S+)，is_synthetic=(\S+)", r"Backfill params: region_id=\1, is_synthetic=\2"),
    (r"开始线路地闪密度回填：线路ID=(\S+)", r"Backfilling line ground-flash density: line_id=\1"),
    (r"报告生成失败（不影响判别结果）", r"Report generation failed (does not affect diagnosis result)"),
    # ATP 外部引擎：模板渲染 / 数值注入 / 几何槽位 / dT 自适应（LP-148）
    (r"\[ATP\] 模板渲染完成，输入文件大小=(\d+) 字节，代码版本=(\S+)，几何覆写=(\S+)，覆写项=(\d+)",
     r"[ATP] Template render complete, input file size=\1 bytes, code version=\2, geometry override=\3, override items=\4"),
    (r"\[ATP\] 数值参数覆写（(\S+)）：(.+)",
     r"[ATP] Numeric parameter override (\1): \2"),
    (r"\[ATP\] 耦合系数槽位（(\S+)）：(.+)",
     r"[ATP] Coupling coefficient slot (\1): \2"),
    (r"\[ATP\] 14XXSS 电角度已按 C# 规则改写：A=(-?[\d.]+) B=(-?[\d.]+) C=(-?[\d.]+)",
     r"[ATP] 14XXSS electrical angle rewritten per C# rules: A=\1 B=\2 C=\3"),
    (r"其中 (\d+)/(\d+) 条支路波速取自 \$PARAMETER 变量",
     r"\1/\2 branch wave speeds taken from $PARAMETER variables"),
    (r"未发现分布参数支路，无需适配",
     r"No distributed-parameter branches found; no adaptation needed"),
    (r"\[ATP\] dT 自适应生效（(\S+)）：(\S+) s → (\S+) s（最短支路行程 ([\d.]+) ns）",
     r"[ATP] dT adaptation applied (\1): \2 s → \3 s (shortest branch travel \4 ns)"),
    (r"\[ATP\] dT 自适应（(\S+)）：(.+)",
     r"[ATP] dT adaptation (\1): \2"),
    (r"\[ATP\] 输入文件已写入：(\S+)",
     r"[ATP] Input file written: \1"),
    (r"\[ATP\] 资产文件已物化到引擎目录 (\S+)，work\.atp 渲染版已覆盖",
     r"[ATP] Asset files materialized to engine directory \1; rendered work.atp overwritten"),
    (r"\[ATP\] startup 已复制到引擎目录 (\S+)",
     r"[ATP] startup copied to engine directory \1"),
    (r"\[ATP\] 自动选资产：电压=(\S+) 塔型=(\S+) 场景=(\S+) 避雷器=(\S+)\(来源=(\S+),命中=(\S+)\) → asset=(\S+) \((\S+)\)",
     _auto_asset_replacement),
    (r"\[ATP\] 开始执行外部波形分析：job=(\S+), 杆塔=(\S+)\((\S+)\), 模型=(\S+), 适配器=(\S+)",
     r"[ATP] Starting external waveform analysis: job=\1, tower=\2(\3), model=\4, adapter=\5"),
    (r"\[ATP\]\[STDOUT\] 执行命令：(.+?)，工作目录：(\S+)",
     r"[ATP][STDOUT] Executing command: \1, working directory: \2"),
    (r"\[ATP\] 执行命令：(.+?)，工作目录：(\S+)",
     r"[ATP] Executing command: \1, working directory: \2"),
    (r"\[ATP\] 执行完成：(\S+)，退出码=(-?\d+)",
     r"[ATP] Execution complete: \1, exit code=\2"),
    (r"\[ATP\]\[TIMEOUT\] 杆塔 (\S+) 超时，超时时间=(\d+)s",
     r"[ATP][TIMEOUT] Tower \1 timed out, timeout=\2s"),
    (r"\[ATP\] 执行超时：(\S+)，超时时间=(\d+)s",
     r"[ATP] Execution timeout: \1, timeout=\2s"),
    (r"\[ATP\]\[ERROR\] 杆塔 (\S+) 启动失败: (.+)",
     r"[ATP][ERROR] Tower \1 failed to start: \2"),
    (r"\[ATP\] 启动失败：(\S+)，错误=(.+)",
     r"[ATP] Failed to start: \1, error=\2"),
    (r"\[ATP\] 执行失败：(\S+)，退出码=(-?\d+)，stderr=(.+)",
     r"[ATP] Execution failed: \1, exit code=\2, stderr=\3"),
    (r"\[ATP\] 开始解析结果：(\S+)，资产无结果契约，使用 lis 闪络检测",
     r"[ATP] Parsing result for \1: asset has no result contract; using lis flashover detection"),
    (r"\[ATP\] 开始解析结果：(\S+)，结果文件=(\S+)",
     r"[ATP] Parsing result for \1: result file=\2"),
    (r"\[ATP\] 结果解析完成：(\S+)，payload_keys=(.+)",
     r"[ATP] Result parsing complete: \1, payload_keys=\2"),
    (r"\[ATP\] lis 闪络检测（Close switch）：(\S+)，闪络相数=(\d+)，相=(\S+)",
     r"[ATP] lis flashover detection (Close switch): \1, flashover phase count=\2, phases=\3"),
    (r"\[ATP\] lis 闪络检测失败（(\S+)）：(.+)",
     r"[ATP] lis flashover detection failed (\1): \2"),
    (r"\[ATP\] pl4 闪络检测（回退）：(\S+)，闪络相数=(\d+)",
     r"[ATP] pl4 flashover detection (fallback): \1, flashover phase count=\2"),
    (r"\[ATP\] pl4 闪络检测失败（(\S+)）：(.+)",
     r"[ATP] pl4 flashover detection failed (\1): \2"),
    (r"\[ATP\] 线路模型已重生成：(\S+)\.lib（几何改写 \+ LCC）",
     r"[ATP] Line model regenerated: \1.lib (geometry rewrite + LCC)"),
    (r"\[ATP\] 线路模型重生成完成：(.+)",
     r"[ATP] Line model regeneration complete: \1"),
    (r"\[ATP\] 物化文件失败 (\S+)：(.+)",
     r"[ATP] Failed to materialize file \1: \2"),
    # 引擎心跳 / EGM 绕击跳闸率（LP-148）
    (r"\[ENGINE\]\[HEARTBEAT\] 运行中：(.+?)，已耗时 (\d+)s，超时上限 (\d+)s",
     r"[ENGINE][HEARTBEAT] Running: \1, elapsed \2s, timeout limit \3s"),
    (r"\[ENGINE\] 运行心跳：(.+?)，已耗时 (\d+)s，超时上限 (\d+)s",
     r"[ENGINE] Heartbeat: \1, elapsed \2s, timeout limit \3s"),
    (r"\[EGM\] 绕击跳闸率（(\S+) 引擎）：egm(\d+) 电压=(\S+) 回路数=(\d+) Ng=(\S+) Ic=(\S+) 合计=([\d.]+) ÷(\d+) = ([\d.]+)",
     r"[EGM] Shielding trip rate (\1 engine): egm\2 voltage=\3 circuits=\4 Ng=\5 Ic=\6 total=\7 ÷\8 = \9"),
]

_COMPILED_LOG_RULES: list[tuple[re.Pattern[str], str | Callable[..., str]]] = [
    (re.compile(pattern), replacement) for pattern, replacement in _LOG_RULES
]

# ───────────────────────── 2) 完整短语（step 文案 / 报告标题 / 状态） ─────────────────────────
PHRASE_EN: dict[str, str] = {
    # 故障判别 WS step 阶段文案（fault_diagnosis_service.py / tasks）
    "开始收集输入": "Collecting inputs",
    "准备输入文件": "Preparing input files",
    "输入收集完成，正在分析": "Inputs collected, analyzing",
    "行波分析完成": "Traveling-wave analysis complete",
    "综合判别完成，正在生成结果": "Diagnosis complete, generating results",
    "结果回填完成": "Results written back",
    "生成Word报告": "Generating Word report",
    # Word 报告标题 / 章节
    "输电线路故障综合判别报告": "Transmission Line Fault Diagnosis Report",
    "输电线路故障综合判别系统｜正式报告": "Transmission Line Fault Diagnosis System | Official Report",
    "报告总览": "Report Overview",
    "接地故障及过渡电阻判别": "Ground Fault and Transition Resistance Diagnosis",
    "故障定位": "Fault Location",
    "耐雷水平与雷击原因分析": "Lightning Withstand Level and Cause Analysis",
    "分布式行波分析与故障原因融合": "Distributed Traveling-Wave Analysis and Cause Fusion",
    "总体状态与后续意见": "Overall Status and Recommendations",
    "输入信息汇总": "Input Information Summary",
    "录波故障信息": "Recorded Fault Information",
    "雷电流及定位信息": "Lightning Current and Location Information",
    "线路台账匹配信息": "Line Ledger Matching Information",
    "行波与光学监测信息": "Traveling-Wave and Optical Monitoring Information",
    "故障分析": "Fault Analysis",
    "生成时间：": "Generated at: ",
    "第一轮前半部分审阅稿": "First-round partial review draft",
    "故障综合判别系统": "Fault Diagnosis System",
}

# ───────────────────────── 3) 通用中文片段（兜底，按长度降序替换） ─────────────────────────
# 覆盖散落的 26+ 处硬编码中文日志：把常见中文词/短语换成英文，未命中部分回落中文。
_SEGMENT_PAIRS: dict[str, str] = {
    "异常堆栈": "Traceback",
    "任务已被取消": "Task cancelled",
    "取消状态写入失败（交由清理任务兜底）": "Failed to write cancelled state (cleanup task will handle)",
    "取消状态兜底写入失败": "Failed to write fallback cancelled state",
    "取消状态兜底写入仍被锁阻塞，放弃": "Fallback cancelled-state write still blocked by lock, giving up",
    "取消清理任务派发失败": "Failed to dispatch cancellation cleanup task",
    "写任务 PID 文件失败": "Failed to write task PID file",
    "任务启动": "task started",
    "任务执行失败": "Task failed",
    "绘图任务执行失败": "Plotting task failed",
    "导入失败": "Import failed",
    "回填失败": "Backfill failed",
    "计算失败": "Calculation failed",
    "解析失败": "Parsing failed",
    "上传失败": "Upload failed",
    "生成失败": "Generation failed",
    "开始执行回填计算": "Starting backfill calculation",
    "开始执行地闪密度回填计算": "Starting ground-flash density backfill calculation",
    "开始提取波形特征参数": "Extracting waveform features",
    "开始回写特征数据到数据库": "Writing feature data back to database",
    "开始构建时间轴": "Building time axis",
    "开始解析电流序列": "Parsing current sequence",
    "开始导入雷电流幅值": "Importing lightning current amplitude",
    "开始线路雷电流幅值回填": "Starting line lightning-current amplitude backfill",
    "开始线路地闪密度回填": "Starting line ground-flash density backfill",
    "开始渲染地闪密度图": "Rendering ground-flash density map",
    "开始上传到对象存储": "uploading to object storage",
    "开始处理杆塔": "Processing tower",
    "解析校验通过": "Parse validation passed",
    "解析完成": "Parsing complete",
    "解析警告": "Parse warning",
    "时间轴警告": "Time-axis warning",
    "回填警告": "Backfill warning",
    "回填参数": "Backfill params",
    "回填任务记录已更新为 processing": "Backfill task record updated to processing",
    "采样点数量": "samples",
    "采样点数": "samples",
    "采样间隔": "sample interval",
    "采样频率": "sample rate",
    "文本行数": "text lines",
    "字节数": "bytes",
    "源文件对象键": "Source object key",
    "文件名": "file name",
    "线路杆塔数": "Tower count on line",
    "自动生成事件编号": "Auto-generated event id",
    "源文件中未解析到有效落雷数据": "No valid lightning strike data parsed from source file",
    "Voronoi 分区计算失败": "Voronoi partition calculation failed",
    "密度图渲染": "density map rendering",
    "密度图": "density map",
    "对象存储": "object storage",
    "数据库连接已失效": "DB connection lost",
    "重建连接后继续": "reconnected and continuing",
    "换新会话重试": "retrying with a new session",
    "回退默认模板": "falling back to default template",
    "保留原值": "keeping previous value",
    "风险等级重算失败": "Risk grade recalculation failed",
    "塔进度事件推送失败": "Failed to push tower progress event",
    "塔日志流推送失败": "Failed to push tower log stream",
    "塔内进度落库失败": "Failed to persist intra-tower progress",
    "塔内进度事件推送失败": "Failed to push intra-tower progress event",
    "进度上报失败": "Failed to report progress",
    "任务全部塔计算失败": "All tower calculations failed",
    "标记 failed": "marking failed",
    "结果数": "results",
    "运行结果目录": "run result directory",
    "已清理任务": "Cleaned up task",
    "清理任务": "Cleaning up task",
    "跳过队列中的残留消息": "skipping queued residual messages",
    "单塔独立，任务继续": "per-tower isolated, task continues",
    "按塔型解析模板失败": "Failed to resolve template by tower type",
    "几何未变": "geometry unchanged",
    "写回缓存": "writing back cached",
    "跳过 LCC": "skipping LCC",
    "线路模型已重生成": "Line model regenerated",
    "线路模型重生成完成": "Line model regeneration complete",
    "引擎文件复制失败": "Failed to copy engine file",
    "无 .dat（几何内嵌模板），跳过 .dat 改写与 LCC 重生成": "No .dat (geometry embedded in template); skipping .dat rewrite and LCC regeneration",
    "导入预处理": "import preprocessing",
    "删除 $PARAMETER 变量替换段": "removed $PARAMETER substitution block",
    "保留非 $$ 参数": "kept non-$$ parameters",
    "已发布模型": "published model",
    "文件变更": "file changes",
    "派生变更版本": "derived change version",
    "已丢弃": "discarded",
    "覆盖上传完成": "overwrite upload complete",
    "清理旧文件": "removed old files",
    "测试结论已重置": "test result reset",
    "资产分析任务入队失败": "Failed to enqueue asset analysis task",
    "资产分析异常": "Asset analysis error",
    "已通过的提示项": "Passed checks",
    "修复：": "Fix: ",
    "不可用，跳过": "unavailable, skipping",
    "不可用，无法": "unavailable, cannot",
    "未找到": "not found",
    "无带经纬度杆塔，无法绘图": "no towers with coordinates; cannot plot",
    "已上传": "uploaded",
    "已更新为": "updated to",
    "已取消": "cancelled",
    "已完成": "complete",
    "正在生成结果": "generating results",
    "正在分析": "analyzing",
    "生成结果": "generating results",
    "生成Word报告": "Generating Word report",
    "开始": "Start",
    "完成": "Complete",
    "失败": "Failed",
    "跳过": "Skip",
    "重试": "Retry",
    "任务": "Task",
    "杆塔": "Tower",
    "线路": "Line",
    "导入": "Import",
    "导出": "Export",
    "解析": "Parse",
    "上传": "Upload",
    "读取": "Read",
    "渲染": "Render",
    "回填": "Backfill",
    "警告": "Warning",
    "异常": "Error",
    "成功": "Success",
    "终止任务": "Aborting task",
    # ATP 渲染/执行片段兜底（LP-148）：命中规则后仍有残留中文时按片段替换
    "模板渲染完成": "Template render complete",
    "输入文件大小": "input file size",
    "代码版本": "code version",
    "几何覆写": "geometry override",
    "覆写项": "override items",
    "数值参数覆写": "Numeric parameter override",
    "耦合系数槽位": "Coupling coefficient slot",
    "电角度已按 C# 规则改写": "electrical angle rewritten per C# rules",
    "电角度": "electrical angle",
    "dT 自适应生效": "dT adaptation applied",
    "dT 自适应": "dT adaptation",
    "最短支路行程": "shortest branch travel",
    "支路波速取自": "branch wave speeds taken from",
    "无需适配": "no adaptation needed",
    "分布参数支路": "distributed-parameter branches",
    "输入文件已写入": "Input file written",
    "资产文件已物化到引擎目录": "Asset files materialized to engine directory",
    "渲染版已覆盖": "rendered version overwritten",
    "已复制到引擎目录": "copied to engine directory",
    "自动选资产": "Auto-selected asset",
    "开始执行外部波形分析": "Starting external waveform analysis",
    "工作目录": "working directory",
    "执行命令": "Executing command",
    "执行完成": "Execution complete",
    "执行超时": "Execution timeout",
    "超时时间": "timeout",
    "启动失败": "failed to start",
    "执行失败": "Execution failed",
    "退出码": "exit code",
    "开始解析结果": "Parsing result",
    "资产无结果契约": "asset has no result contract",
    "使用 lis 闪络检测": "using lis flashover detection",
    "结果解析完成": "Result parsing complete",
    "闪络相数": "flashover phase count",
    "闪络检测": "flashover detection",
    "几何改写": "geometry rewrite",
    "线路模型重生成完成": "Line model regeneration complete",
    "物化文件失败": "Failed to materialize file",
    "运行心跳": "Heartbeat",
    "运行中": "Running",
    "已耗时": "elapsed",
    "超时上限": "timeout limit",
    "绕击跳闸率": "Shielding trip rate",
    "回路数": "circuits",
    "合计": "total",
    "已写入": "written",
    "未找到槽位": "slot not found",
    "仿真": "simulation",
    "（": " (",
    "）": ")",
}
# 合并完整短语映射，按 key 长度降序：长短语先命中，避免「开始收集输入」
# 被「开始」切成「Start收集输入」这类半吊子结果。
_SEGMENTS: list[tuple[str, str]] = sorted(
    list(_SEGMENT_PAIRS.items()) + list(PHRASE_EN.items()),
    key=lambda kv: -len(kv[0]),
)


def _replace_segments(text: str) -> str:
    for zh, en in _SEGMENTS:
        if zh in text:
            text = text.replace(zh, en)
    return text


# ───────────────────────── 4) HTTPException detail / warning 提示文案 ─────────────────────────
# 与前端 EN_DICT / BACKEND_DETAIL_EN 对齐；英文请求下由 HTTPException 处理器 / 提示点
# 调用 localize_backend_text 翻译。zh 请求逐字返回原文。
PROMPT_EN: dict[str, str] = {
    # 高程回填警告（前端词典未登记，LP-148 补入）
    "栅格缺少 CRS 定义，默认按 WGS84 经度/纬度采样": "Raster has no CRS definition; sampling by WGS84 longitude/latitude by default",
    "栅格 CRS 无法识别，默认按 WGS84 经度/纬度采样，建议先校验源数据": "Raster CRS unrecognized; sampling by WGS84 longitude/latitude by default; validate source data first",
    "未提取到有效地形网格（可能为 nodata 或投影定义不匹配）": "No valid terrain grid extracted (possibly nodata or projection mismatch)",
    "未识别到故障字段：请使用「下载模板」的格式（录波记录厂站/故障时刻/故障线路名称等表头）或上传录波故障报告 PDF": "Fault field not recognized: use the \\\"Download Template\\\" format (headers such as fault recorder station/fault time/fault line name) or upload the fault recorder fault report PDF",
    "当前服务未启用 rasterio 栅格能力，请联系管理员重建 API 镜像后重试 IMG/TIF 分析与回填": "The service does not have rasterio support enabled; please contact the administrator to rebuild the API image and retry IMG/TIF analysis and refill",
    "普通计算和同跳计算仅支持 placeholder/atp/wine/legacy_atp 适配器": "Normal and same-strike calculation only support the placeholder/atp/wine/legacy_atp adapters",
    "手工 base_tower/profile 已不再支持：几何与工况输入统一由测试线路快照提供。": "Manual base_tower/profile is no longer supported: geometry and operating-condition inputs are provided uniformly by the test-line snapshot.",
    "资产目录里没有 .atp / .dat / .pch 文件，无法判定形态；请先上传模型文件": "The asset directory has no .atp/.dat/.pch files; unable to determine the format. Please upload model files first",
    "params_source=tower 已不再支持：几何与工况输入统一由测试线路快照提供": "params_source=tower is no longer supported: geometry and operating-condition inputs are provided uniformly by the test-line snapshot.",
    "line_tower_id 已不再支持：测试参数统一从「测试线路（单塔基准）」装配。": "line_tower_id is no longer supported: test parameters are assembled uniformly from \\\"Test line (single-tower baseline)\\\".",
    "读取 XLSX 需要 openpyxl；请使用项目的 Python 运行环境": "Reading XLSX requires openpyxl; please use the project's Python runtime",
    "图片格式不支持，仅支持 jpg/jpeg/png/webp/gif/bmp": "Unsupported image format; only jpg/jpeg/png/webp/gif/bmp are supported",
    "暂不支持该格式，录波数据支持 pdf/txt/csv/json/xlsx": "This format is not supported yet; waveform data supports pdf/txt/csv/json/xlsx",
    "该运行没有 work.pl4(波形未生成,可能 ATP 未跑出结果)": "This run has no work.pl4 (waveform not generated; ATP may not have produced results)",
    "资产目录不存在（尚未上传模型文件），无法分析模型；请先上传模型文件": "The asset directory does not exist (model files not uploaded yet); unable to analyze the model. Please upload model files first",
    "雷电 CSV 未识别到可推断的时间列，统计年限按固定 6 年计算": "No usable time column in the lightning CSV; data years fall back to a fixed 6 years",
    "未找到可用于线路雷电流拟合的幅值记录（请先导入并等待处理完成）": "No amplitude records found for line lightning-current fitting (import first and wait for processing to complete)",
    "未找到可用于地闪密度计算的地闪分布数据（请先导入并关联线路）": "No ground-flash distribution data found for ground-flash density calculation (import and link a line first)",
    "缺少文件，请提供 files 或 temp_file_id": "Missing files; please provide files or temp_file_id",
    "XLSX 文件解析失败，请确认为有效的 Excel 文件": "Failed to parse the XLSX file; please confirm it is a valid Excel file",
    "缺少文件，请提供 file 或 temp_file_id": "Missing file; please provide file or temp_file_id",
    "资产目录下未找到 .atp 入口文件，无法扫描槽位": "No .atp entry file found in the asset directory; unable to scan slots",
    "上传的 LP_Setting 未解析到杆塔模型清单": "The uploaded LP_Setting did not parse to a tower-model list",
    "前驱风险任务结果已失效，请重新生成措施推荐任务": "The prerequisite risk task's results have expired; please regenerate the mitigation-recommendation task",
    "地形瓦片自动构建已下线，不再接受新的构建任务。": "Automatic terrain tile building has been retired and no longer accepts new build tasks.",
    "前驱任务必须为普通计算/同跳/风险评估任务": "The prerequisite task must be a normal-calculation, same-strike, or risk-assessment task",
    "记录缺少 MinIO 源文件引用，无法重试": "The record lacks a MinIO source-file reference; unable to retry",
    "加载录波 PDF 提取器失败，请联系管理员": "Failed to load the waveform-PDF extractor; please contact the administrator",
    "措施推荐任务缺少关联风险任务，无法生成报告": "The mitigation-recommendation task lacks a linked risk task; unable to generate a report",
    "录波 PDF 提取器不存在，请联系管理员": "The waveform-PDF extractor does not exist; please contact the administrator",
    "报告任务的风险结果已失效，请重新生成任务": "The report task's risk results have expired; please regenerate the task",
    "该运行没有产物包（可能仍在执行或已清理）": "This run has no artifact package (it may still be running or was cleaned up)",
    "报告任务的杆塔范围已失效，请重新生成任务": "The report task's tower range has expired; please regenerate the task",
    "当前线路缺少杆塔经纬度，无法计算地闪密度": "The current line lacks tower coordinates; unable to calculate ground-flash density",
    "没有可执行的用例（全部被禁用或未勾选）": "No executable cases (all are disabled or unchecked)",
    "必须提供 file_record_id": "file_record_id is required",
    "未找到可用于地闪密度计算的雷击分布数据": "No lightning-strike distribution data found for ground-flash density calculation",
    "加装避雷器复算任务至少需要选择一座杆塔": "The arrester-adding recompute task requires selecting at least one tower",
    "仅普通计算或同跳计算任务可作为复算基线": "Only normal-calculation or same-strike tasks can be a recomputation baseline",
    "措施推荐任务至少需要选择一座高风险杆塔": "The mitigation-recommendation task requires selecting at least one high-risk tower",
    "未找到可用于线路雷电流拟合的幅值样本": "No amplitude samples found for line lightning-current fitting",
    "保留天数为 0（永久保留），跳过清理": "Retention days is 0 (keep forever); skipping cleanup",
    "该线路在此幅值下没有可展示的回填明细": "The line has no displayable refill details at this amplitude",
    "该运行还没有对比产物（可能仍在执行）": "This run has no comparison artifacts yet (it may still be running)",
    "加装避雷器复算任务缺少复用的计算任务": "The arrester-adding recompute task lacks a reused calculation task",
    "前驱措施任务没有可复算的中高风险杆塔": "The prerequisite mitigation task has no medium/high-risk towers to recompute",
    "LP_Setting 文件名不能为空": "LP_Setting filename cannot be empty",
    "地形 layer.json 解析失败": "Failed to parse terrain layer.json",
    "加装避雷器复算任务包含无效的杆塔选择": "The arrester-adding recompute task contains an invalid tower selection",
    "关联措施任务不属于当前风险评估任务": "The linked mitigation task does not belong to the current risk-assessment task",
    "仅风险评估或措施推荐任务可生成报告": "Only risk-assessment or mitigation-recommendation tasks can generate a report",
    "地形 layer.json 不存在": "Terrain layer.json does not exist",
    "加装避雷器复算任务缺少前驱措施任务": "The arrester-adding recompute task lacks a prerequisite mitigation task",
    "LP_GanTa 文件名不能为空": "LP_GanTa filename cannot be empty",
    "仅措施推荐任务可作为报告关联任务": "Only mitigation-recommendation tasks can be a report's linked task",
    "报告任务缺少来源结果或选塔范围": "The report task lacks a source result or tower-selection range",
    "ZIP 包必须是 zip 格式": "The archive must be a .zip file",
    "措施推荐任务包含无效的杆塔选择": "The mitigation-recommendation task contains an invalid tower selection",
    "存在无效用例（资产已被删除）：": "There are invalid cases (the asset was deleted): ",
    "模型尚未扫描槽位，请先执行扫描": "The model has not had its slots scanned yet; run the scan first",
    "任务已在排队或执行中，无法删除": "The task is queued or running and cannot be deleted",
    "分析任务已存在，无需重复提交。": "The analysis task already exists; no need to resubmit.",
    "测试集还没有用例，请先添加用例": "The test set has no cases yet; add cases first",
    "当前文件格式不支持地形瓦片生成": "The current file format does not support terrain tile generation",
    "老系统配置未解析到杆塔模型清单": "The legacy-system config did not parse to a tower-model list",
    "复算杆塔不在所选基线计算结果中": "The recomputed tower is not in the selected baseline calculation results",
    "前驱风险任务暂无可复用杆塔结果": "The prerequisite risk task has no reusable tower results yet",
    "报告来源任务暂无可复用杆塔结果": "The report source task has no reusable tower results yet",
    "前驱风险任务与当前线路不匹配": "The prerequisite risk task does not match the current line",
    "复用计算任务与当前线路不匹配": "The reused calculation task does not match the current line",
    "关联措施任务与当前线路不匹配": "The linked mitigation task does not match the current line",
    "关联风险任务与当前线路不匹配": "The linked risk task does not match the current line",
    "前驱措施任务与当前线路不匹配": "The prerequisite mitigation task does not match the current line",
    "措施推荐任务缺少前驱风险任务": "The mitigation-recommendation task lacks a prerequisite risk task",
    "当前线路没有可回填的杆塔数据": "The current line has no towers available for refill",
    "报告来源任务与当前线路不匹配": "The report source task does not match the current line",
    "前驱措施任务缺少关联风险任务": "The prerequisite mitigation task lacks a linked risk task",
    "当前线路没有可分析的杆塔数据": "The current line has no analyzable tower data",
    "老系统 CSV 编码无法识别": "The legacy-system CSV encoding cannot be recognized",
    "报告任务至少需要选择一座杆塔": "The report task requires selecting at least one tower",
    "JSON 顶层应为对象或数组": "The top-level JSON must be an object or array",
    "work.pl4 无数据点": "work.pl4 has no data points",
    "关联复算任务缺少可复用结果": "The linked recomputation task lacks reusable results",
    "报告来源任务缺少可复用结果": "The report source task lacks reusable results",
    "ZIP 包中没有可导入文件": "No importable files in the ZIP package",
    "复用计算任务缺少可复用结果": "The reused calculation task lacks reusable results",
    "分析任务已提交，等待执行。": "The analysis task was submitted and is awaiting execution.",
    "前驱风险任务缺少可复用结果": "The prerequisite risk task lacks reusable results",
    "图片包必须是 zip 格式": "The image package must be a zip",
    "前驱任务必须为措施推荐任务": "The prerequisite task must be a mitigation-recommendation task",
    "报告任务请使用报告下载入口": "For report tasks please use the report download entry",
    "文件中未解析到有效数值序列": "No valid numeric sequence parsed from the file",
    "报告任务包含无效的杆塔选择": "The report task contains an invalid tower selection",
    "关联风险任务缺少可复用结果": "The linked risk task lacks reusable results",
    "前驱措施任务缺少可复用结果": "The prerequisite mitigation task lacks reusable results",
    "work.pl4 步长异常": "work.pl4 has an abnormal step size",
    "关联措施任务缺少可复用结果": "The linked mitigation task lacks reusable results",
    "报告来源任务尚未成功完成": "The report source task has not completed successfully",
    "文件记录分析任务保存失败": "Failed to save the file-record analysis task",
    "复用计算任务尚未成功完成": "The reused calculation task has not completed successfully",
    "前驱措施任务尚未成功完成": "The prerequisite mitigation task has not completed successfully",
    "关联风险任务尚未成功完成": "The linked risk task has not completed successfully",
    "当前任务暂无可导出的结果": "The current task has no exportable results yet",
    "仅已完成分布的线路可绘图": "Only lines with a completed distribution can be plotted",
    "关联措施任务尚未成功完成": "The linked mitigation task has not completed successfully",
    "前驱风险任务尚未成功完成": "The prerequisite risk task has not completed successfully",
    "当前未配置可用文件挂载点": "No usable file mount is configured",
    "报告任务缺少风险评估来源": "The report task lacks a risk-assessment source",
    "仅报告任务支持文档下载": "Only report tasks support document download",
    "创建故障分析记录失败": "Failed to create the fault-analysis record",
    "测试集执行记录不存在": "Test-set execution record does not exist",
    "创建防雷分析任务失败": "Failed to create the lightning-protection analysis task",
    "测试运行记录保存失败": "Failed to save the test run record",
    "任务已在排队或执行中": "The task is already queued or running",
    "上传包内没有有效文件": "No valid files in the upload package",
    "雷电流幅值记录不存在": "Lightning-current amplitude record does not exist",
    "报告任务缺少来源任务": "The report task lacks a source task",
    "更新故障分析记录失败": "Failed to update the fault-analysis record",
    "文件已上传并创建记录": "File uploaded and record created",
    "报告任务尚未成功完成": "The report task has not completed successfully",
    "导入文件没有数据行": "The imported file has no data rows",
    "前驱措施任务不存在": "The prerequisite mitigation task does not exist",
    "复用计算任务不存在": "The reused calculation task does not exist",
    "前驱风险任务不存在": "The prerequisite risk task does not exist",
    "故障分析记录不存在": "Fault-analysis record does not exist",
    "图片压缩包格式非法": "Invalid image archive format",
    "所选故障线路不存在": "The selected fault line does not exist",
    "地闪分布记录不存在": "Ground-flash distribution record does not exist",
    "高程文件记录不存在": "Elevation file record does not exist",
    "关联措施任务不存在": "The linked mitigation task does not exist",
    "测试运行记录不存在": "Test run record does not exist",
    "防雷分析任务不存在": "Lightning-protection analysis task does not exist",
    "高程文件记录未启用": "The elevation file record is not enabled",
    "报告来源任务不存在": "The report source task does not exist",
    "ZIP 包不能为空": "The ZIP package cannot be empty",
    "雷电流幅值样本为空": "Lightning-current amplitude sample is empty",
    "ATP 资产不存在": "ATP asset not found",
    "任务派发后查询失败": "Post-dispatch task query failed",
    "关联风险任务不存在": "The linked risk task does not exist",
    "文件编码不受支持": "The file encoding is unsupported",
    "文件记录创建失败": "Failed to create the file record",
    "保存图片关联失败": "Failed to save the image association",
    "不支持的回填模式": "Unsupported refill mode",
    "无可用文件挂载点": "No usable file mount",
    "地形瓦片尚未就绪": "Terrain tile is not ready yet",
    "地形瓦片不存在": "Terrain tile does not exist",
    "任务产物不存在": "Task artifact does not exist",
    "文件记录未启用": "The file record is not enabled",
    "文件名不能为空": "Filename cannot be empty",
    "测试线路不存在": "Test line does not exist",
    "测试用例不存在": "Test case does not exist",
    "参数模板不存在": "Parameter template does not exist",
    "文件记录不存在": "File record does not exist",
    "杆塔模型不存在": "Tower model does not exist",
    "回填任务不存在": "Refill task does not exist",
    "上传文件为空": "Uploaded file is empty",
    "任务派发失败": "Task dispatch failed",
    "密度图不存在": "Density map does not exist",
    "测试集不存在": "Test set does not exist",
    "导入文件为空": "The imported file is empty",
    "创建任务失败": "Failed to create task",
    "上传图片为空": "Uploaded image is empty",
    "任务不存在": "Task does not exist",
    "线路不存在": "Line does not exist",
}

# 动态提示（数值 / 异常 / 文件名带入）：正则 + 反向引用保留动态值。
_PROMPT_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"CSV 线路编号 (\S+) 与当前线路编码 (\S+) 不一致，已保留当前线路编码"),
     r"CSV line code \1 differs from current line code \2; kept the current line code"),
    (re.compile(r"(\d+) 座杆塔缺少经纬度，未能回填地闪密度"),
     r"\1 towers lack coordinates; ground-flash density not backfilled"),
    (re.compile(r"事件编号已存在：(\S+)"), r"Event id already exists: \1"),
    (re.compile(r"任务当前状态为 (\S+)，已结束无法取消"), r"Task status is \1; already finished and cannot be cancelled"),
    (re.compile(r"任务派发失败:\s*(.+)"), r"Failed to dispatch task: \1"),
    (re.compile(r"文件「(.+?)」为空，无有效数据行"), r'File "\1" is empty; no valid data rows'),
    (re.compile(r"无效的 (start_date|end_date)：(\S+)，请使用 YYYY-MM-DD"),
     r"Invalid \1: \2; use YYYY-MM-DD"),
    (re.compile(r"时间列非严格递增，已改用固定采样间隔重建时间轴"),
     r"Time column is not strictly increasing; rebuilt time axis with fixed sampling interval"),
    (re.compile(r"未找到「序号/塔号」表头，已按固定列序（1-63 列）解析"),
     r'Header "Seq/Tower No." not found; parsed with fixed column order (columns 1-63)'),
    (re.compile(r"未提供采样间隔，默认按 1\.0us 计算"),
     r"Sampling interval not provided; defaulting to 1.0us"),
    (re.compile(r"样本分布不足以插值求解 a，已回退到中位数"),
     r"Sample distribution insufficient to interpolate a; fell back to median"),
    (re.compile(r"样本分布不足以稳定拟合 b，已使用默认 b=2\.6"),
     r"Sample distribution insufficient to fit b reliably; using default b=2.6"),
    (re.compile(r"样本拟合得到的 a 非法，已回退到中位数"),
     r"Fitted a is invalid; fell back to median"),
    (re.compile(r"样本概率分布异常，已回退到中位数"),
     r"Abnormal sample probability distribution; fell back to median"),
    (re.compile(r"检测到部分行存在时间列但并不完整，已统一按采样间隔重建时间轴"),
     r"Some rows have a time column but incomplete; rebuilt time axis uniformly by sampling interval"),
    (re.compile(r"第 (\d+) 行未识别为数值，已跳过"), r"Line \1: unrecognized numeric value; skipped"),
    (re.compile(r"第 (\d+) 行序号/塔号映射冲突，已跳过"), r"Row \1: seq/tower no. mapping conflict; skipped"),
    (re.compile(r"第 (\d+) 行缺少有效的序号/塔号，已跳过"), r"Row \1: missing valid seq/tower no.; skipped"),
    (re.compile(r"线路参数准备未完成：(.+?)。请先完成相关回填后再创建任务。"),
     r"Line parameters not ready: \1. Complete the relevant backfill before creating a task."),
    (re.compile(r"解析幅值源文件失败（(.+?)）：(.+)"), r"Failed to parse amplitude source file (\1): \2"),
    (re.compile(r"读取幅值源文件失败（(.+?)）：(.+)"), r"Failed to read amplitude source file (\1): \2"),
    (re.compile(r"采样间隔必须大于 0，已回退到 1\.0us"),
     r"Sampling interval must be > 0; reverted to 1.0us"),
    # 高程 / 文件回填（LP-148 验收 #3）
    (re.compile(r"读取上传文件失败：(.+)"), r"Failed to read uploaded file: \1"),
    (re.compile(r"上传文件为空：(.+)"), r"Uploaded file is empty: \1"),
    (re.compile(r"不支持的高程文件类型:\s*(\S+)，仅支持 \.tif/\.tiff"),
     r"Unsupported elevation file type: \1; only .tif/.tiff are supported"),
    (re.compile(r"当前文件不是栅格高程文件:\s*(.+)"), r"Current file is not a raster elevation file: \1"),
    (re.compile(r"高程数据文件不存在:\s*(.+)"), r"Elevation data file does not exist: \1"),
    (re.compile(r"高程栅格文件解析失败:\s*(.+)"), r"Failed to parse elevation raster file: \1"),
    (re.compile(r"文件不存在:\s*(.+)"), r"File does not exist: \1"),
    (re.compile(r"栅格 CRS 为 (\S+?)，数据集边界框基于该投影坐标，预览渲染会自动转换到 WGS84 经度/纬度"),
     r"Raster CRS is \1; dataset bounds are in that projected coordinate; preview converts to WGS84 longitude/latitude"),
]


def _translate_prompts(text: str) -> str:
    if not _HAS_ZH.search(text):
        return text
    stripped = text.strip()
    if stripped in PROMPT_EN:
        return PROMPT_EN[stripped]
    for pattern, replacement in _PROMPT_RULES:
        translated = pattern.sub(replacement, text, count=1)
        if translated != text:
            return translated
    return text


def localize_backend_text(text: str | None) -> str:
    """按当前后端语言翻译提示文案（HTTPException detail / warning 等）。

    ``zh``（或拿不到语言）逐字返回原文；``en`` 走 PROMPT_EN / _PROMPT_RULES /
    通用片段兜底，未命中保留中文。
    """
    if not text:
        return text or ""
    from .backend_lang import current_backend_lang

    return translate_backend_text(text, current_backend_lang())


def _should_skip_line(line: str) -> bool:
    """ATP 引擎原始输出 / traceback 帧原样保留。"""
    return bool(_SKIP_LINE.match(line))


def translate_log_line(line: str, lang: str) -> str:
    """翻译单行日志；``zh`` 或不含中文 / 原始输出时逐字返回。"""
    if lang != "en" or not line or not _HAS_ZH.search(line):
        return line
    if _should_skip_line(line):
        return line
    translated = line
    for pattern, replacement in _COMPILED_LOG_RULES:
        translated = pattern.sub(replacement, translated, count=1)
    if _HAS_ZH.search(translated):
        translated = _translate_prompts(translated)
    if _HAS_ZH.search(translated):
        translated = _replace_segments(translated)
    return translated


def translate_log_lines(lines: Iterable[str], lang: str) -> list[str]:
    """批量翻译；``zh`` 时返回与输入逐字相同的列表。"""
    if lang != "en":
        return list(lines)
    return [translate_log_line(line, lang) for line in lines]


def translate_backend_text(text: str | None, lang: str) -> str:
    """翻译阶段文案 / 报告文本等纯文本；未命中回落中文。"""
    if not text or lang != "en" or not _HAS_ZH.search(text):
        return text or ""
    stripped = text.strip()
    if stripped in PHRASE_EN:
        return PHRASE_EN[stripped]
    text = _translate_prompts(text)
    return _replace_segments(text)


def translate_report_docx(path: str | Path, lang: str) -> None:
    """把已生成的 Word 报告按语言翻译（逐段 + 表格单元格），原地覆盖保存。

    报告正文由大量领域句子拼成，完整模板化属于第二阶段；这里对标题 / 标签 /
    常见短语做映射，未命中片段回落中文，保证不出现空洞。
    """
    if lang != "en":
        return
    from docx import Document

    doc = Document(str(path))

    def _translate_paragraph(paragraph) -> None:  # noqa: ANN001
        if not paragraph.runs:
            return
        original = "".join(run.text for run in paragraph.runs)
        translated = translate_backend_text(original, lang)
        if translated == original:
            return
        paragraph.runs[0].text = translated
        for run in paragraph.runs[1:]:
            run.text = ""

    for paragraph in doc.paragraphs:
        _translate_paragraph(paragraph)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    _translate_paragraph(paragraph)
    doc.save(str(path))
