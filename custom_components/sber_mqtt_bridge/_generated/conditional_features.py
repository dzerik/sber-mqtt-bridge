"""AUTO-GENERATED from tests/hacs/__snapshots__/sber_full_spec.json.

DO NOT EDIT BY HAND.  Regenerate with:

    python tools/codegen.py

Source: https://developers.sber.ru/docs/ru/smarthome/c2c
Spec generated at: 2026-07-03T14:23:03.048208+00:00
"""

from __future__ import annotations

CATEGORY_CONDITIONAL_FEATURES: dict[str, frozenset[str]] = {
    "curtain": frozenset({"open_percentage", "open_set"}),
    "gate": frozenset({"open_percentage", "open_set"}),
    "sensor_air": frozenset({"co2", "hcho_float", "humidity", "pm10", "pm1_0", "pm2_5", "temperature", "tvoc_float"}),
    "sensor_temp": frozenset({"humidity", "temperature"}),
    "valve": frozenset({"open_percentage", "open_set"}),
    "window_blind": frozenset({"open_percentage", "open_set"}),
}
"""Features marked conditionally obligatory (``✔︎*``) per category.

Sber footnotes these as "at least one of" groups: a gate must describe
*some* way to open (``open_percentage`` or ``open_set`` or both), an air
sensor must report *some* measurement.  Declaring none of them is as
fatal as omitting a strictly obligatory feature — the cloud drops the
device — yet the strict :data:`CATEGORY_OBLIGATORY_FEATURES` table
cannot express it, which is why this second table exists.

Only categories that actually carry a group are listed; the absence of
a key means "no conditional group", not "empty group".

The check belongs on the device's **declared features**, not on a state
payload: command-only members such as ``open_set`` hold no state and
never appear in a publish (see the Sber page for ``open_set``: "Не
хранит состояние устройства")."""
