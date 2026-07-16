from __future__ import annotations

from app.schemas.fl_analysis import FlAnalysisWaveformExecutionOptions


def test_fl_analysis_waveform_execution_options_defaults() -> None:
    payload = FlAnalysisWaveformExecutionOptions()

    assert payload.current_waveform == "heidler"
    assert payload.flashover_method == "intersection"
    assert payload.altitude_correction == "none"
    assert payload.head_time_min_us == 2.6
    assert payload.tail_time_max_us == 50.0
