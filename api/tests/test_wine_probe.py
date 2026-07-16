from __future__ import annotations

from app.services.wine_probe import interpret_wine_probe_output


def test_interpret_wine_probe_output_marks_wine32_warning_unavailable() -> None:
    output = (
        "it looks like wine32 is missing, you should install it. multiarch needs to be enabled first.\n"
        'as root, please execute "dpkg --add-architecture i386 && apt-get update && apt-get install wine32:i386"\n'
        "wine-10.0 (Debian 10.0~repack-6)"
    )

    result = interpret_wine_probe_output(0, output)

    assert result.available is False
    assert result.version == output
    assert result.error == output


def test_interpret_wine_probe_output_accepts_normal_version() -> None:
    result = interpret_wine_probe_output(0, "wine-10.0 (Debian 10.0~repack-6)")

    assert result.available is True
    assert result.version == "wine-10.0 (Debian 10.0~repack-6)"
    assert result.error is None


def test_interpret_wine_probe_output_propagates_nonzero_exit() -> None:
    result = interpret_wine_probe_output(1, "wine: failed to load")

    assert result.available is False
    assert result.version == "wine: failed to load"
    assert result.error == "wine: failed to load"
