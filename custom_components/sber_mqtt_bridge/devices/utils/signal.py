"""Signal strength conversion utility for Sber Smart Home protocol."""

from __future__ import annotations


def rssi_to_signal_strength(rssi: int) -> str:
    """Convert raw RSSI/linkquality value to Sber signal_strength enum.

    Args:
        rssi: Raw RSSI (dBm, typically negative) or linkquality value.

    Returns:
        Sber enum string: 'high', 'medium', or 'low'.
    """
    if rssi > -50:
        return "high"
    if rssi > -70:
        return "medium"
    return "low"
