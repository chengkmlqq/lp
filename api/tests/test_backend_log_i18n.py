"""LP-22 日志翻译层单测：zh 逐字不变 / en 翻译且动态值不丢 / 回落 / 原文保留。"""

from __future__ import annotations

import pytest

from app.services.backend_text_i18n import (
    _HAS_ZH,
    translate_backend_text,
    translate_log_line,
    translate_log_lines,
)


ZH_LINES = [
    "[ATP] 开始处理杆塔 T1（第 1/3 根）",
    "2026-11-15 | INFO     | [ATP] 开始处理杆塔 青八甲线#12（第 2/9 根）",
    "[abc-123] 地闪分布导入任务启动（distribution_id=d-1）",
    "[abc-123] 解析完成，采样点数量：120，解析警告数：2",
    "开始收集输入",
    "Traceback (most recent call last): 中文异常",
    "这不是登记表里的短语，回落中文",
    "ATP engine raw stdout: 1 2 3",
    "",
]


class TestZhPassthrough:
    def test_zh_is_byte_identical(self):
        for line in ZH_LINES:
            assert translate_log_line(line, "zh") == line

    def test_any_other_lang_is_byte_identical(self):
        for lang in ("", None, "fr", "ZH"):
            for line in ZH_LINES:
                assert translate_log_line(line, lang) == line

    def test_zh_batch_equals_input(self):
        assert translate_log_lines(ZH_LINES, "zh") == ZH_LINES


class TestEnTranslation:
    def test_dynamic_values_preserved(self):
        assert translate_log_line(
            "[ATP] 开始处理杆塔 T1（第 1/3 根）", "en"
        ) == "[ATP] Processing tower T1 (no. 1/3)"
        assert translate_log_line(
            "2026-11-15 | INFO     | [ATP] 开始处理杆塔 青八甲线#12（第 2/9 根）", "en"
        ) == "2026-11-15 | INFO     | [ATP] Processing tower 青八甲线#12 (no. 2/9)"

    def test_task_start_line(self):
        assert translate_log_line(
            "[abc-123] 地闪分布导入任务启动（distribution_id=d-1）", "en"
        ) == "[abc-123] Ground-flash distribution import task started (distribution_id=d-1)"

    def test_multiple_dynamic_numbers(self):
        assert translate_log_line(
            "[abc-123] 解析完成，采样点数量：120，解析警告数：2", "en"
        ) == "[abc-123] Parsing complete, samples: 120, parse warnings: 2"

    def test_step_phrase_in_log_line(self):
        assert translate_log_line("开始收集输入", "en") == "Collecting inputs"
        assert translate_log_line("[t] 开始收集输入", "en") == "[t] Collecting inputs"

    def test_no_holes_on_unmapped_fragment(self):
        result = translate_log_line("这不是登记表里的短语，回落中文", "en")
        assert result  # 不为空
        assert "回落中文" in result  # 未命中片段回落

    def test_ascii_and_traceback_untouched(self):
        assert translate_log_line("ATP engine raw stdout: 1 2 3", "en") == "ATP engine raw stdout: 1 2 3"
        assert translate_log_line(
            "Traceback (most recent call last): 中文异常", "en"
        ) == "Traceback (most recent call last): 中文异常"
        assert translate_log_line(
            '  File "/app/x.py", line 3, in 中文函数', "en"
        ) == '  File "/app/x.py", line 3, in 中文函数'

    def test_batch_returns_all_lines(self):
        result = translate_log_lines(ZH_LINES, "en")
        assert len(result) == len(ZH_LINES)
        assert result[0] == "[ATP] Processing tower T1 (no. 1/3)"


class TestBackendText:
    def test_zh_unchanged(self):
        assert translate_backend_text("开始收集输入", "zh") == "开始收集输入"

    def test_step_phrases(self):
        assert translate_backend_text("开始收集输入", "en") == "Collecting inputs"
        assert translate_backend_text("生成Word报告", "en") == "Generating Word report"

    def test_report_heading(self):
        assert (
            translate_backend_text("输电线路故障综合判别报告", "en")
            == "Transmission Line Fault Diagnosis Report"
        )

    def test_unmapped_falls_back(self):
        assert translate_backend_text("完全未知的中文句子", "en") == "完全未知的中文句子"

    def test_none_and_empty(self):
        assert translate_backend_text(None, "en") == ""
        assert translate_backend_text("", "en") == ""


class TestCaptureIntegration:
    @pytest.fixture(autouse=True)
    def _clean_registry(self):
        from app.core.task_log_capture import TaskLogCapture

        TaskLogCapture._registry.clear()
        yield
        TaskLogCapture._registry.clear()

    def test_buffer_en_snapshot_translated_raw_preserved(self):
        from app.core.task_log_capture import _TaskLogBuffer

        buf = _TaskLogBuffer("t-1", lang="en")
        buf.write("[ATP] 开始处理杆塔 T1（第 1/3 根）\n开始收集输入\n")
        assert buf.snapshot() == (
            "[ATP] Processing tower T1 (no. 1/3)\nCollecting inputs"
        )
        assert buf.snapshot(translate=False) == (
            "[ATP] 开始处理杆塔 T1（第 1/3 根）\n开始收集输入"
        )
        buf.close()

    def test_buffer_zh_snapshot_identical(self):
        from app.core.task_log_capture import _TaskLogBuffer

        buf = _TaskLogBuffer("t-2", lang="zh")
        buf.write("[ATP] 开始处理杆塔 T1（第 1/3 根）")
        assert buf.snapshot() == "[ATP] 开始处理杆塔 T1（第 1/3 根）"
        buf.close()

    def test_flush_sends_translated_lines_to_redis(self):
        from app.core.task_log_capture import _TaskLogBuffer
        from app.services import task_log_service

        sent: list[list[str]] = []
        original = task_log_service.append_task_log_lines
        task_log_service.append_task_log_lines = lambda task_id, lines: sent.append(list(lines))
        try:
            buf = _TaskLogBuffer("t-3", lang="en")
            buf.write("[ATP] 开始处理杆塔 T1（第 1/3 根）")
            buf.flush_incremental()
            assert sent == [["[ATP] Processing tower T1 (no. 1/3)"]]
            buf.close()
            buf = _TaskLogBuffer("t-4", lang="zh")
            buf.write("[ATP] 开始处理杆塔 T1（第 1/3 根）")
            buf.flush_incremental()
            assert sent[1] == ["[ATP] 开始处理杆塔 T1（第 1/3 根）"]
            buf.close()
        finally:
            task_log_service.append_task_log_lines = original

    def test_start_stop_and_peek_raw(self):
        from app.core.task_log_capture import TaskLogCapture

        TaskLogCapture.start("live-1", lang="en")
        buf = TaskLogCapture.get("live-1")
        assert buf is not None
        buf.log("[ATP] 开始处理杆塔 T1（第 1/3 根）")
        assert TaskLogCapture.peek_raw("live-1") == "[ATP] 开始处理杆塔 T1（第 1/3 根）"
        assert TaskLogCapture.stop("live-1") == ["[ATP] Processing tower T1 (no. 1/3)"]

    def test_start_defaults_to_zh_without_db(self):
        from app.core.task_log_capture import TaskLogCapture

        TaskLogCapture.start("live-2")
        buf = TaskLogCapture.get("live-2")
        assert buf is not None
        assert buf.lang == "zh"
        TaskLogCapture._registry.clear()


# ───────────────────────── LP-148：ATP 高频日志 / 提示 / 分析文本 ─────────────────────────

ATP_EN_LOG_LINES = [
    "[ATP] 模板渲染完成，输入文件大小=12345 字节，代码版本=v3，几何覆写=True，覆写项=7",
    "[ATP] 数值参数覆写（T1）：ZRE03_: 1.0 -> 2.0",
    "[ATP] 耦合系数槽位（T1）：11K0=0.123456（已写入）",
    "[ATP] 14XXSS 电角度已按 C# 规则改写：A=0.0 B=-120.0 C=-240.0",
    "[ATP] dT 自适应（T1）：其中 3/11 条支路波速取自 $PARAMETER 变量",
    "[ATP] dT 自适应生效（T1）：5e-09 s → 2e-09 s（最短支路行程 8.00 ns）",
    "[ATP] 输入文件已写入：/tmp/work.atp",
    "[ATP] 资产文件已物化到引擎目录 /data/engine，work.atp 渲染版已覆盖",
    "[ATP] startup 已复制到引擎目录 /data/engine",
    "[ATP] 自动选资产：电压=500 塔型=guxing 场景=raoji1 避雷器=无(来源=auto,命中=1) → asset=A1 (id1)",
    "[ATP] 开始执行外部波形分析：job=J1, 杆塔=T1(1), 模型=atp500, 适配器=atp",
    "[ATP] 执行命令：wine both work.atp s -r，工作目录：/tmp/run",
    "[ATP][STDOUT] 执行命令：wine both work.atp s -r，工作目录：/tmp/run",
    "[ATP] 执行完成：T1，退出码=0",
    "[ATP] 开始解析结果：T1，资产无结果契约，使用 lis 闪络检测",
    "[ATP] 结果解析完成：T1，payload_keys=['a', 'b']",
    "[ATP] lis 闪络检测（Close switch）：T1，闪络相数=2，相=A1,C1",
    "[ATP] 线路模型已重生成：long.lib（几何改写 + LCC）",
    "[ENGINE] 运行心跳：杆塔 T1（run1）tpbig 仿真，已耗时 30s，超时上限 600s",
    "[ENGINE][HEARTBEAT] 运行中：杆塔 T1（run1）tpbig 仿真，已耗时 30s，超时上限 600s",
    "[EGM] 绕击跳闸率（native 引擎）：egm1 电压=500 回路数=2 Ng=5.0 Ic=20.0 合计=0.123456 ÷2 = 0.061728",
]


class TestMoreLogRules:
    def test_atp_lines_have_no_chinese(self):
        for line in ATP_EN_LOG_LINES:
            result = translate_log_line(line, "en")
            assert not _HAS_ZH.search(result), (line, result)

    def test_dynamic_values_preserved(self):
        assert translate_log_line(ATP_EN_LOG_LINES[0], "en") == (
            "[ATP] Template render complete, input file size=12345 bytes, "
            "code version=v3, geometry override=True, override items=7"
        )
        assert "3/11 branch wave speeds" in translate_log_line(ATP_EN_LOG_LINES[4], "en")
        assert "exit code=0" in translate_log_line(ATP_EN_LOG_LINES[13], "en")

    def test_zh_still_identical(self):
        for line in ATP_EN_LOG_LINES:
            assert translate_log_line(line, "zh") == line


class TestPromptLocalization:
    def test_static_and_dynamic_prompts(self):
        from app.services.backend_text_i18n import translate_backend_text

        cases = {
            "当前线路没有可回填的杆塔数据": "The current line has no towers available for refill",
            "导入文件没有数据行": "The imported file has no data rows",
            "报告任务请使用报告下载入口": "For report tasks please use the report download entry",
            "采样间隔必须大于 0，已回退到 1.0us": "Sampling interval must be > 0; reverted to 1.0us",
            "第 12 行未识别为数值，已跳过": "Line 12: unrecognized numeric value; skipped",
            "第 3 行缺少有效的序号/塔号，已跳过": "Row 3: missing valid seq/tower no.; skipped",
            "无效的 start_date：2026-13-01，请使用 YYYY-MM-DD": "Invalid start_date: 2026-13-01; use YYYY-MM-DD",
        }
        for zh, en in cases.items():
            assert translate_backend_text(zh, "en") == en
            assert translate_backend_text(zh, "zh") == zh


class TestAnalysisTextI18n:
    def test_semicolon_and_dynamic_phrases(self):
        from app.services.analysis_text_i18n import translate_analysis_text

        assert translate_analysis_text(
            "规程法雷击风险等级为 3 级；反击跳闸率明显高于绕击跳闸率", "en"
        ) == ("Regulation-based lightning risk grade: 3; "
              "Back-flashover trip rate significantly exceeds shielding trip rate")
        assert translate_analysis_text(
            "按Heidler波形、相交法口径扫描 2.60/50.00 μs", "en"
        ) == "Scan per Heidler waveform and intersection method criterion: 2.60/50.00 μs"
        assert "；" not in translate_analysis_text(
            "规程法雷击风险等级为 3 级；档距偏大", "en"
        )

    def test_summary_text(self):
        from app.services.analysis_text_i18n import translate_analysis_text

        result = translate_analysis_text(
            "塔1普通计算，最不利点 2.60/50.00 μs，高风险，规程法等级 3，反击跳闸率 0.2458，含历史结果回退",
            "en",
        )
        assert "normal calculation" in result
        assert "Worst point 2.60/50.00 μs" in result
        assert "high risk" in result
        assert "Regulation grade 3" in result
        assert "Back-flashover trip rate 0.2458" in result
        assert "historical-result fallback" in result
        assert "，" not in result

    def test_zh_unchanged(self):
        from app.services.analysis_text_i18n import translate_analysis_text

        text = "塔1普通计算，最不利点 2.60/50.00 μs，高风险"
        assert translate_analysis_text(text, "zh") == text

    def test_lp149_mixed_fragments_fully_translated(self):
        """LP-149：3 条真实夹生文本在英文模式无中文残字，中文模式逐字不变。"""
        from app.services.analysis_text_i18n import translate_analysis_text

        cases = {
            "导线左右位置信息缺失, 当前Scanned per 对称坐标近似":
                "Conductor left/right position info missing; approximated with symmetric coordinates",
            "按Heidler waveform, intersection method criterion: 2.60/50.00 μs":
                "Scan per Heidler waveform and intersection method criterion: 2.60/50.00 μs",
            "建议结合波头/波尾最不利点继续复核绝缘配合与接地参数":
                "It is recommended to further recheck insulation coordination and grounding "
                "parameters based on the worst head/tail time point",
        }
        for zh, en in cases.items():
            result = translate_analysis_text(zh, "en")
            assert result == en, (zh, result)
            assert not _HAS_ZH.search(result), (zh, result)
            assert translate_analysis_text(zh, "zh") == zh

    def test_lp149_comma_variants_and_multi_segment(self):
        """全/半角逗号均命中，且多段文本仍以半角 '; ' 拼接。"""
        from app.services.analysis_text_i18n import translate_analysis_text

        for comma in ("，", ","):
            text = f"导线左右位置信息缺失{comma}当前按对称坐标近似；档距偏大"
            result = translate_analysis_text(text, "en")
            assert result == (
                "Conductor left/right position info missing; approximated with symmetric "
                "coordinates; Span is relatively large"
            ), result
            assert not _HAS_ZH.search(result)
