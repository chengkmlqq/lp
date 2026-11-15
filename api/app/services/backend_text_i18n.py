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
from typing import Any, Iterable

_HAS_ZH = re.compile(r"[\u4e00-\u9fff]")

# 引擎原始输出 / traceback 帧：原样保留，不翻译（LP-22 明确不覆盖）。
_SKIP_LINE = re.compile(
    r"^\s*(?:Traceback \(most recent call last\)|File \"|[A-Za-z_][\w.]*(?:Error|Exception|Warning):)"
)

# ───────────────────────── 1) 日志行模板（含动态值，反向引用带回） ─────────────────────────
# 每条规则用 re.sub 命中「中文模板片段」并替换，行首时间戳 / 日志级别等前缀自动保留。
_LOG_RULES: list[tuple[str, str]] = [
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
]

_COMPILED_LOG_RULES: list[tuple[re.Pattern[str], str]] = [
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
