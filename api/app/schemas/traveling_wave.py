from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

TravelingWaveStatus = Literal["pending", "running", "success", "failed"]


class TravelingWaveStatusResponse(BaseModel):
    """Environment status for the traveling wave analysis service."""

    python_available: bool = True
    numpy_available: bool = False
    scipy_available: bool = False
    matplotlib_available: bool = False
    missing_components: list[str] = Field(default_factory=list, description="Missing dependency module names")
    error: str | None = None


class FileInput(BaseModel):
    """Server-side file path or file content for one phase."""

    path: str | None = None
    content: str | None = None


class TravelingWaveTempUploadResponse(BaseModel):
    """Response of a temp-file upload (two-phase upload flow)."""

    temp_file_id: str
    file_name: str = "upload"


class TravelingWaveAnalyzeRequest(BaseModel):
    """Request to start a traveling wave analysis job."""

    file_a: str | None = Field(default=None, description="Server path to A phase file")
    file_b: str | None = Field(default=None, description="Server path to B phase file")
    file_c: str | None = Field(default=None, description="Server path to C phase file")
    sample_rate_hz: int = Field(default=1_000_000, description="Sampling rate in Hz")
    fault_distance_km: float | None = Field(default=None, description="Fault distance in km")
    tower_no: str | None = Field(default=None, description="Tower number")


class TravelingWaveParseResult(BaseModel):
    """Parsed header info from a traveling wave data file."""

    wave_batch_id: str = ""
    vo_level: str = ""
    sample_frequency: int = 0
    head_time: str = ""
    head_time_parsed: datetime | None = None
    left_dist_ohl: int = 0
    right_dist_ohl: int = 0
    data_len: int = 0
    line_name: str = ""


class TravelingWaveAnalyzeResponse(BaseModel):
    """Result of a traveling wave analysis."""

    id: str
    status: TravelingWaveStatus
    created_at: datetime | None = None
    finished_at: datetime | None = None

    # Parsed info from the three phases
    phase_a_info: TravelingWaveParseResult | None = None
    phase_b_info: TravelingWaveParseResult | None = None
    phase_c_info: TravelingWaveParseResult | None = None

    # Basic info
    sample_rate_hz: int = 1_000_000
    vo_level: str = ""
    line_name: str = ""
    left_dist_ohl: int = 0
    right_dist_ohl: int = 0
    tower_no: str | None = None
    fault_distance_km: float | None = None

    # Chart data (base64-encoded PNG)
    three_phase_chart: str | None = None
    zero_sequence_chart: str | None = None

    # Log / error
    error_message: str | None = None
    log_text: str | None = None
