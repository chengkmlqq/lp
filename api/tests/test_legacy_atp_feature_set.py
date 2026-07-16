from __future__ import annotations

from pathlib import Path

from app.services.legacy_atp_adapter import apply_feature_bindings, load_feature_bindings_from_setting_file


def test_load_feature_bindings_from_gb18030_setting_file_and_apply_offsets(tmp_path: Path) -> None:
    setting_path = tmp_path / "features.txt"
    setting_path.write_bytes(
        (
            "# 中文注释\n"
            "GROUND_RES,10,6,F1,base_tower.ground_resistance_ohm\n"
            "TOWER_NO,30,4,,snapshot.tower_no\n"
        ).encode("gb18030")
    )
    bindings = load_feature_bindings_from_setting_file(setting_path)

    assert len(bindings) == 2
    assert bindings[0].name == "GROUND_RES"
    assert bindings[0].offset == 10
    assert bindings[0].length == 6
    assert bindings[0].format_spec == "F1"

    model_path = tmp_path / "sample.atp"
    original = list("BEGIN" + (" " * 1595))
    model_path.write_text("".join(original), encoding="utf-8")

    apply_feature_bindings(
        run_dir=tmp_path,
        model_file="sample.atp",
        bindings=bindings,
        context={
            "base_tower": {"ground_resistance_ohm": 12.34},
            "snapshot": {"tower_no": "N01"},
        },
        minimum_model_size_bytes=1024,
        required_keywords=["BEGIN"],
    )

    updated = model_path.read_text(encoding="utf-8")
    assert updated[10:16] == "  12.3"
    assert updated[30:34] == " N01"
