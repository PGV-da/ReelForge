"""
ReelForge Time Parsing Utilities.

Converts between human-readable timestamps ("MM:SS", "HH:MM:SS"),
raw seconds, milliseconds, and SRT-format timestamps.
"""

from __future__ import annotations

import re


def parse_to_ms(value: str) -> int:
    """
    Parse a timestamp string or numeric value into milliseconds.

    Supported formats:
        - ``"MM:SS"`` → minutes and seconds (e.g., ``"01:30"`` → 90000 ms)
        - ``"HH:MM:SS"`` → hours, minutes, seconds (e.g., ``"00:01:30"`` → 90000 ms)
        - ``"MM:SS.mmm"`` → with fractional seconds (e.g., ``"01:30.500"`` → 90500 ms)
        - ``"90"`` or ``"90.5"`` → raw seconds (e.g., ``"90"`` → 90000 ms)
        - ``"90000"`` → already in milliseconds if > 1000 and no decimal (heuristic)

    Args:
        value: Timestamp string to parse.

    Returns:
        Time value in milliseconds.

    Raises:
        ValueError: If the format cannot be parsed.
    """
    value = value.strip()

    # HH:MM:SS or HH:MM:SS.mmm
    match = re.match(r"^(\d+):(\d{1,2}):(\d{1,2})(?:\.(\d+))?$", value)
    if match:
        h, m, s = int(match.group(1)), int(match.group(2)), int(match.group(3))
        ms_frac = int(match.group(4).ljust(3, "0")[:3]) if match.group(4) else 0
        return ((h * 3600) + (m * 60) + s) * 1000 + ms_frac

    # MM:SS or MM:SS.mmm
    match = re.match(r"^(\d+):(\d{1,2})(?:\.(\d+))?$", value)
    if match:
        m, s = int(match.group(1)), int(match.group(2))
        ms_frac = int(match.group(3).ljust(3, "0")[:3]) if match.group(3) else 0
        return ((m * 60) + s) * 1000 + ms_frac

    # Plain numeric: seconds (with optional decimal) or milliseconds
    match = re.match(r"^(\d+)(?:\.(\d+))?$", value)
    if match:
        whole = int(match.group(1))
        frac = match.group(2)

        if frac is not None:
            # Has a decimal → treat as seconds
            seconds = float(f"{whole}.{frac}")
            return int(seconds * 1000)

        # Heuristic: values >= 1000 with no decimal are treated as milliseconds
        if whole >= 1000:
            return whole

        # Otherwise treat as seconds
        return whole * 1000

    raise ValueError(
        f"Cannot parse timestamp '{value}'. "
        "Supported formats: MM:SS, HH:MM:SS, seconds, or milliseconds."
    )


def ms_to_srt_timestamp(ms: int) -> str:
    """
    Convert milliseconds to SRT timestamp format ``HH:MM:SS,mmm``.

    Args:
        ms: Time in milliseconds.

    Returns:
        Formatted string like ``"00:01:23,456"``.
    """
    if ms < 0:
        ms = 0

    hours = ms // 3_600_000
    ms %= 3_600_000
    minutes = ms // 60_000
    ms %= 60_000
    seconds = ms // 1_000
    millis = ms % 1_000

    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def seconds_to_srt_timestamp(seconds: float) -> str:
    """
    Convert seconds (float) to SRT timestamp format ``HH:MM:SS,mmm``.

    Args:
        seconds: Time in seconds, e.g., 83.456.

    Returns:
        Formatted string like ``"00:01:23,456"``.
    """
    return ms_to_srt_timestamp(int(seconds * 1000))


def format_duration(seconds: float) -> str:
    """
    Format a duration in seconds to a human-readable string.

    Args:
        seconds: Duration in seconds.

    Returns:
        Formatted string like ``"1m 23s"`` or ``"45s"``.
    """
    if seconds < 0:
        seconds = 0

    mins = int(seconds) // 60
    secs = int(seconds) % 60

    if mins > 0:
        return f"{mins}m {secs:02d}s"
    return f"{secs}s"
