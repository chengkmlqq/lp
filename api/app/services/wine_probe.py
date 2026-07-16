from __future__ import annotations

import asyncio
import subprocess
from dataclasses import dataclass


_WINE32_MISSING_HINTS = (
    "it looks like wine32 is missing",
    "wine32 is missing",
)


@dataclass(slots=True)
class WineProbeResult:
    available: bool
    version: str | None
    error: str | None


def interpret_wine_probe_output(returncode: int, output: bytes | str | None) -> WineProbeResult:
    if isinstance(output, bytes):
        text = output.decode("utf-8", errors="replace")
    else:
        text = output or ""

    normalized = text.strip() or None
    if normalized:
        lowered = normalized.lower()
        if any(hint in lowered for hint in _WINE32_MISSING_HINTS):
            return WineProbeResult(available=False, version=normalized, error=normalized)

    if returncode != 0:
        return WineProbeResult(available=False, version=normalized, error=normalized)

    return WineProbeResult(available=True, version=normalized, error=None)


def probe_wine_binary(resolved_binary: str, *, timeout_seconds: int = 10) -> WineProbeResult:
    try:
        completed = subprocess.run(
            [resolved_binary, "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return WineProbeResult(available=False, version=None, error=str(exc))

    return interpret_wine_probe_output(completed.returncode, completed.stdout)


async def probe_wine_binary_async(resolved_binary: str, *, timeout_seconds: int = 10) -> WineProbeResult:
    try:
        process = await asyncio.create_subprocess_exec(
            resolved_binary,
            "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        output, _ = await asyncio.wait_for(process.communicate(), timeout=timeout_seconds)
    except (OSError, asyncio.TimeoutError) as exc:
        return WineProbeResult(available=False, version=None, error=str(exc))

    return interpret_wine_probe_output(process.returncode, output)
