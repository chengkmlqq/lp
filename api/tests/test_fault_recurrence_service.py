from __future__ import annotations

import unittest

from app.services.fault_recurrence_service import (
    analyze_fault_recurrence_points,
    build_fault_recurrence_report,
    parse_fault_recurrence_points,
)


class FaultRecurrenceServiceTest(unittest.TestCase):
    def test_parse_legacy_section_file_sorts_points(self) -> None:
        payload = """
<TGanTa>
任务编号,杆塔模型,波头时间/μs,波尾时间/μs,反击耐雷水平kA,绕击耐雷水平kA
1,Model-A,3.1,55,18,16
2,Model-B,2.6,50,12,10
</TGanTa>
"""
        points, warnings, source_mode = parse_fault_recurrence_points(payload)

        self.assertEqual(warnings, [])
        self.assertEqual(source_mode, "legacy-sections")
        self.assertEqual(len(points), 2)
        self.assertEqual(points[0].head_time_us, 2.6)
        self.assertEqual(points[0].tail_time_us, 50.0)
        self.assertEqual(points[1].head_time_us, 3.1)

    def test_report_returns_no_need_when_withstand_exceeds_reference_point(self) -> None:
        payload = """
杆塔模型,波头时间/μs,波尾时间/μs,反击耐雷水平kA,绕击耐雷水平kA
Model-A,2.6,50,10,9
Model-B,3.1,55,18,16
"""
        report = build_fault_recurrence_report(
            payload.encode("utf-8"),
            file_name="fault.csv",
            curve_no=1,
            stroke_mode="counterstroke",
            withstand_level_ka=12.0,
        )

        self.assertEqual(report["source_mode"], "plain-csv")
        self.assertEqual(report["reference_counterstroke_ka"], 10.0)
        self.assertEqual(report["result"]["status"], "no_need")
        self.assertEqual(report["result"]["message"], "No need!")

    def test_analysis_interpolates_tail_on_same_head_group(self) -> None:
        payload = """
杆塔模型,波头时间/μs,波尾时间/μs,反击耐雷水平kA,绕击耐雷水平kA
Model-A,2.6,40,8,7
Model-B,2.6,50,12,11
Model-C,2.6,60,16,15
"""
        report = build_fault_recurrence_report(
            payload.encode("utf-8"),
            file_name="fault.csv",
            curve_no=2,
            stroke_mode="counterstroke",
            withstand_level_ka=10.0,
        )

        result = report["result"]
        self.assertEqual(result["status"], "matched")
        self.assertAlmostEqual(result["head_time_us"], 2.6, places=6)
        self.assertAlmostEqual(result["tail_time_us"], 45.0, places=6)
        self.assertGreater(result["probability_density"], 0.0)

    def test_analysis_warns_when_reference_point_is_missing(self) -> None:
        points, _, _ = parse_fault_recurrence_points(
            """
杆塔模型,波头时间/μs,波尾时间/μs,反击耐雷水平kA,绕击耐雷水平kA
Model-A,3.0,40,20,18
Model-B,3.0,50,24,22
"""
        )
        result = analyze_fault_recurrence_points(
            points,
            stroke_mode="shielding",
            withstand_level_ka=19.0,
        )

        self.assertFalse(result["reference_point_found"])
        self.assertTrue(result["warnings"])


if __name__ == "__main__":
    unittest.main()
