"""LP-22 日志翻译层单测：zh 逐字不变 / en 翻译且动态值不丢 / 回落 / 原文保留。"""

from __future__ import annotations

import pytest

from app.services.backend_text_i18n import (
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
