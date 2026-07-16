from __future__ import annotations

import csv
import io
import math
from dataclasses import asdict, dataclass
from typing import Literal


FaultRecurrenceStrokeMode = Literal["counterstroke", "shielding"]

EPSILON = 1e-4
SUPPORTED_ENCODINGS = ("utf-8-sig", "utf-8", "gb18030", "gbk")
LEGACY_SECTION_START_MARKERS = {"<TGanTa>", "<XianLu>"}
LEGACY_SECTION_END_MARKERS = {"</TGanTa>", "</XianLu>"}
HEADER_FIELDS = {
    "head_time_us": "波头时间/μs",
    "tail_time_us": "波尾时间/μs",
    "counterstroke_withstand_ka": "反击耐雷水平kA",
    "shielding_withstand_ka": "绕击耐雷水平kA",
}
POSITIONAL_FIELD_INDEXES = {
    "head_time_us": 60,
    "tail_time_us": 61,
    "counterstroke_withstand_ka": 63,
    "shielding_withstand_ka": 65,
}
CURVE_LABELS = {
    1: "Heidler",
    2: "双斜角",
    3: "双指数",
}
STROKE_LABELS = {
    "counterstroke": "反击",
    "shielding": "绕击",
}


@dataclass(frozen=True)
class FaultRecurrencePoint:
    head_time_us: float
    tail_time_us: float
    counterstroke_withstand_ka: float
    shielding_withstand_ka: float


KDE_DATA_POINTS: tuple[tuple[float, float], ...] = (
    (2.5446625, 71.94915),
    (3.878075, 45.71697),
    (5.2919, 36.68912),
    (2.2, 35.016475),
    (5.2623375, 53.46354),
    (0.5975, 69.55),
    (8.6125, 40.043055),
    (1.0364225, 59.31549),
    (2.2287375, 68.80835),
    (6.3, 88.8407),
    (6.3791875, 45.053385),
    (38.3205, 75.1023),
    (2.770925, 86.41685),
    (0.78666, 43.69612),
    (1.9475375, 64.02136),
    (6.43745, 47.88732),
    (2.1827875, 64.6113),
    (5.878075, 62.836475),
    (0.94157125, 45.493045),
    (8.7521625, 45.177535),
    (1.381825, 67.2178),
    (5.39025, 73.2563),
    (3.5, 31.135),
    (11.3375, 14.495),
    (4.1772125, 100.8358),
    (41.0 / 160.0, 79.7992),
    (3.625, 92.95),
    (6.9187875, 57.616195),
    (0.904215, 55.79496),
    (2.925, 86.0249),
    (2.1625, 67.3465),
    (0.055375, 71.3609),
    (3.52085, 55.69681),
    (1.55, 77.29865),
    (9.1396125, 36.816325),
    (1.811025, 86.48445),
    (9.5971875, 46.126925),
    (1.9967875, 62.300745),
    (1.7409625, 40.6081),
    (9.5375, 49.27),
    (6.258875, 83.8786),
    (0.80435625, 83.265),
    (13.94925, 128.91645),
    (2.077225, 79.781),
    (10.8873375, 34.65475),
    (11.65, 33.865),
    (5.142125, 46.79155),
    (1.832, 87.789),
    (1.29575, 63.037325),
    (1.9125, 57.2),
    (2.4490625, 44.61132),
    (3.968625, 69.64555),
    (3.0873375, 44.872295),
    (3.4136625, 67.834),
    (2.452875, 75.61905),
    (2.3944875, 77.82255),
    (2.085875, 78.06955),
    (3.0885625, 78.0),
    (3.5739625, 66.1076),
    (2.4911625, 80.22755),
    (7.2521875, 56.4239),
    (0.95733125, 85.36125),
    (4.85, 72.54),
    (3.3823375, 50.460345),
    (1.6570625, 77.883),
    (5.9302875, 83.36445),
    (19.0, 82.68),
    (2.2402125, 83.1415),
    (2.28455, 77.97725),
    (1.645225, 86.0925),
    (12.625, 33.8),
    (2.5478, 62.411375),
    (6.5173125, 57.049395),
    (10.671875, 37.177335),
    (2.9472375, 55.92483),
    (2.9691, 50.966825),
    (9.0238125, 17.03364),
    (5.9496, 32.13704),
    (1.12263, 54.11705),
    (2.6329625, 66.84535),
    (2.23485, 64.15552),
    (1.3868625, 73.6411),
    (5.175, 76.284),
    (4.9095375, 31.97792),
    (5.8178125, 68.0498),
    (2.4029375, 18.073835),
    (3.200375, 56.467645),
    (11.185225, 84.01835),
    (5.362175, 37.23395),
    (4.804875, 53.678495),
    (6.351875, 65.56745),
    (3.094075, 78.03315),
    (1.520025, 74.08245),
    (2.7534, 79.118),
    (3.2919125, 65.1573),
    (3.2234875, 76.882),
    (3.87235, 76.0526),
)


def build_fault_recurrence_report(
    file_bytes: bytes,
    *,
    file_name: str,
    curve_no: int,
    stroke_mode: FaultRecurrenceStrokeMode,
    withstand_level_ka: float,
) -> dict[str, object]:
    if curve_no not in CURVE_LABELS:
        raise ValueError("波形数值越界，有效范围为 1-3")
    if stroke_mode not in STROKE_LABELS:
        raise ValueError("类型数值越界，仅支持 counterstroke/shielding")
    if withstand_level_ka <= 0:
        raise ValueError("耐雷水平必须大于 0")

    text = _decode_text(file_bytes)
    points, warnings, source_mode = parse_fault_recurrence_points(text)
    analysis = analyze_fault_recurrence_points(
        points,
        stroke_mode=stroke_mode,
        withstand_level_ka=withstand_level_ka,
    )
    warnings.extend(analysis.pop("warnings"))

    return {
        "curve_no": curve_no,
        "curve_label": CURVE_LABELS[curve_no],
        "stroke_mode": stroke_mode,
        "stroke_label": STROKE_LABELS[stroke_mode],
        "withstand_level_ka": withstand_level_ka,
        "source_file_name": file_name,
        "source_mode": source_mode,
        "point_count": len(points),
        "reference_counterstroke_ka": analysis.pop("reference_counterstroke_ka"),
        "reference_shielding_ka": analysis.pop("reference_shielding_ka"),
        "reference_point_found": analysis.pop("reference_point_found"),
        "warnings": warnings,
        "data_points": [asdict(point) for point in points],
        "result": analysis,
    }


def parse_fault_recurrence_points(text: str) -> tuple[list[FaultRecurrencePoint], list[str], str]:
    candidate_rows, source_mode = _extract_candidate_rows(text)
    header_map: dict[str, int] | None = None
    points: list[FaultRecurrencePoint] = []

    for raw_line in candidate_rows:
        columns = _parse_csv_row(raw_line)
        if not columns:
            continue
        if _looks_like_header(columns):
            header_map = {value.strip(): index for index, value in enumerate(columns)}
            continue

        point = _extract_point(columns, header_map)
        if point is not None:
            points.append(point)

    if not points:
        raise ValueError("未从上传文件解析到有效基础数据，请确认文件包含波头/波尾与耐雷水平列。")

    points.sort(key=lambda item: (item.head_time_us, item.tail_time_us))
    return points, [], source_mode


def analyze_fault_recurrence_points(
    points: list[FaultRecurrencePoint],
    *,
    stroke_mode: FaultRecurrenceStrokeMode,
    withstand_level_ka: float,
) -> dict[str, object]:
    reference_point, reference_found = _search_reference_point(points)
    reference_counterstroke = reference_point.counterstroke_withstand_ka
    reference_shielding = reference_point.shielding_withstand_ka
    selected_reference = _selected_withstand_value(reference_point, stroke_mode)
    warnings: list[str] = []

    if not reference_found:
        warnings.append("未发现波头 2.6μs / 波尾 50μs 的基准点，按源端逻辑回退为首条基础数据。")

    if withstand_level_ka > selected_reference:
        return {
            "status": "no_need",
            "message": "No need!",
            "head_time_us": None,
            "tail_time_us": None,
            "probability_density": None,
            "reference_counterstroke_ka": reference_counterstroke,
            "reference_shielding_ka": reference_shielding,
            "reference_point_found": reference_found,
            "warnings": warnings,
        }

    best_candidate: tuple[float, float, float] | None = None
    groups = _group_points_by_head(points)

    for group_index, group in enumerate(groups):
        previous_point: FaultRecurrencePoint | None = None
        previous_value: float | None = None

        for point_index, point in enumerate(group):
            current_value = _selected_withstand_value(point, stroke_mode)

            if previous_point is None:
                best_candidate = _consider_candidate(
                    best_candidate,
                    point.head_time_us,
                    point.tail_time_us,
                )
                previous_point = point
                previous_value = current_value
                continue

            interpolated = _interpolate_candidate(
                previous_point,
                point,
                previous_value,
                current_value,
                withstand_level_ka,
            )
            if interpolated is not None:
                best_candidate = _consider_candidate(
                    best_candidate,
                    interpolated[0],
                    interpolated[1],
                )
            elif _is_close(withstand_level_ka, current_value):
                best_candidate = _consider_candidate(
                    best_candidate,
                    point.head_time_us,
                    point.tail_time_us,
                )

            if (
                group_index == len(groups) - 1
                and point_index == len(group) - 1
                and stroke_mode == "shielding"
                and withstand_level_ka < current_value
            ):
                best_candidate = _consider_candidate(
                    best_candidate,
                    point.head_time_us,
                    point.tail_time_us,
                )

            previous_point = point
            previous_value = current_value

    if best_candidate is None:
        best_candidate = _consider_candidate(
            None,
            points[0].head_time_us,
            points[0].tail_time_us,
        )

    head_time_us, tail_time_us, probability_density = best_candidate
    return {
        "status": "matched",
        "message": f"head = {_format_float(head_time_us)}, tail = {_format_float(tail_time_us)}, pro = {_format_float(probability_density)}",
        "head_time_us": head_time_us,
        "tail_time_us": tail_time_us,
        "probability_density": probability_density,
        "reference_counterstroke_ka": reference_counterstroke,
        "reference_shielding_ka": reference_shielding,
        "reference_point_found": reference_found,
        "warnings": warnings,
    }


def _decode_text(file_bytes: bytes) -> str:
    last_error: UnicodeDecodeError | None = None
    for encoding in SUPPORTED_ENCODINGS:
        try:
            return file_bytes.decode(encoding)
        except UnicodeDecodeError as error:
            last_error = error
    raise ValueError("文件编码不受支持，请使用 UTF-8、GBK 或 GB18030 文本文件。") from last_error


def _extract_candidate_rows(text: str) -> tuple[list[str], str]:
    rows = text.splitlines()
    has_legacy_markers = any(row.strip() in LEGACY_SECTION_START_MARKERS for row in rows)
    if not has_legacy_markers:
        return [row for row in rows if row.strip()], "plain-csv"

    collected: list[str] = []
    inside_legacy_section = False

    for raw_row in rows:
        stripped = raw_row.strip()
        if stripped in LEGACY_SECTION_START_MARKERS:
            inside_legacy_section = True
            continue
        if stripped in LEGACY_SECTION_END_MARKERS:
            inside_legacy_section = False
            continue
        if inside_legacy_section and stripped:
            collected.append(raw_row)

    return collected, "legacy-sections"


def _parse_csv_row(raw_line: str) -> list[str]:
    try:
        return [value.strip() for value in next(csv.reader([raw_line], skipinitialspace=False))]
    except csv.Error:
        return [value.strip() for value in raw_line.split(",")]


def _looks_like_header(columns: list[str]) -> bool:
    normalized = {value.strip() for value in columns if value.strip()}
    if "杆塔模型" in normalized:
        return True
    required_headers = set(HEADER_FIELDS.values())
    return len(required_headers.intersection(normalized)) >= 2


def _extract_point(columns: list[str], header_map: dict[str, int] | None) -> FaultRecurrencePoint | None:
    if header_map:
        head = _parse_positive_float(_read_header_value(columns, header_map, HEADER_FIELDS["head_time_us"]))
        tail = _parse_positive_float(_read_header_value(columns, header_map, HEADER_FIELDS["tail_time_us"]))
        counterstroke = _parse_positive_float(
            _read_header_value(columns, header_map, HEADER_FIELDS["counterstroke_withstand_ka"])
        )
        shielding = _parse_positive_float(
            _read_header_value(columns, header_map, HEADER_FIELDS["shielding_withstand_ka"])
        )
    else:
        head = _parse_positive_float(_read_positional_value(columns, POSITIONAL_FIELD_INDEXES["head_time_us"]))
        tail = _parse_positive_float(_read_positional_value(columns, POSITIONAL_FIELD_INDEXES["tail_time_us"]))
        counterstroke = _parse_positive_float(
            _read_positional_value(columns, POSITIONAL_FIELD_INDEXES["counterstroke_withstand_ka"])
        )
        shielding = _parse_positive_float(
            _read_positional_value(columns, POSITIONAL_FIELD_INDEXES["shielding_withstand_ka"])
        )

    if head is None or tail is None or counterstroke is None or shielding is None:
        return None

    return FaultRecurrencePoint(
        head_time_us=head,
        tail_time_us=tail,
        counterstroke_withstand_ka=counterstroke,
        shielding_withstand_ka=shielding,
    )


def _read_header_value(columns: list[str], header_map: dict[str, int], field_name: str) -> str | None:
    index = header_map.get(field_name)
    if index is None or index >= len(columns):
        return None
    return columns[index]


def _read_positional_value(columns: list[str], index: int) -> str | None:
    if index >= len(columns):
        return None
    return columns[index]


def _parse_positive_float(value: str | None) -> float | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    try:
        parsed = float(normalized)
    except ValueError:
        return None
    if parsed <= 0:
        return None
    return parsed


def _search_reference_point(points: list[FaultRecurrencePoint]) -> tuple[FaultRecurrencePoint, bool]:
    for point in points:
        if _is_close(point.head_time_us, 2.6) and _is_close(point.tail_time_us, 50.0):
            return point, True
    return points[0], False


def _group_points_by_head(points: list[FaultRecurrencePoint]) -> list[list[FaultRecurrencePoint]]:
    groups: list[list[FaultRecurrencePoint]] = []
    current_group: list[FaultRecurrencePoint] = []
    current_head: float | None = None

    for point in points:
        if current_head is None or _is_close(point.head_time_us, current_head):
            current_group.append(point)
            current_head = point.head_time_us
            continue
        groups.append(current_group)
        current_group = [point]
        current_head = point.head_time_us

    if current_group:
        groups.append(current_group)
    return groups


def _selected_withstand_value(point: FaultRecurrencePoint, stroke_mode: FaultRecurrenceStrokeMode) -> float:
    if stroke_mode == "shielding":
        return point.shielding_withstand_ka
    return point.counterstroke_withstand_ka


def _interpolate_candidate(
    previous_point: FaultRecurrencePoint,
    current_point: FaultRecurrencePoint,
    previous_value: float,
    current_value: float,
    target_value: float,
) -> tuple[float, float] | None:
    if _is_close(target_value, current_value):
        return current_point.head_time_us, current_point.tail_time_us
    if _is_close(previous_value, current_value):
        return None
    if (previous_value - target_value) * (current_value - target_value) > 0:
        return None

    if _is_close(previous_point.head_time_us, current_point.head_time_us):
        ratio = (target_value - previous_value) / (current_value - previous_value)
        tail_time_us = previous_point.tail_time_us + (
            (current_point.tail_time_us - previous_point.tail_time_us) * ratio
        )
        return previous_point.head_time_us, tail_time_us

    if _is_close(previous_point.tail_time_us, current_point.tail_time_us):
        ratio = (target_value - previous_value) / (current_value - previous_value)
        head_time_us = previous_point.head_time_us + (
            (current_point.head_time_us - previous_point.head_time_us) * ratio
        )
        return head_time_us, previous_point.tail_time_us

    return None


def _consider_candidate(
    current_best: tuple[float, float, float] | None,
    head_time_us: float,
    tail_time_us: float,
) -> tuple[float, float, float]:
    probability_density = probability_density_for_point(head_time_us, tail_time_us)
    if current_best is None or probability_density > current_best[2]:
        return head_time_us, tail_time_us, probability_density
    return current_best


def probability_density_for_point(head_time_us: float, tail_time_us: float) -> float:
    bandwidth_head = 1.14148986513825
    bandwidth_tail = 9.65598579731003
    kernel_sum = 0.0

    for sample_head, sample_tail in KDE_DATA_POINTS:
        exponent = -0.5 * (
            math.pow((head_time_us - sample_head) / bandwidth_head, 2.0)
            + math.pow((tail_time_us - sample_tail) / bandwidth_tail, 2.0)
        )
        kernel_sum += math.exp(exponent)

    denominator = math.pi * 194.0 * bandwidth_head * bandwidth_tail * 0.999874014593309
    return kernel_sum / denominator


def _is_close(left: float, right: float) -> bool:
    return abs(left - right) < EPSILON


def _format_float(value: float) -> str:
    return format(value, ".12g")
