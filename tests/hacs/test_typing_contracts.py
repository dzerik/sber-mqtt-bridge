"""Тесты типизации: mypy-гейт и контракт ``DeviceData``.

CLAUDE.md называет ``mypy custom_components/sber_mqtt_bridge/`` штатным шагом,
но до сих пор ни один прогон его не выполнял — ни CI, ни pre-commit, ни тесты.
Файл закрывает эту дыру для модулей «инфраструктурного» слоя (загрузчик
сущностей, диспетчер команд, форвардер состояний, WebSocket API): если кто-то
вернёт в них аннотацию ``object`` вместо реального типа или уронит narrowing —
падает :func:`test_infrastructure_modules_typecheck_clean`, а не молчаливый
конфиг, который никто не запускает.

Устройства (``devices/``), ``sber_bridge.py``, ``sber_publisher.py``,
``schema_validator.py`` и ``sber_models.py`` в список намеренно НЕ входят:
там ошибки типов пока есть, и гейт по ним был бы вечно красным.  Список
расширяется по мере починки соседних слоёв.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from custom_components.sber_mqtt_bridge.devices.light import LightEntity
from custom_components.sber_mqtt_bridge.entity_registry import SberEntityLoader

REPO_ROOT = Path(__file__).resolve().parents[2]
"""Корень репозитория — рабочая директория для mypy (там лежит pyproject.toml)."""

TYPED_MODULES = (
    "custom_components/sber_mqtt_bridge/command_dispatcher.py",
    "custom_components/sber_mqtt_bridge/config_publish_gate.py",
    "custom_components/sber_mqtt_bridge/custom_capabilities.py",
    "custom_components/sber_mqtt_bridge/device_grouper.py",
    "custom_components/sber_mqtt_bridge/diagnostics.py",
    "custom_components/sber_mqtt_bridge/entity_registry.py",
    "custom_components/sber_mqtt_bridge/ha_state_forwarder.py",
    "custom_components/sber_mqtt_bridge/reconnect_ack_guard.py",
    "custom_components/sber_mqtt_bridge/state_diff.py",
    "custom_components/sber_mqtt_bridge/websocket_api/",
)
"""Модули, для которых mypy обязан быть зелёным."""

MYPY_PYTHON_VERSION = "3.14"
"""Версия синтаксиса для mypy.

``[tool.mypy] python_version = "3.13"`` в pyproject.toml делает прогон
невозможным: mypy разбирает исходники установленного Home Assistant, а те
используют синтаксис 3.14 (``except`` без скобок в ``config_entries.py``), и
проверка падает на первом же файле, не дойдя до нашего кода.  Тесты проекта
всё равно идут на 3.14 — флаг командной строки перекрывает конфиг.
"""

MYPY_CACHE_DIR = Path(tempfile.gettempdir()) / "sber-mqtt-bridge-mypy-cache"
"""Кэш вне репозитория: повторный прогон занимает секунды, а рабочее дерево
не обрастает неотслеживаемым ``.mypy_cache/``."""


def test_infrastructure_modules_typecheck_clean() -> None:
    """mypy не находит ошибок в инфраструктурных модулях моста.

    Что ломается у пользователя, если тест упал: ошибка типа в этих модулях
    означает, что аннотация разошлась с фактическим кодом — например, параметр
    снова объявлен как ``object`` и любая опечатка в имени атрибута
    (``yaml_cfg.sber_nicknames`` → ``sber_nicknmes``) перестаёт ловиться и
    доезжает до рантайма как ``AttributeError`` внутри загрузки сущностей,
    то есть как «интеграция не запустилась» после рестарта HA.
    """
    pytest.importorskip("mypy", reason="mypy не установлен в этом окружении")

    result = subprocess.run(  # noqa: S603 - фиксированная команда, без пользовательского ввода
        [
            sys.executable,
            "-m",
            "mypy",
            "--python-version",
            MYPY_PYTHON_VERSION,
            "--cache-dir",
            str(MYPY_CACHE_DIR),
            *TYPED_MODULES,
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "MYPY_FORCE_COLOR": "0"},
    )

    assert result.returncode == 0, f"mypy нашёл ошибки типов:\n{result.stdout}{result.stderr}"


def test_linked_device_name_is_always_a_string() -> None:
    """У безымянного HA-устройства ``linked_device['name']`` — строка, не ``None``.

    ``DeviceData`` объявляет ``name: str``, и на этот контракт опираются
    все читатели (``_resolve_display_name``, ``_build_model_descriptor``).
    Устройство, у которого HA не знает ни ``name``, ни ``name_by_user``
    (типично для zigbee-узла, добавленного без имени), клало в словарь
    ``None`` — тип обещал одно, а в память попадало другое.

    Что ломается у пользователя, если тест упал: словарь снова разойдётся с
    собственным контрактом, и первый же читатель, который перестанет
    подстраховываться через ``or``, отправит Сберу ``name: null`` — облако
    молча отклонит устройство целиком.
    """
    device = MagicMock()
    device.id = "dev1"
    device.name = None
    device.name_by_user = None
    device.area_id = None
    device.manufacturer = None
    device.model = None
    device.model_id = None
    device.hw_version = None
    device.sw_version = None
    device.serial_number = None
    device.connections = set()

    device_reg = MagicMock()
    device_reg.async_get.side_effect = lambda did: {"dev1": device}.get(did)

    entry = MagicMock()
    entry.device_id = "dev1"

    sber_entity = LightEntity({"entity_id": "light.nameless", "device_id": "dev1"})
    SberEntityLoader._link_device_registry(sber_entity, entry, device_reg)

    assert sber_entity.linked_device is not None
    assert sber_entity.linked_device["name"] == ""
