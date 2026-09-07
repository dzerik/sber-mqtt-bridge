"""AUTO-GENERATED from tests/hacs/__snapshots__/sber_full_spec.json.

DO NOT EDIT BY HAND.  Regenerate with:

    python tools/codegen.py

Source: https://developers.sber.ru/docs/ru/smarthome/c2c
Spec generated at: 2026-09-07T15:07:37.367121+00:00
"""

from __future__ import annotations

FEATURE_TITLES_RU: dict[str, str] = {
    "air_pressure": "текущее атмосферное давление",
    "alarm_mute": "выключено ли звуковое оповещение",
    "battery_low_power": "разряжена батарея или нет",
    "battery_percentage": "уровень заряда батареи",
    "button_10_event": "нажатие на десятую кнопку",
    "button_1_event": "нажатие на первую кнопку",
    "button_2_event": "нажатие на вторую кнопку",
    "button_3_event": "нажатие на третью кнопку",
    "button_4_event": "нажатие на четвертую кнопку",
    "button_5_event": "нажатие на пятую кнопку",
    "button_6_event": "нажатие на шестую кнопку",
    "button_7_event": "нажатие на седьмую кнопку",
    "button_8_event": "нажатие на восьмую кнопку",
    "button_9_event": "нажатие на девятую кнопку",
    "button_bottom_left_event": "нажатие на левую нижнюю кнопку",
    "button_bottom_right_event": "нажатие на правую нижнюю кнопку",
    "button_event": "нажатие на кнопку",
    "button_left_event": "нажатие на левую кнопку",
    "button_right_event": "нажатие на правую кнопку",
    "button_top_left_event": "нажатие на левую верхнюю кнопку",
    "button_top_right_event": "нажатие на правую верхнюю кнопку",
    "channel": "включение предыдущего или следующего канала",
    "channel_int": "номер канала",
    "child_lock": "блокировка от детей",
    "co2": "концентрация углекислого газа",
    "current": "текущий ток",
    "custom_key": "кнопка на пульте",
    "direction": "сдвиг курсора в нужном направлении",
    "doorcontact_state": "разомкнуты или сомкнуты контакты датчика",
    "gas_leak_state": "обнаружена ли утечка газа",
    "hcho_float": "концентрация соединений частиц формальдегида",
    "humidity": "текущая влажность",
    "hvac_air_flow_direction": "направление потока воздуха",
    "hvac_air_flow_power": "скорость вентиляторов",
    "hvac_aromatization": "режим ароматизации воздуха",
    "hvac_decontaminate": "режим обеззараживания воздуха",
    "hvac_direction_set": "направление вентилятора",
    "hvac_heating_rate": "скорость нагрева",
    "hvac_humidity_set": "целевая влажность воздуха",
    "hvac_ionization": "режим ионизации",
    "hvac_night_mode": "ночной режим работы",
    "hvac_replace_filter": "нужно ли менять фильтр",
    "hvac_replace_ionizator": "нужно ли менять ионизатор",
    "hvac_temp_set": "целевая температура",
    "hvac_thermostat_mode": "режим работы термостата",
    "hvac_water_level": "количество воды в баке в литрах",
    "hvac_water_low_level": "закончилась ли вода в баке",
    "hvac_water_percentage": "количество воды в баке в процентах",
    "hvac_work_mode": "режим работы",
    "incoming_call": "поступает ли вызов на домофон",
    "kitchen_water_level": "количество воды в устройстве в литрах",
    "kitchen_water_low_level": "закончилась ли вода",
    "kitchen_water_temperature": "текущая температура воды",
    "kitchen_water_temperature_set": "целевая температура воды",
    "light_brightness": "яркость",
    "light_colour": "цвет",
    "light_colour_temp": "температура цвета",
    "light_mode": "режим цвета",
    "light_transmission_percentage": "степень пропускания света в процентах",
    "mute": "бесшумный режим",
    "number": "нажатая на пульте цифровая кнопка",
    "on_off": "удаленное включение и выключение устройства",
    "online": "доступность устройства",
    "open_left_percentage": "открывание левой половины в процентах",
    "open_left_set": "открывание левой половины",
    "open_left_state": "статус открывания левой стороны",
    "open_percentage": "открывание в процентах",
    "open_rate": "скорость открывания",
    "open_right_percentage": "открывание правой половины в процентах",
    "open_right_set": "открывание правой половины",
    "open_right_state": "статус открывания правой стороны",
    "open_set": "открывание",
    "open_state": "статус открывания",
    "pir": "обнаружено ли движение",
    "pm10": "концентрация твердых крупных частиц, крупной пыли",
    "pm1_0": "концентрация микрочастиц, мельчайших частиц",
    "pm2_5": "концентрация твердых мелких частиц, мелкой пыли",
    "power": "текущая мощность",
    "reject_call": "отклонить вызов",
    "sensor_sensitive": "чувствительность датчика",
    "signal_strength": "сила сигнала",
    "smoke_state": "обнаружено ли задымление",
    "source": "источник видеосигнала",
    "tamper_alarm": "сигнализация о вскрытии",
    "temp_unit_view": "температурная шкала для вывода информации",
    "temperature": "текущая температура",
    "tvoc_float": "общая концентрация летучих органических веществ",
    "unlock": "открыть замок",
    "vacuum_cleaner_cleaning_type": "тип уборки",
    "vacuum_cleaner_command": "команда управления уборкой",
    "vacuum_cleaner_program": "программа уборки",
    "vacuum_cleaner_status": "статус устройства",
    "voltage": "текущее напряжение",
    "volume": "сделать тише или громче",
    "volume_int": "уровень громкости",
    "water_leak_state": "обнаружена ли протечка",
}
"""Feature name → Sber's own Russian label for it.

Straight off each function page's heading — ``light_colour
(цвет)``.  The panel shows protocol slugs today; these are the
words the Salute app uses for the very same feature, so a user
reading our wizard and their phone sees one vocabulary instead of
two."""


FEATURE_ENUM_LABELS: dict[str, dict[str, str]] = {
    "button_10_event": {
        "click": "однократное нажатие",
        "double_click": "двойное нажатие",
        "long_press": "долгое нажатие",
    },
    "button_1_event": {
        "click": "однократное нажатие",
        "double_click": "двойное нажатие",
        "long_press": "долгое нажатие",
    },
    "button_2_event": {
        "click": "однократное нажатие",
        "double_click": "двойное нажатие",
        "long_press": "долгое нажатие",
    },
    "button_3_event": {
        "click": "однократное нажатие",
        "double_click": "двойное нажатие",
        "long_press": "долгое нажатие",
    },
    "button_4_event": {
        "click": "однократное нажатие",
        "double_click": "двойное нажатие",
        "long_press": "долгое нажатие",
    },
    "button_5_event": {
        "click": "однократное нажатие",
        "double_click": "двойное нажатие",
        "long_press": "долгое нажатие",
    },
    "button_6_event": {
        "click": "однократное нажатие",
        "double_click": "двойное нажатие",
        "long_press": "долгое нажатие",
    },
    "button_7_event": {
        "click": "однократное нажатие",
        "double_click": "двойное нажатие",
        "long_press": "долгое нажатие",
    },
    "button_8_event": {
        "click": "однократное нажатие",
        "double_click": "двойное нажатие",
        "long_press": "долгое нажатие",
    },
    "button_9_event": {
        "click": "однократное нажатие",
        "double_click": "двойное нажатие",
        "long_press": "долгое нажатие",
    },
    "button_bottom_left_event": {
        "click": "однократное нажатие",
        "double_click": "двойное нажатие",
        "long_press": "долгое нажатие",
    },
    "button_bottom_right_event": {
        "click": "однократное нажатие",
        "double_click": "двойное нажатие",
        "long_press": "долгое нажатие",
    },
    "button_event": {
        "click": "однократное нажатие",
        "double_click": "двойное нажатие",
        "long_press": "долгое нажатие",
    },
    "button_left_event": {
        "click": "однократное нажатие",
        "double_click": "двойное нажатие",
        "long_press": "долгое нажатие",
    },
    "button_right_event": {
        "click": "однократное нажатие",
        "double_click": "двойное нажатие",
        "long_press": "долгое нажатие",
    },
    "button_top_left_event": {
        "click": "однократное нажатие",
        "double_click": "двойное нажатие",
        "long_press": "долгое нажатие",
    },
    "button_top_right_event": {
        "click": "однократное нажатие",
        "double_click": "двойное нажатие",
        "long_press": "долгое нажатие",
    },
    "channel": {
        "+": "следующий канал",
        "-": "предыдущий канал",
    },
    "custom_key": {
        "back": "кнопка возврата на предыдущий экран",
        "confirm": "кнопка подтверждения (OK)",
        "home": "кнопка перехода на домашний экран",
        "next": "кнопка перехода к следующему объекту, например видеофайлу",
        "pause": "кнопка паузы воспроизведения",
        "play": "кнопка старта воспроизведения",
        "previous": "кнопка перехода к предыдущему объекту, например видеофайлу",
    },
    "direction": {
        "down": "сдвинуть вниз",
        "left": "сдвинуть влево",
        "right": "сдвинуть вправо",
        "up": "сдвинуть вверх",
    },
    "hvac_air_flow_direction": {
        "auto": "поток воздуха меняет направление автоматически",
        "horizontal": "поток воздуха меняет направление по горизонтальной оси",
        "no": "управление потоком воздуха выключено",
        "rotation": "поток воздуха меняет направление и по вертикальной, и по горизонтальной осям",
        "swing": "режим автоматической смены направления потока воздуха",
        "vertical": "поток воздуха меняет направление по вертикальной оси",
    },
    "hvac_air_flow_power": {
        "auto": "скорость меняется автоматически",
        "high": "высокая скорость",
        "low": "низкая скорость",
        "medium": "средняя скорость",
        "quiet": "тихий режим работы. Скорость вентилятора замедляется для снижения шума",
        "turbo": "повышенная скорость работы вентилятора. Обычно используется для быстрого охлаждения, нагрева или проветривания комнаты",
    },
    "hvac_direction_set": {
        "down": "вниз",
        "left": "налево",
        "right": "направо",
        "up": "вверх",
    },
    "hvac_heating_rate": {
        "auto": "автоматическая скорость нагрева",
        "high": "высокая скорость нагрева",
        "low": "низкая скорость нагрева",
        "medium": "средняя скорость нагрева",
    },
    "hvac_thermostat_mode": {
        "auto": "автоматический режим",
        "cooling": "охлаждение",
        "eco": "энергосбережение",
        "fast_cooling": "быстрое охлаждение",
        "fast_heating": "быстрый нагрев",
        "heating": "нагрев",
        "turbo": "режим усиленной работы",
    },
    "hvac_work_mode": {
        "air_purification": "очистка воздуха",
        "auto": "автоматический режим",
        "comfortable_sleep": "режим комфортного сна",
        "cooling": "охлаждение воздуха",
        "dehumidification": "осушение воздуха",
        "eco": "энергосбережение",
        "fast_cooling": "быстрое охлаждение воздуха",
        "fast_heating": "быстрый нагрев воздуха",
        "heating": "нагрев воздуха",
        "self_cleaning": "самоочистка и сушка устройства",
        "turbo": "режим усиленной работы",
        "ventilation": "вентиляция без охлаждения или нагрева воздуха",
    },
    "light_mode": {
        "colour": "цветной режим. Например, лампа светит оранжевым",
        "white": "белый цвет. Устройство светит белым",
    },
    "open_left_set": {
        "close": "закрыть",
        "open": "открыть",
        "stop": "остановить",
    },
    "open_left_state": {
        "close": "закрыто",
        "closing": "закрывается",
        "open": "открыто",
        "opening": "открывается",
    },
    "open_rate": {
        "auto": "автоматическая скорость",
        "high": "высокая скорость",
        "low": "низкая скорость",
        "medium": "средняя скорость",
    },
    "open_right_set": {
        "close": "закрыть",
        "open": "открыть",
        "stop": "остановить",
    },
    "open_right_state": {
        "close": "закрыто",
        "closing": "закрывается",
        "open": "открыто",
        "opening": "открывается",
    },
    "open_set": {
        "close": "закрыть",
        "open": "открыть",
        "stop": "остановить",
    },
    "open_state": {
        "close": "закрыто",
        "closing": "закрывается",
        "open": "открыто",
        "opening": "открывается",
    },
    "pir": {
        "pir": "отправляется, когда обнаружено движение",
    },
    "sensor_sensitive": {
        "high": "высокая чувствительность",
        "low": "низкая чувствительность",
        "medium": "средняя чувствительность",
    },
    "signal_strength": {
        "high": "высокий уровень сигнала. Вероятность появления сбоев связи минимальна",
        "low": "низкий уровень сигнала. Возможны сбои связи",
        "medium": "средний уровень сигнала. Иногда возможны сбои связи, но вероятность их появления меньше, чем на уровне low",
    },
    "source": {
        "+": "следующий источник сигнала",
        "-": "предыдущий источник сигнала",
        "av": "сигнал с AV-входа (RCA)",
        "content": "трансляция видео со смартфона или компьютера на телевизор",
        "hdmi1": "сигнал со входа HDMI № 1",
        "hdmi2": "сигнал со входа HDMI № 2",
        "hdmi3": "сигнал со входа HDMI № 3",
        "screencast": "демонстрация экрана смартфона или компьютера на телевизоре",
        "tv": "сигнал с ТВ-антенны",
    },
    "temp_unit_view": {
        "c": "градусы Цельсия",
        "f": "градусы Фаренгейта",
    },
    "vacuum_cleaner_cleaning_type": {
        "dry": "сухая уборка",
        "mixed": "сухая и влажная уборка",
        "wet": "влажная уборка",
    },
    "vacuum_cleaner_command": {
        "pause": "приостановить уборку",
        "resume": "возобновить уборку",
        "return_to_dock": "вернуться на базу",
        "start": "начать уборку",
    },
    "vacuum_cleaner_program": {
        "perimeter": "уборка по периметру помещения. Устройство двигается вдоль стен, не убираясь в центре",
        "random_route": "уборка по случайному маршруту. Устройство двигается по простейшему алгоритму, не отслеживающему ранее убранную площадь. Обычно уборка продолжается, пока батарея не разрядится до заданного производителем порогового значения, после этого устройство возвращается на базу",
        "smart": "уборка в автоматическом режиме по алгоритму устройства. Обычно в этом режиме устройство убирает всю доступную площадь помещения",
        "spot": "уборка по спирали. Устройство начинает уборку в точке запуска и двигается по расширяющейся спирали",
    },
    "vacuum_cleaner_status": {
        "cleaning": "уборка",
        "docked": "на базе",
        "pause": "пауза",
        "returning_to_dock": "возвращение на базу",
    },
    "volume": {
        "+": "сделать громче",
        "-": "сделать тише",
    },
}
"""ENUM value → Sber's Russian gloss for that value.

"cooling — охлаждение воздуха", "self_cleaning — самоочистка и
сушка устройства".  Absent for the two command-only ENUMs whose
pages carry no vocabulary at all (``reject_call``, ``unlock``):
their single legal value appears only inside the state example,
which is captured in the snapshot but is too thin a source to
label from."""
