from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


FaultRecurrenceStrokeMode = Literal["counterstroke", "shielding"]
FaultRecurrenceResultStatus = Literal["matched", "no_need"]


class FaultRecurrenceDataPoint(BaseModel):
    head_time_us: float
    tail_time_us: float
    counterstroke_withstand_ka: float
    shielding_withstand_ka: float


class FaultRecurrenceResult(BaseModel):
    status: FaultRecurrenceResultStatus
    message: str
    head_time_us: float | None = None
    tail_time_us: float | None = None
    probability_density: float | None = None


class FaultRecurrenceAnalyzeResponse(BaseModel):
    curve_no: int
    curve_label: str
    stroke_mode: FaultRecurrenceStrokeMode
    stroke_label: str
    withstand_level_ka: float
    source_file_name: str
    source_mode: str
    point_count: int
    reference_counterstroke_ka: float
    reference_shielding_ka: float
    reference_point_found: bool
    warnings: list[str] = Field(default_factory=list)
    data_points: list[FaultRecurrenceDataPoint] = Field(default_factory=list)
    result: FaultRecurrenceResult
