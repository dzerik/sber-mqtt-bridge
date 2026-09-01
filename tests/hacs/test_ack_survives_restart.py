"""Acknowledgement state must not look like rejection after a restart.

Reported as issue #57: after every Home Assistant restart the panel showed
every exposed device as unacknowledged, until the user opened the Salute
app.  The devices were registered the whole time.

The cause is structural, not a slip.  The Sber C2C protocol has no upward
question: the bridge only publishes on ``up/config`` and ``up/status``,
and everything it learns about the cloud's side comes from what the cloud
volunteers in ``down/status_request`` and commands.  So "acknowledged"
can only ever mean "the cloud spoke to us about this device", and that
mark lives in memory — a restart empties it while the cloud, unaware that
anything happened, stays quiet until something asks it for state.

What was *not* structural is re-deriving the picture from scratch every
boot.  :class:`~cloud_device_registry.CloudDeviceRegistry` already
persists the ids the cloud is known to hold into ``ConfigEntry.options``.
These tests pin the three-way distinction built on it:

* **known to the cloud** — remembered across restarts, the normal state;
* **confirmed this session** — the old, volatile signal;
* **never confirmed** — neither of the above, and the only one worth
  alerting on.
"""

from __future__ import annotations

from typing import Any

import pytest

LAMP = "light.kitchen"
PUMP = "switch.pump"


@pytest.fixture
def bridge(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Build a bridge stub exposing two entities and no cloud memory.

    Args:
        monkeypatch: pytest fixture, unused but keeps the signature
            stable for future needs.

    Returns:
        A :class:`SberBridge` with its collaborators stubbed down to the
        three attributes the properties under test actually read.
    """
    from custom_components.sber_mqtt_bridge.sber_bridge import SberBridge

    obj = object.__new__(SberBridge)
    obj._enabled_entity_ids = [LAMP, PUMP]

    class _Stats:
        """Only the fields the properties read.

        ``collectively_acked_entities`` holds the ids acknowledged without
        being named (a ``status_request`` with no device list); the alarm
        subtracts it from the acknowledgement set so a collective signal
        cannot vouch for an individual device.
        """

        def __init__(self) -> None:
            self.acknowledged_entities: set[str] = set()
            self.collectively_acked_entities: set[str] = set()

    class _CloudDevices:
        """Stand-in for the persisted registry."""

        def __init__(self) -> None:
            self.known: frozenset[str] = frozenset()

    obj._stats = _Stats()
    obj._cloud_devices = _CloudDevices()
    return obj


class TestFreshInstall:
    """Ничего ещё не подтверждалось — всё честно «не подтверждено»."""

    def test_everything_is_never_confirmed(self, bridge: Any) -> None:
        """На чистой установке оба списка совпадают.

        До первого разговора с облаком «не подтверждено в сессии» и
        «не подтверждено никогда» — это одно и то же множество, и
        предупреждение здесь законно.
        """
        assert bridge.unacknowledged_entities == [LAMP, PUMP]
        assert bridge.never_confirmed_entities == [LAMP, PUMP]
        assert bridge.cloud_known_entities == []


class TestAfterRestart:
    """Главный сценарий issue #57."""

    def test_cloud_memory_survives_an_empty_session(self, bridge: Any) -> None:
        """После перезапуска устройства «известны облаку», а не отклонены.

        Отметок текущей сессии нет — именно так выглядит мост сразу
        после рестарта. Но облако о них спрашивало раньше, и это
        сохранено. Если тест упадёт, пользователь снова увидит все свои
        устройства помеченными как непринятые.
        """
        bridge._cloud_devices.known = frozenset({LAMP, PUMP})

        assert bridge.unacknowledged_entities == [LAMP, PUMP], "отметка сессии обязана оставаться пустой"
        assert bridge.cloud_known_entities == [LAMP, PUMP]
        assert bridge.never_confirmed_entities == [], "ни одно устройство не должно выглядеть отклонённым"

    def test_partial_memory_isolates_the_real_problem(self, bridge: Any) -> None:
        """Одно устройство помнится, второе — нет: тревога только по второму."""
        bridge._cloud_devices.known = frozenset({LAMP})

        assert bridge.cloud_known_entities == [LAMP]
        assert bridge.never_confirmed_entities == [PUMP]

    def test_session_ack_alone_clears_the_alarm(self, bridge: Any) -> None:
        """Подтверждение в текущей сессии тоже снимает тревогу.

        Устройство, о котором облако заговорило прямо сейчас, не может
        быть «никогда не подтверждённым», даже если сохранённая память
        до него ещё не дошла.
        """
        bridge._stats.acknowledged_entities.add(PUMP)

        assert bridge.never_confirmed_entities == [LAMP]
        assert bridge.unacknowledged_entities == [LAMP]


class TestScope:
    """Списки ограничены выставленными наружу сущностями."""

    def test_cloud_memory_of_removed_devices_is_ignored(self, bridge: Any) -> None:
        """Устройство, убранное пользователем, не попадает в счётчики.

        Сохранённая память переживает не только перезапуск, но и
        удаление сущности из моста. Без фильтра по актуальному списку
        счётчик «известно облаку» показывал бы больше, чем выставлено
        наружу, и не сходился бы с общим числом.
        """
        bridge._cloud_devices.known = frozenset({LAMP, PUMP, "light.removed_long_ago"})

        assert bridge.cloud_known_entities == [LAMP, PUMP]

    def test_order_follows_the_exposed_list(self, bridge: Any) -> None:
        """Порядок совпадает с порядком выставленных сущностей.

        Множество не упорядочено; выдача в порядке `enabled_entity_ids`
        делает вывод в панели стабильным между опросами.
        """
        bridge._enabled_entity_ids = [PUMP, LAMP]
        bridge._cloud_devices.known = frozenset({LAMP, PUMP})

        assert bridge.cloud_known_entities == [PUMP, LAMP]
