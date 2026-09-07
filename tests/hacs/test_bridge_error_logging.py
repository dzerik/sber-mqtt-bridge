"""Тесты видимости ошибок обработчиков MQTT в DevTools message log.

Приход сообщения пишется в кольцевой буфер DevTools ДО диспетчеризации,
а падение обработчика раньше уходило только в лог Home Assistant. В панели
это выглядело как «команда пришла и ничего не произошло», и разбор такого
обращения всегда начинался с просьбы прислать логи HA.

Только внешняя граница (обработчик команд) подменяется моком; сам мост,
роутер и message log работают по-настоящему на фикстуре ``hass``.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sber_mqtt_bridge.const import (
    CONF_SBER_BROKER,
    CONF_SBER_LOGIN,
    CONF_SBER_PASSWORD,
    CONF_SBER_PORT,
    CONF_SBER_VERIFY_SSL,
    DOMAIN,
)
from custom_components.sber_mqtt_bridge.sber_bridge import SberBridge


def _make_entry(hass: HomeAssistant) -> MockConfigEntry:
    """Создать и зарегистрировать MockConfigEntry с учётными данными Sber."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_SBER_LOGIN: "test",
            CONF_SBER_PASSWORD: "pass",
            CONF_SBER_BROKER: "broker.test",
            CONF_SBER_PORT: 8883,
            CONF_SBER_VERIFY_SSL: False,
        },
        options={},
    )
    entry.add_to_hass(hass)
    return entry


async def test_handler_error_is_visible_in_message_log(hass: HomeAssistant) -> None:
    """Падение обработчика попадает в message log рядом с самим сообщением.

    Если тест упадёт — пользователь снова увидит в панели только строку
    «команда пришла», без единого следа ошибки, и причину сбоя нельзя будет
    выяснить без ручного чтения логов Home Assistant.
    """
    bridge = SberBridge(hass, _make_entry(hass))
    bridge._command_dispatcher.handle_command = AsyncMock(side_effect=ValueError("boom"))
    topic = f"{bridge._down_topic}/commands"

    # Роутер по-прежнему изолирует падение: исключение наружу не уходит.
    await bridge._handle_mqtt_message(topic, b"{}")

    errors = [m for m in bridge.message_log if m["direction"] == "error"]
    assert errors, "падение обработчика должно быть видно в message log"
    assert errors[0]["topic"] == topic, "ошибка должна быть привязана к своему топику"
    assert "ValueError" in errors[0]["payload"], "тип исключения нужен для диагностики"
    assert "boom" in errors[0]["payload"], "текст исключения нужен для диагностики"

    # Само сообщение осталось в логе — ошибка дополняет запись, а не заменяет её.
    assert any(m["direction"] == "in" and m["topic"] == topic for m in bridge.message_log)


async def test_successful_handler_writes_no_error_entry(hass: HomeAssistant) -> None:
    """Успешная команда не оставляет записей ``direction="error"``.

    Если тест упадёт — панель начнёт показывать ложные ошибки на штатном
    трафике, и настоящие сбои утонут в шуме.
    """
    bridge = SberBridge(hass, _make_entry(hass))
    bridge._command_dispatcher.handle_command = AsyncMock()

    await bridge._handle_mqtt_message(f"{bridge._down_topic}/commands", b"{}")

    assert not [m for m in bridge.message_log if m["direction"] == "error"]


async def test_cancellation_writes_no_error_entry(hass: HomeAssistant) -> None:
    """Отмена задачи — не ошибка обработчика и в лог не пишется.

    Если тест упадёт — каждая выгрузка интеграции будет засорять message log
    фальшивой «ошибкой обработчика» из-за штатной отмены MQTT-цикла.
    """
    bridge = SberBridge(hass, _make_entry(hass))
    bridge._command_dispatcher.handle_command = AsyncMock(side_effect=asyncio.CancelledError)

    with pytest.raises(asyncio.CancelledError):
        await bridge._handle_mqtt_message(f"{bridge._down_topic}/commands", b"{}")

    assert not [m for m in bridge.message_log if m["direction"] == "error"]
