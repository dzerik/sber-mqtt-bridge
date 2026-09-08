"""Панель: энергомониторинг розеток и реле (мощность, напряжение, ток).

Умные розетки и реле со счётчиком — единственные категории Sber, где
показания (`power`, `voltage`, `current`) приходят из Home Assistant
**отдельными сущностями** (`sensor.plug_power` и т.д.), а не атрибутами
выключателя.  На стороне панели это значит, что пользователь обязан их
увидеть и подтвердить — иначе он добавит розетку, в приложении Сбера не
будет расхода, и понять почему будет неоткуда.

Файл стережёт четыре вещи:

1. **Группировка.** Энергосенсоры вынимаются из общих списков
   «родные»/«совместимые» в отдельный блок мастера, куда попадают и
   сенсоры соседнего HA-устройства.  Если это сломается, три галочки
   растворятся среди батареи и уровня сигнала, и мастер перестанет
   отвечать на вопрос «а расход-то будет?».
2. **Подпись блока не врёт про галочки.** Текст «снимите галочку, чтобы
   исключить показание» осмыслен только когда галочки стоят.  Сенсор с
   соседнего HA-устройства приезжает `preselected: false`, а на
   многоканальной колодке бэкенд намеренно не преселектит ничего — и
   тогда подпись обязана просить *поставить* галочку, а не снять.
3. **Молчание там, где сказать нечего, и объяснение там, где есть.**
   Нужна ли строка «сенсоров не нашлось», решают присланные бэкендом
   `accepted_roles`, а не список категорий в панели: показания
   объявлены и у `socket`, и у `relay` (обе страницы документации Sber
   называют обе категории).  Недостающая роль называется по имени.
4. **Общий словарь ролей.** Роль показывается человеческим именем во
   всех трёх местах панели, где она вообще показывается (мастер, диалог
   привязок, карточка устройства), а сырой идентификатор остаётся в
   подсказке: именно он в логах, в payload'ах WebSocket и в
   документации Sber.

Плюс диалог привязок — единственная дорога для розеток, добавленных до
появления энергомониторинга: мастер их больше не пускает.  Он обязан
расставлять галочки по подсказке бэкенда (`preselected`), иначе вся
существующая база пользователей ищет три сенсора руками.

Проверки исполняют настоящий код панели в node: методы вынимаются из
шипящегося класса как есть и вызываются с подставным тегом ``html``,
который склеивает шаблон в строку.  Поэтому падение теста означает
поломку того, что увидит пользователь, а не расхождение с пересказом
исходника.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from custom_components.sber_mqtt_bridge.devices.base_entity import ALL_LINKABLE_ROLES

COMPONENT_ROOT = Path(__file__).resolve().parents[2] / "custom_components" / "sber_mqtt_bridge"
"""Корень интеграции."""

WWW = COMPONENT_ROOT / "www"
"""Корень SPA-панели (сборки нет — файлы отдаются браузеру как есть)."""

LINK_ROLES_JS = WWW / "link-roles.js"
"""Общий словарь ролей привязки: имена, группировка энергоролей."""

WIZARD_JS = WWW / "components" / "sber-wizard.js"
"""Мастер добавления устройства — там пользователь подтверждает сенсоры."""

LINK_DIALOG_JS = WWW / "components" / "sber-link-dialog.js"
"""Диалог привязок — единственный путь для уже добавленных устройств."""

NODE = shutil.which("node")
"""Путь к node: им исполняется настоящий JS панели."""

requires_node = pytest.mark.skipif(NODE is None, reason="node is not installed")
"""Пропуск проверок, которым нужно исполнить JS."""

ENERGY_ROLES = ("power", "voltage", "current")
"""Роли, из которых складывается энергомониторинг Sber."""

STRING_FILES = ("strings.json", "translations/en.json", "translations/ru.json")
"""Файлы строк, которые обязаны знать каждую новую строку панели."""

ROLE_LABEL_RE = re.compile(r"^  ([a-z0-9_]+): \(hass\) => t\(hass, \"link_role\.([a-z0-9_]+)\"\),$", re.MULTILINE)
"""Строка карты ролей в ``link-roles.js``: ``role: (hass) => t(hass, "link_role.role"),``."""

HTML_STUB = (
    "const _flat = (v) =>\n"
    "  Array.isArray(v)\n"
    "    ? v.map(_flat).join('')\n"
    "    : v === null || v === undefined || v === false\n"
    "      ? ''\n"
    "      : String(v);\n"
    "const html = (strings, ...values) =>\n"
    "  strings.reduce((acc, s, i) => acc + s + (i < values.length ? _flat(values[i]) : ''), '');\n"
)
"""Подставной тег ``html``: склеивает лит-шаблон в строку, как это сделал бы браузер.

Вложенные шаблоны уже строки, списки склеиваются рекурсивно, ``false``
и ``undefined`` исчезают — ровно так лит и рисует пустые ветки.
"""


ROLES_IMPORT = (
    'import * as roles from "./link-roles.js";\n'
    "const { acceptsEnergyRoles, linkRoleLabel, linkRoleNames, missingEnergyRoles, roleNames, "
    "splitEnergyLinks } = roles;\n"
)
"""Импорт словаря ролей через пространство имён, а не поимённо.

Поимённый импорт отсутствующего экспорта — ошибка связывания модуля:
node падает ещё до первой строки, и проверка сообщает «модуля нет»
вместо «панель ведёт себя не так».  Через пространство имён недостающая
функция становится ``undefined`` и роняет ровно тот вызов, который её
использует, — то есть тест по-прежнему красный, но по делу.
"""


def _read(rel: str) -> str:
    """Прочитать модуль панели.

    Args:
        rel: Путь относительно ``www``.

    Returns:
        Исходник модуля.
    """
    return (WWW / rel).read_text(encoding="utf-8")


def _method_span(src: str, name: str) -> tuple[int, int]:
    """Найти границы метода класса в исходнике компонента.

    Скобки считаются от конца строки сигнатуры, поэтому деструктуризация
    в параметрах счётчик не сбивает.

    Args:
        src: Исходник модуля.
        name: Имя метода.

    Returns:
        Пара «начало сигнатуры, конец тела».
    """
    match = re.search(rf"^  (?:async |get )?{re.escape(name)}\(.*\) \{{$", src, re.MULTILINE)
    assert match is not None, f"метод {name} не найден — тест проверяет не тот код"
    depth = 0
    start = match.end() - 1
    for i in range(start, len(src)):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return match.start(), i + 1
    raise AssertionError(f"не сбалансированы скобки метода {name}")


def _methods_as_object_body(src: str, names: list[str], optional: tuple[str, ...] = ()) -> str:
    """Вырезать методы класса и склеить их в тело объектного литерала.

    Так в node исполняется байт-в-байт тот код, который уедет в браузер,
    без поднятия LitElement и shadow DOM.

    Имена из ``optional`` берутся, только если они в исходнике есть.  Это
    не послабление, а условие честности проверки: методы-помощники,
    появившиеся вместе с исправлением, не должны превращать «панель
    ведёт себя не так» в «в панели нет такого метода».  Отсутствие
    помощника обязано проваливать тест на тексте, который увидит
    пользователь, — иначе тест не отличит поломку поведения от
    переименования.

    Args:
        src: Исходник компонента.
        names: Имена методов, без которых проверять нечего.
        optional: Имена, которые вырезаются при наличии.

    Returns:
        Текст для вставки внутрь ``{ ... }``.
    """
    parts = []
    for name in [*names, *optional]:
        if name in optional and not re.search(rf"^  {re.escape(name)}\(", src, re.MULTILINE):
            continue
        start, end = _method_span(src, name)
        parts.append(src[start:end].strip())
    return ",\n".join(parts) + ","


def _run_node(tmp_path: Path, driver: str) -> object:
    """Запустить драйвер рядом с копиями ``localize.js`` и ``link-roles.js``.

    Args:
        tmp_path: Временный каталог.
        driver: Текст ES-модуля, печатающего JSON в stdout.

    Returns:
        Разобранный JSON.
    """
    shutil.copy(WWW / "localize.js", tmp_path / "localize.js")
    shutil.copy(LINK_ROLES_JS, tmp_path / "link-roles.js")
    entry = tmp_path / "driver.mjs"
    entry.write_text(driver, encoding="utf-8")
    proc = subprocess.run(  # noqa: S603 - фиксированный argv, без shell
        [str(NODE), "driver.mjs"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    return json.loads(proc.stdout)


# Устройство-образец: розетка Zigbee со счётчиком, у которой мощность,
# напряжение и ток — отдельные сущности, а ток вдобавок приехал с
# соседнего HA-устройства (частый случай у Shelly и Tuya).
DEVICE = {
    "device_id": "dev1",
    "primary": {"entity_id": "switch.plug"},
    "accepted_roles": ["power", "voltage", "current"],
    "linked_native": [
        {"entity_id": "sensor.plug_battery", "link_role": "battery"},
        {"entity_id": "sensor.plug_power", "link_role": "power"},
        {"entity_id": "sensor.plug_voltage", "link_role": "voltage"},
        {"entity_id": "sensor.plug_rssi", "link_role": "signal_strength"},
    ],
    "linked_compatible": [
        {
            "entity_id": "sensor.meter_current",
            "link_role": "current",
            "origin_device_name": "Счётчик",
        },
        {"entity_id": "sensor.room_temp", "link_role": "temperature"},
    ],
}

GROUPING_METHODS = ["_partitionLinks", "_selectedLinksOf"]
"""Разбор списков сенсоров — то, что было в мастере и до энергомониторинга."""

SECTION_METHODS = [*GROUPING_METHODS, "_renderEnergySection"]
"""Всё, что нужно, чтобы нарисовать энергоблок."""

STEP3_METHODS = [*GROUPING_METHODS, "_renderStep3"]
"""Всё, что нужно, чтобы нарисовать сводку последнего шага."""


def _wizard_driver(
    body: str,
    *,
    device: dict = DEVICE,
    category: str = "socket",
    methods: list[str] = GROUPING_METHODS,
    optional: tuple[str, ...] = (),
) -> str:
    """Собрать драйвер с настоящими методами мастера.

    Подставляется только то, что в браузере даёт LitElement: тег
    ``html``, строка сенсора и форма имени.  Сама логика — настоящая.

    Args:
        body: Хвост драйвера, печатающий JSON.
        device: Описание устройства от бэкенда.
        category: Выбранная в мастере категория Sber.
        methods: Методы мастера, нужные проверке.
        optional: Методы, которые берутся при наличии.

    Returns:
        Текст ES-модуля.
    """
    body_js = _methods_as_object_body(WIZARD_JS.read_text(encoding="utf-8"), methods, optional)
    primary = device["primary"]["entity_id"]
    return (
        ROLES_IMPORT
        + 'import { t } from "./localize.js";\n'
        + HTML_STUB
        + f"const device = {json.dumps(device, ensure_ascii=False)};\n"
        f"const wizard = {{\n"
        "  hass: null,\n"
        f"  _selectedCategory: {json.dumps(category)},\n"
        "  _enabledLinks: new Set(),\n"
        f"  _devices: [device],\n"
        f"  _selectedDeviceId: {json.dumps(device['device_id'])},\n"
        f"  _selectedPrimaries: [{json.dumps(primary)}],\n"
        f"  _pendingPrimaries: [{json.dumps(primary)}],\n"
        "  _categories: [],\n"
        "  _perPrimary: {},\n"
        "  _added: new Set(),\n"
        "  _failed: [],\n"
        "  _renderLinkRow(dev, link) { return `[row:${link.entity_id}]`; },\n"
        "  _renderPrimaryForm() { return '[form]'; },\n"
        f"  {body_js}\n"
        "};\n"
        "const energy = () => wizard._partitionLinks(device).energy;\n" + body
    )


def _render_energy(
    tmp_path: Path, *, device: dict = DEVICE, ticked: list[str] | None = None, category: str = "socket"
) -> str:
    """Отрисовать энергоблок мастера настоящим кодом панели.

    Args:
        tmp_path: Временный каталог.
        device: Описание устройства от бэкенда.
        ticked: Сущности, у которых стоит галочка.
        category: Выбранная категория Sber.

    Returns:
        Разметка блока (пустая строка, если блок не рисуется).
    """
    driver = _wizard_driver(
        f"wizard._enabledLinks = new Set({json.dumps(ticked or [], ensure_ascii=False)});\n"
        "console.log(JSON.stringify(wizard._renderEnergySection(device, energy())));\n",
        device=device,
        category=category,
        methods=SECTION_METHODS,
        optional=("_isVirtualDevice",),
    )
    out = _run_node(tmp_path, driver)
    assert isinstance(out, str)
    return out


def _render_step3(
    tmp_path: Path, *, device: dict = DEVICE, ticked: list[str] | None = None, category: str = "socket"
) -> str:
    """Отрисовать сводку последнего шага мастера настоящим кодом панели.

    Args:
        tmp_path: Временный каталог.
        device: Описание устройства от бэкенда.
        ticked: Сущности, у которых стоит галочка.
        category: Выбранная категория Sber.

    Returns:
        Разметка шага подтверждения.
    """
    driver = _wizard_driver(
        f"wizard._enabledLinks = new Set({json.dumps(ticked or [], ensure_ascii=False)});\n"
        "console.log(JSON.stringify(wizard._renderStep3()));\n",
        device=device,
        category=category,
        methods=STEP3_METHODS,
        optional=("_energySummary",),
    )
    out = _run_node(tmp_path, driver)
    assert isinstance(out, str)
    return out


def _text(name: str, key: str) -> str:
    """Взять строку панели из файла переводов.

    Args:
        name: Файл строк, например ``translations/en.json``.
        key: Путь вида ``wizard.energy_hint``.

    Returns:
        Текст строки.
    """
    block, _, leaf = key.partition(".")
    return json.loads((COMPONENT_ROOT / name).read_text(encoding="utf-8"))["config_panel"][block][leaf]


def _en(key: str) -> str:
    """Английский текст строки панели (её и рисует драйвер без ``hass``).

    Args:
        key: Путь вида ``wizard.energy_hint``.

    Returns:
        Текст строки из ``translations/en.json``.
    """
    return _text("translations/en.json", key)


class TestEnergySensorsAreGrouped:
    """Мастер обязан собрать показания счётчика в один блок."""

    @requires_node
    def test_energy_roles_leave_the_generic_sensor_lists(self, tmp_path: Path) -> None:
        """Мощность, напряжение и ток уходят из общих списков в свой блок.

        Если тест упадёт, три галочки энергомониторинга снова
        размажутся между «родными сенсорами» (рядом с батареей и
        уровнем сигнала) и «совместимыми сенсорами с других
        устройств».  Пользователь, добавляющий розетку именно ради
        расхода, перестанет видеть, нашлись ли нужные сенсоры вообще —
        а это и есть та причина, по которой он держал вторую
        интеграцию.
        """
        out = _run_node(
            tmp_path,
            _wizard_driver("console.log(JSON.stringify(wizard._partitionLinks(device)));"),
        )

        assert [link["link_role"] for link in out["energy"]] == ["power", "voltage", "current"]
        assert [link["link_role"] for link in out["native"]] == ["battery", "signal_strength"]
        assert [link["link_role"] for link in out["compatible"]] == ["temperature"]

    @requires_node
    def test_cross_device_energy_sensor_keeps_its_origin(self, tmp_path: Path) -> None:
        """Сенсор с соседнего устройства не теряет пометку происхождения.

        Ток у Shelly и Tuya часто висит на отдельном HA-устройстве.
        Перенос такого сенсора в общий энергоблок не должен стирать
        ``origin_device_name`` — иначе в мастере появится галочка без
        объяснения, откуда взялась эта сущность, и пользователь не
        отличит её от родного сенсора розетки.
        """
        out = _run_node(
            tmp_path,
            _wizard_driver("console.log(JSON.stringify(wizard._partitionLinks(device)));"),
        )

        current = next(link for link in out["energy"] if link["link_role"] == "current")
        assert current["origin_device_name"] == "Счётчик"

    @requires_node
    def test_device_without_energy_sensors_yields_an_empty_group(self, tmp_path: Path) -> None:
        """Без энергоролей группа пуста, а остальные списки целы.

        Это состояние — не редкость, а норма: так выглядит любая
        категория без счётчика, и так же выглядит розетка, пока
        бэкенд не научился энергоролям.  Пустая группа обязана
        оставить мастер работоспособным, иначе релиз панели вперёд
        бэкенда ломает добавление устройств целиком.
        """
        plain = {
            "device_id": "dev2",
            "primary": {"entity_id": "light.lamp"},
            "accepted_roles": ["battery"],
            "linked_native": [{"entity_id": "sensor.lamp_battery", "link_role": "battery"}],
            "linked_compatible": [],
        }
        out = _run_node(
            tmp_path,
            _wizard_driver(
                "console.log(JSON.stringify(wizard._partitionLinks(device)));",
                device=plain,
            ),
        )

        assert out["energy"] == []
        assert [link["link_role"] for link in out["native"]] == ["battery"]


class TestEnergyCaptionMatchesTheCheckboxes:
    """Подпись блока обязана описывать то состояние галочек, что видно."""

    @requires_node
    def test_caption_asks_for_a_tick_when_nothing_is_selected(self, tmp_path: Path) -> None:
        """Пока ни одна галочка не стоит, подпись просит их поставить.

        Именно так выглядит флагманский случай фичи: ток на соседнем
        HA-устройстве (Shelly, Tuya) приезжает ``preselected: false``,
        а на многоканальной колодке бэкенд не преселектит ни одного
        сенсора.  Если подпись при этом скажет «сенсоры найдены,
        снимите галочку, чтобы исключить показание», пользователь ей
        поверит, ничего не тронет и уйдёт из мастера без
        энергомониторинга — ровно то, из-за чего он держал вторую
        интеграцию.
        """
        rendered = _render_energy(tmp_path, ticked=[])

        assert _en("wizard.energy_unlinked") in rendered
        assert _en("wizard.energy_hint") not in rendered

    @requires_node
    def test_caption_explains_unticking_once_something_is_selected(self, tmp_path: Path) -> None:
        """Как только галочка стоит, подпись объясняет, как исключить показание.

        Обратная половина той же честности: с отмеченными сенсорами
        просьба «отметьте, что передавать» бессмысленна и сбивает с
        толку — пользователь начнёт искать, где же отметить.
        """
        rendered = _render_energy(tmp_path, ticked=["sensor.plug_power"])

        assert _en("wizard.energy_hint") in rendered
        assert _en("wizard.energy_unlinked") not in rendered

    @requires_node
    def test_missing_reading_is_named(self, tmp_path: Path) -> None:
        """Ненайденное показание названо, а не пропущено молча.

        Zigbee-прошивки часто отдают мощность и напряжение, но не ток.
        Две галочки без единого слова о третьем показании выглядят как
        «всё нашлось», и вопрос «почему в приложении нет тока?»
        задаётся уже после добавления.  Панель обязана назвать
        недостающую роль по имени, взяв её из ``accepted_roles``.
        """
        partial = {
            **DEVICE,
            "linked_compatible": [{"entity_id": "sensor.room_temp", "link_role": "temperature"}],
        }
        rendered = _render_energy(tmp_path, device=partial, ticked=["sensor.plug_power"])

        assert "Current" in rendered
        assert _en("wizard.energy_missing").split("{")[0] in rendered

    @requires_node
    def test_nothing_is_declared_missing_when_all_readings_are_there(self, tmp_path: Path) -> None:
        """Полный комплект показаний не вызывает строку «не нашлось».

        Лишняя строка про отсутствие того, что на самом деле нашлось, —
        такая же ложь, как и молчание о недостающем, и обесценивает
        предупреждение там, где оно нужно.
        """
        rendered = _render_energy(tmp_path, ticked=["sensor.plug_power"])

        assert _en("wizard.energy_missing").split("{")[0] not in rendered


class TestEnergySectionDegradesGracefully:
    """Блок объясняется там, где показания возможны, и молчит везде ещё."""

    @requires_node
    def test_section_is_silent_for_a_device_that_takes_no_readings(self, tmp_path: Path) -> None:
        """У устройства без энергоролей блока нет вовсе.

        Заголовок «Энергомониторинг» над пустотой в мастере лампочки
        выглядит как поломка интеграции и провоцирует обращения в
        поддержку.
        """
        lamp = {
            "device_id": "dev2",
            "primary": {"entity_id": "light.lamp"},
            "accepted_roles": ["battery", "signal_strength"],
            "linked_native": [],
            "linked_compatible": [],
        }
        assert _render_energy(tmp_path, device=lamp, category="light") == ""

    @requires_node
    def test_metering_relay_without_sensors_gets_the_explanation(self, tmp_path: Path) -> None:
        """Реле со счётчиком объясняется наравне с розеткой.

        Обе страницы документации Sber (`power`, `voltage`, `current`)
        называют в «Устройства с этой функцией» и `socket`, и `relay`,
        а бэкенд вешает энергороли на ``RelayEntity``.  Пока панель
        решала по своему списку категорий (`["socket"]`), владелец
        Shelly 1PM или Sonoff POW, выставленного как реле, не получал
        ни объяснения, ни подсказки — блок просто не рисовался.
        Решение обязано приниматься по ``accepted_roles`` от бэкенда.
        """
        relay = {
            "device_id": "dev3",
            "primary": {"entity_id": "switch.boiler"},
            "accepted_roles": ["power", "voltage", "current"],
            "linked_native": [],
            "linked_compatible": [],
        }
        rendered = _render_energy(tmp_path, device=relay, category="relay")

        assert _en("wizard.energy_none") in rendered
        assert _en("wizard.energy_sensors") in rendered

    @requires_node
    def test_orphan_entity_is_not_sent_to_a_dead_end(self, tmp_path: Path) -> None:
        """Сущности без HA-устройства не советуют «привязать позже».

        Template-switch, SmartIR и прочие «сироты» попадают в мастер
        как виртуальное устройство, у которого ``device_id`` — это сам
        ``entity_id``.  ``ws_suggest_links`` для такой сущности выходит
        раньше и отдаёт пустой список кандидатов, так что совет
        «привязать позже из строки устройства» ведёт в диалог, где
        ничего нет.  Текст обязан быть другим.
        """
        orphan = {
            "device_id": "switch.template_plug",
            "primary": {"entity_id": "switch.template_plug"},
            "accepted_roles": ["power", "voltage", "current"],
            "linked_native": [],
            "linked_compatible": [],
        }
        rendered = _render_energy(tmp_path, device=orphan)

        assert _en("wizard.energy_none_orphan") in rendered
        assert _en("wizard.energy_none") not in rendered

    @requires_node
    def test_old_backend_without_accepted_roles_says_nothing(self, tmp_path: Path) -> None:
        """Без ``accepted_roles`` панель молчит, а не выдумывает.

        Панель отдаётся браузеру без сборки и переживает кэш: она может
        оказаться новее бэкенда.  Утверждать «сенсоров не нашлось» на
        ответе, где список принимаемых ролей вообще не присылали, —
        значит показать выдумку; правильное поведение — тишина.
        """
        legacy = {
            "device_id": "dev4",
            "primary": {"entity_id": "switch.plug"},
            "linked_native": [],
            "linked_compatible": [],
        }
        assert _render_energy(tmp_path, device=legacy) == ""

    @requires_node
    def test_summary_lists_only_the_readings_still_checked(self, tmp_path: Path) -> None:
        """Итоговый шаг перечисляет только те показания, что остались отмечены.

        Мастер разрешает снять галочку с показания.  Если сводка
        перестанет это учитывать, она пообещает пользователю расход,
        которого в приложении не появится, — худший вид расхождения
        между интерфейсом и реальностью.
        """
        rendered = _render_step3(tmp_path, ticked=["sensor.plug_power", "sensor.meter_current"])

        assert f"{_en('wizard.summary_energy')}</b> Power, Current" in rendered

    @requires_node
    def test_summary_says_none_selected_instead_of_keeping_quiet(self, tmp_path: Path) -> None:
        """На шаге подтверждения пустой выбор назван вслух.

        Молчание на последнем шаге читается как «всё в порядке»:
        пользователь жмёт «Добавить» и обнаруживает отсутствие расхода
        уже в приложении Сбера, где чинить это некому.  Строка
        «Энергомониторинг: не выбрано» — последнее место, где решение
        ещё можно поправить, и оно нужно именно в том случае, когда
        бэкенд ничего не преселектил: колодка на несколько розеток,
        сенсор с соседнего HA-устройства.
        """
        rendered = _render_step3(tmp_path, ticked=[])

        assert f"{_en('wizard.summary_energy')}</b> {_en('wizard.summary_energy_none')}" in rendered

    @requires_node
    def test_summary_line_is_absent_where_no_reading_was_possible(self, tmp_path: Path) -> None:
        """У лампы строки об энергомониторинге на шаге 3 нет.

        Строка обязана исчезать, а не превращаться в «не выбрано» у
        каждой лампочки: иначе предупреждение перестанет что-либо
        значить именно там, где оно важно.
        """
        lamp = {
            "device_id": "dev2",
            "name": "Лампа",
            "primary": {"entity_id": "light.lamp"},
            "accepted_roles": ["battery"],
            "linked_native": [],
            "linked_compatible": [],
        }
        rendered = _render_step3(tmp_path, device=lamp, category="light")

        assert _en("wizard.summary_energy") not in rendered


def _dialog_driver(body: str, *, result: dict) -> str:
    """Собрать драйвер с настоящими методами диалога привязок.

    Args:
        body: Хвост драйвера, печатающий JSON.
        result: Ответ ``suggest_links`` от бэкенда.

    Returns:
        Текст ES-модуля.
    """
    methods = _methods_as_object_body(
        LINK_DIALOG_JS.read_text(encoding="utf-8"),
        ["_loadCandidates", "_renderCandidates", "_renderCandidateRow"],
        ("_rolesWithoutCandidate", "_renderUnfilledRoles"),
    )
    return (
        ROLES_IMPORT
        + 'import { t } from "./localize.js";\n'
        + HTML_STUB
        + f"const result = {json.dumps(result, ensure_ascii=False)};\n"
        "const dialog = {\n"
        "  hass: { callWS: async () => result },\n"
        "  _entityId: 'switch.plug',\n"
        "  _candidates: [],\n"
        "  _acceptedRoles: [],\n"
        "  _selected: {},\n"
        "  _loading: false,\n"
        "  _error: '',\n"
        f"  {methods}\n"
        "};\n" + body
    )


class TestLinkDialogFollowsTheBackendSuggestion:
    """Диалог привязок — единственная дорога для уже добавленных розеток."""

    @requires_node
    def test_suggested_energy_sensors_start_ticked(self, tmp_path: Path) -> None:
        """Подсказанные бэкендом сенсоры сразу отмечены.

        Розетку, добавленную до появления энергомониторинга, мастер
        больше не пускает: она уже выставлена.  Диалог привязок —
        единственное место, где ей можно дать мощность, напряжение и
        ток.  Если он не читает ``preselected``, вся существующая база
        пользователей обязана найти три сенсора вручную среди всех
        сущностей устройства — чего никто не делает, и энергомониторинг
        для них не появляется вовсе.
        """
        result = {
            "category": "socket",
            "allowed_roles": ["power", "voltage"],
            "accepted_roles": ["power", "voltage", "current"],
            "candidates": [
                {
                    "entity_id": "sensor.plug_power",
                    "suggested_role": "power",
                    "compatible": True,
                    "currently_linked": False,
                    "linked_role": "",
                    "preselected": True,
                    "friendly_name": "Power",
                },
                {
                    "entity_id": "sensor.plug_voltage",
                    "suggested_role": "voltage",
                    "compatible": True,
                    "currently_linked": False,
                    "linked_role": "",
                    "preselected": False,
                    "friendly_name": "Voltage",
                },
            ],
        }
        out = _run_node(
            tmp_path,
            _dialog_driver(
                "await dialog._loadCandidates();\nconsole.log(JSON.stringify(Object.keys(dialog._selected).sort()));\n",
                result=result,
            ),
        )

        assert out == ["sensor.plug_power"]

    @requires_node
    def test_manual_link_wins_over_a_suggestion_for_the_same_role(self, tmp_path: Path) -> None:
        """Сохранённая привязка сильнее подсказки на ту же роль.

        Роль хранится в одном экземпляре: сохранение свернёт две
        галочки одной роли в одну, и выиграет случайная.  Выбор
        пользователя обязан пережить открытие диалога, иначе
        сохранение молча подменит его сенсор на подсказанный.
        """
        result = {
            "category": "socket",
            "allowed_roles": ["power"],
            "accepted_roles": ["power"],
            "candidates": [
                {
                    "entity_id": "sensor.clamp_power",
                    "suggested_role": "power",
                    "compatible": True,
                    "currently_linked": True,
                    "linked_role": "power",
                    "preselected": False,
                    "friendly_name": "Clamp",
                },
                {
                    "entity_id": "sensor.plug_power",
                    "suggested_role": "power",
                    "compatible": True,
                    "currently_linked": False,
                    "linked_role": "",
                    "preselected": True,
                    "friendly_name": "Plug power",
                },
            ],
        }
        out = _run_node(
            tmp_path,
            _dialog_driver(
                "await dialog._loadCandidates();\nconsole.log(JSON.stringify(Object.keys(dialog._selected)));\n",
                result=result,
            ),
        )

        assert out == ["sensor.clamp_power"]

    @requires_node
    def test_roles_nobody_can_fill_are_named(self, tmp_path: Path) -> None:
        """Роли, под которые нет ни одного кандидата, названы в диалоге.

        ``accepted_roles`` — полный список слотов устройства, и разница
        между ним и кандидатами есть честный ответ на «почему в
        приложении нет тока»: привязывать нечего, и сколько диалог ни
        листай, сенсор не появится.  Без этой строки поле, которое
        бэкенд отдаёт специально ради неё, не используется вовсе.
        """
        result = {
            "category": "socket",
            "allowed_roles": ["power"],
            "accepted_roles": ["power", "voltage", "current"],
            "candidates": [
                {
                    "entity_id": "sensor.plug_power",
                    "suggested_role": "power",
                    "compatible": True,
                    "currently_linked": False,
                    "linked_role": "",
                    "preselected": True,
                    "friendly_name": "Power",
                },
            ],
        }
        rendered = _run_node(
            tmp_path,
            _dialog_driver(
                "await dialog._loadCandidates();\nconsole.log(JSON.stringify(dialog._renderCandidates()));\n",
                result=result,
            ),
        )

        assert "Voltage, Current" in rendered

    @requires_node
    def test_complete_device_gets_no_unfilled_footer(self, tmp_path: Path) -> None:
        """Когда все слоты заполнимы, лишней строки нет.

        Сообщение о недостающих ролях под каждым устройством перестало
        бы читаться — а оно нужно ровно там, где чего-то нет.
        """
        result = {
            "category": "socket",
            "allowed_roles": ["power"],
            "accepted_roles": ["power"],
            "candidates": [
                {
                    "entity_id": "sensor.plug_power",
                    "suggested_role": "power",
                    "compatible": True,
                    "currently_linked": False,
                    "linked_role": "",
                    "preselected": True,
                    "friendly_name": "Power",
                },
            ],
        }
        rendered = _run_node(
            tmp_path,
            _dialog_driver(
                "await dialog._loadCandidates();\nconsole.log(JSON.stringify(dialog._renderCandidates()));\n",
                result=result,
            ),
        )

        assert _en("link.roles_unfilled").split("{")[0] not in rendered


# Каждый случай: (модуль, метод, JS-выражение вызова со своей нагрузкой).
# Нагрузка везде описывает одно и то же — сенсор мощности в роли
# ``power``, — чтобы разметка трёх мест сравнивалась с одним эталоном.
SURFACES = [
    (
        "components/sber-wizard.js",
        "_renderLinkRow",
        "surface._renderLinkRow({}, {entity_id: 'sensor.plug_power', link_role: 'power', "
        "friendly_name: 'Plug power'}, false)",
    ),
    (
        "components/sber-link-dialog.js",
        "_renderCandidateRow",
        "surface._renderCandidateRow({entity_id: 'sensor.plug_power', suggested_role: 'power', "
        "compatible: true, friendly_name: 'Plug power'})",
    ),
    (
        "components/sber-detail-dialog.js",
        "_renderLinkedEntities",
        "surface._renderLinkedEntities({linked_entities: [{role: 'power', "
        "entity_id: 'sensor.plug_power', friendly_name: 'Plug power', state: '42'}]})",
    ),
]
"""Три места панели, где роль вообще показывается пользователю."""


class TestRoleVocabularyIsShared:
    """Роль показывается человеческим именем везде и одинаково."""

    def test_every_backend_role_has_a_panel_name(self) -> None:
        """Каждая роль из ``ALL_LINKABLE_ROLES`` названа в панели.

        Реестр ролей на бэкенде выводится автоматически, а панель —
        нет: роль, добавленная в ``base_entity.py`` и забытая здесь,
        доедет до пользователя сырым идентификатором (``hcho``,
        ``open_state``) в диалоге привязок.  Тест связывает два списка,
        чтобы забыть было нельзя.
        """
        declared = {role.role for role in ALL_LINKABLE_ROLES}
        named = {match.group(1) for match in ROLE_LABEL_RE.finditer(LINK_ROLES_JS.read_text(encoding="utf-8"))}

        assert named, "карта имён ролей не разобралась — проверка стала бы всегда зелёной"
        assert sorted(declared - named) == []

    def test_role_key_matches_the_role_name(self) -> None:
        """Ключ перевода совпадает с именем роли.

        Опечатка вида ``power: (hass) => t(hass, "link_role.powr")``
        прошла бы сторожа переводов (ключ существует), но показала бы
        не ту подпись.  Здесь сверяются обе половины строки карты.
        """
        pairs = ROLE_LABEL_RE.findall(LINK_ROLES_JS.read_text(encoding="utf-8"))

        assert pairs
        assert [role for role, key in pairs if role != key] == []

    @pytest.mark.parametrize("role", ENERGY_ROLES)
    @pytest.mark.parametrize("name", STRING_FILES)
    def test_energy_role_is_translated(self, role: str, name: str) -> None:
        """Имя энергороли есть во всех файлах строк.

        Недостающий ключ в ``ru.json`` — английское слово посреди
        русского диалога, недостающий в ``en.json`` — сырое
        ``link_role.current`` у всех.
        """
        panel = json.loads((COMPONENT_ROOT / name).read_text(encoding="utf-8"))["config_panel"]
        roles = panel.get("link_role", {})

        assert role in roles, f"{name}: нет config_panel.link_role.{role}"
        assert roles[role].strip()

    @requires_node
    @pytest.mark.parametrize(("path", "method", "call"), SURFACES)
    def test_surfaces_render_the_shared_label(self, tmp_path: Path, path: str, method: str, call: str) -> None:
        """Все три места панели рисуют роль одинаково: имя + сырой id в подсказке.

        Пока каждое место печатало ``link.link_role`` само, энергия
        неизбежно стала бы четвёртым частным случаем, и `power`
        показался бы пользователю сырым словом там, где `battery`
        показывается «Батареей».  Сравнивается результат рендера, а не
        текст исходника: разметка обязана содержать и человеческое имя,
        и идентификатор в ``title`` — по нему пользователь свяжет
        увиденное с логами и документацией Sber.
        """
        src = _read(path)
        start, end = _method_span(src, method)
        driver = (
            ROLES_IMPORT + 'import { t } from "./localize.js";\n' + HTML_STUB + "const surface = {\n"
            "  hass: null,\n"
            "  _enabledLinks: new Set(),\n"
            "  _selected: {},\n"
            f"  {src[start:end].strip()},\n"
            "};\n"
            f"console.log(JSON.stringify({call}));\n"
        )
        rendered = _run_node(tmp_path, driver)

        assert isinstance(rendered, str)
        assert 'title="power">Power<' in rendered, f"{path}::{method} рисует роль в обход общего словаря"

    @requires_node
    def test_unknown_role_still_renders_something_readable(self, tmp_path: Path) -> None:
        """Роль, которой панель не знает, показывается идентификатором.

        Бэкенд может обогнать панель (у пользователя обновилась
        интеграция, а браузер держит старый кэш модулей).  Показать
        сырое имя роли — приемлемо; уронить рендер диалога привязок
        или показать пустую плашку — нет.
        """
        driver = (
            'import { linkRoleLabel } from "./link-roles.js";\n'
            "console.log(JSON.stringify({\n"
            "  known: linkRoleLabel(null, 'power'),\n"
            "  unknown: linkRoleLabel(null, 'flux_capacitance'),\n"
            "  fallback: linkRoleLabel(null, null, 'illuminance'),\n"
            "  nothing: linkRoleLabel(null, null, null),\n"
            "}));\n"
        )
        out = _run_node(tmp_path, driver)

        assert out["known"] == {"text": "Power", "hint": "power"}
        assert out["unknown"] == {"text": "flux_capacitance", "hint": ""}
        assert out["fallback"] == {"text": "illuminance", "hint": ""}
        assert out["nothing"]["text"] == "?"
