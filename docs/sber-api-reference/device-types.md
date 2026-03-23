=== /docs/ru/smarthome/c2c/light ===
Содержание раздела
Доступные функции устройства
Пример описания модели датчика протечки
Пример описания датчика протечки пользователя
sensor_water_leak
Обновлено 28 октября 2025

Датчик протечки.

Доступные функции устройства﻿

У устройства могут быть все нижеперечисленные функции или только часть из них. Например, если датчик не умеет сообщать об уровне заряда батареи, включать функцию battery_percentage в описание его модели не нужно.

Некоторые функции обязательные: они должны быть у всех датчиков протечки.

Функция	Обязательная?	Описание
battery_low_power		Разряжена ли батарея или нет
battery_percentage		Уровень заряда батареи
online	✔︎	Доступность устройства: офлайн или онлайн
signal_strength		

Сила сигнала


water_leak_state	✔︎	

Обнаружена ли протечка воды

Пример описания модели датчика протечки﻿

Модель описывается в соответствии со структурой model. В примере описан датчик, который умеет сообщать об обнаружении протечки, силе сигнала, уровне заряда батареи и разряжена ли батарея.

Кроме того, у модели изменены доступные значения для функции signal_strength (сила сигнала): эта модель поддерживает только два уровня силы сигнала. Средний уровень medium не поддерживается и исключен.

{
    "id": "QWERTY124",
    "manufacturer": "Xiaqara",
    "model": "SM1123456789",
    "hw_version": "3.1",
    "sw_version": "5.6",
    "description": "Умный датчик протечки Xiaqara",
    "category": "sensor_water_leak",
    "features": [
        "online",
        "battery_low_power",
        "battery_percentage",
        "signal_strength",
        "water_leak_state",
    ],
    "allowed_values": {
        "signal_strength": {
            "type": "ENUM",
            "enum_values": {
                "values": [
                    "low",
                    "high",
                ]
            }
        }
    }
}

Пример описания датчика протечки пользователя﻿

Устройство описывается в соответствии со структурой device. В примере нет описания модели датчика — считаем, что моде

=== /docs/ru/smarthome/c2c/relay ===
Содержание раздела
Доступные функции устройства
Пример описания модели реле
Пример описания реле пользователя
relay
Обновлено 28 октября 2025

Реле — устройство, которое по команде включает или выключает питание присоединенного прибора: светильника, розетки и др. Обычно подключается к электропроводке.

Доступные функции устройства﻿

У устройства могут быть все нижеперечисленные функции или только часть из них. Например, если умное реле не умеет измерять текущее энергопотребление, включать функции current, power, voltage в описание его модели не нужно.

У устройства есть две обязательные функции: online, on_off. Они должны быть у всех реле.

Функция	Обязательная?	Описание
current		Текущий ток, мА
on_off	✔︎	Удаленное включение и выключение устройства
online	✔︎	Доступность устройства: офлайн или онлайн
power		Текущая мощность, Вт
voltage		Текущее напряжение, В
Пример описания модели реле﻿

Модель описывается в соответствии со структурой model. В примере описано реле, которое может по удаленной команде включать и выключать питание присоединенного прибора, а также умеет измерять энергопотребление.

Кроме того, у модели изменены доступные значения для функции power (потребляемая мощность): указано, что устройства этой модели умеют измерять мощность в диапазоне от 10 до 45000 ватт с шагом в 1 ватт.

{
   "id": "QWERTY124",
   "manufacturer": "Xiaqara",
   "model": "SM1123456789",
   "hw_version": "3.1",
   "sw_version": "5.6",
   "description": "Умное реле Xiaqara",
   "category": "relay",
   "features": [
      "online",
      "on_off",
      "current",
      "power",
      "voltage"
   ],
   "allowed_values": {
      "power": {
         "type": "INTEGER",
         "integer_values": {
            "min": "10",
            "max": "45000",
            "step": "1"
         }
      }
   }
}

Пример описания реле пользователя﻿

Устройство описывается в соответствии со структурой device. В примере нет описания модели реле — считаем, что модели описаны отдельно, поэтому достаточн

=== /docs/ru/smarthome/c2c/socket ===
Содержание раздела
Доступные функции устройства
Пример описания модели моторизованного крана
Пример описания моторизованного крана пользователя
valve
Обновлено 28 октября 2025

Моторизованный кран.

Доступные функции устройства﻿

У устройства могут быть все нижеперечисленные функции или только часть из них. Например, если устройство нельзя открыть на заданный процент, включать функцию open_percentage в описание его модели не нужно.

У устройства есть обязательные функции: online, open_state. Кроме того, обязательно должен быть описан способ открытия: либо open_set, либо open_percentage, либо они оба.

При одновременном использовании open_set и open_percentage необходимо соблюдать правило:

Если open_percentage не равен нулю, то open_set должен принять значение open. И наоборот: если open_set имеет значение open, open_percentage должен быть больше нуля.
Если open_percentage равен нулю, то open_set должен принять значение close. И наоборот: если open_set имеет значение close, open_percentage должен быть равен нулю.
Функция	Обязательная?	Описание
battery_low_power		

Разряжена ли батарея или нет


battery_percentage		

Уровень заряда батареи


online	✔︎	

Доступность устройства: офлайн или онлайн


open_percentage	✔︎*	

Открывание устройства в процентах. Для устройства обязательно должен быть описан способ открытия: либо open_percentage, либо open_set, либо они оба


open_set	✔︎*	

Открывание устройства. Для устройства обязательно должен быть описан способ открытия: либо open_set, либо open_percentage, либо они оба


open_state	✔︎	

Статус открывания устройства


signal_strength		

Сила сигнала

Пример описания модели моторизованного крана﻿

Модель описывается в соответствии со структурой model. В примере описан кран, который обладает всеми функциями, кроме возможности открываться на заданный процент.

Кроме того, у модели изменены доступные значения для функции signal_strength (сила сигнала): эта модель поддерживает только два уровня силы сигнала. Средний уровень medi

=== /docs/ru/smarthome/c2c/curtain ===
Содержание раздела
Доступные функции устройства
Пример описания модели штор
Пример описания штор пользователя
curtain
Обновлено 28 октября 2025

Шторы (раздвижные).

Доступные функции устройства﻿

У устройства могут быть все нижеперечисленные функции или только часть из них. Например, если устройство нельзя открыть на заданный процент, включать функцию open_percentage в описание его модели не нужно.

У устройства есть обязательные функции: online, open_state. Кроме того, обязательно должен быть описан способ открытия: либо open_set, либо open_percentage, либо они оба.

При одновременном использовании open_set и open_percentage необходимо соблюдать правило:

Если open_percentage не равен нулю, то open_set должен принять значение open. И наоборот: если open_set имеет значение open, open_percentage должен быть больше нуля.
Если open_percentage равен нулю, то open_set должен принять значение close. И наоборот: если open_set имеет значение close, open_percentage должен быть равен нулю.

При изменении значений функций open_left_state, open_left_percentage, open_right_state, open_right_percentage должны соответствующим образом меняться и значения функций open_state, open_percentage.

Функция	Обязательная?	Описание
battery_low_power		

Разряжена ли батарея или нет


battery_percentage		

Уровень заряда батареи


online	

✔︎

	

Доступность устройства: офлайн или онлайн


open_left_percentage		

Открывание левой половины устройства в процентах


open_left_set		

Открывание левой половины устройства


open_left_state		

Статус открывания левой стороны устройства


open_percentage	

✔︎*

	

Открывание устройства в процентах. Для устройства обязательно должен быть описан способ открытия: либо open_percentage, либо open_set, либо они оба


open_rate		

Скорость открывания устройства


open_right_percentage		

Открывание правой половины устройства в процентах


open_right_set		

Открывание правой половины устройства


open_right_state		

Статус открывания правой стороны устройств

=== /docs/ru/smarthome/c2c/hvac_ac ===
Содержание раздела
Доступные функции устройства
Пример описания модели кондиционера
Пример описания кондиционера пользователя
hvac_ac
Обновлено 28 октября 2025

Кондиционер — устройство, которое может менять температуру и другие характеристики воздуха в комнате.

Доступные функции устройства﻿

У устройства могут быть все нижеперечисленные функции или только часть из них. Например, если кондиционер не умеет регулировать влажность в комнате, включать функцию hvac_humidity_set в описание его модели не нужно.

У устройства есть три обязательные функции: online, on_off, hvac_temp_set. Они должны быть у всех кондиционеров.

Функция	Обязательная?	Описание
humidity		

Текущая влажность


hvac_air_flow_direction		

Направление потока воздуха


hvac_air_flow_power		

Скорость вентиляторов


hvac_humidity_set		

Влажность воздуха, которую необходимо достичь


hvac_ionization		Режим ионизации
hvac_night_mode		Ночной режим работы
hvac_temp_set	✔︎	

Температура воздуха, которую необходимо достичь


hvac_work_mode		

Режим работы кондиционера


on_off	✔︎	

Удаленное включение и выключение устройства


online	✔︎	

Доступность устройства: офлайн или онлайн


temperature		

Текущая температура

Пример описания модели кондиционера﻿

Модель описывается в соответствии со структурой model. В примере описан кондиционер, который обладает всеми функциями, кроме режима ионизации.

Кроме того, у модели изменены доступные значения для функции hvac_air_flow_power (скорость вентилятора): эта модель не поддерживает тихий режим работы quiet, он исключен.

{
   "id": "QWERTY124",
   "manufacturer": "Xiaqara",
   "model": "SM1123456789",
   "hw_version": "3.1",
   "sw_version": "5.6",
   "description": "Умный кондиционер Xiaqara",
   "category": "hvac_ac",
   "features": [
      "online",
      "on_off",
      "hvac_temp_set",
      "hvac_air_flow_direction",
      "hvac_air_flow_power",
      "hvac_humidity_set",
      "hvac_night_mode",
      "hvac_work_mode"
   ],
   "allowed_values": {
      "hv

=== /docs/ru/smarthome/c2c/sensor_temp ===
Содержание раздела
Доступные функции устройства
Пример описания модели датчика температуры и влажности
Пример описания датчика температуры и влажности
sensor_temp
Обновлено 28 октября 2025

Датчик температуры и/или влажности.

Доступные функции устройства﻿

У устройства могут быть все нижеперечисленные функции или только часть из них. Например, если датчик не умеет сообщать об уровне заряда батареи, включать функцию battery_percentage в описание его модели не нужно.

Для датчика обязательной является функция online. Также обязательно должна быть описана хотя бы одна из следующих функций: humidity, temperature. Например, если вы описываете датчик температуры, для него обязательно нужно перечислить функции online и temperature, а функцию humidity указывать не нужно.

Если же вы описываете датчик температуры и влажности, обязательно нужно перечислить все три функции: online, humidity, temperature.

Функция	Обязательная?	Описание
air_pressure		

Текущее атмосферное давление


battery_low_power		Разряжена ли батарея или нет
battery_percentage		Уровень заряда батареи
humidity	

✔︎*

	

Текущая влажность. Функция обязательна для датчиков влажности и датчиков температуры и влажности. Для датчиков температуры, которые влажность не измеряют, ее указывать не нужно


online	✔︎	Доступность устройства: офлайн или онлайн
sensor_sensitive		

Чувствительность датчика


signal_strength		

Сила сигнала


temp_unit_view		

Температурная шкала, в которой датчик сейчас выводит информацию о температуре на свой экран: °C или °F. Используйте только для датчиков с экраном, которые умеют показывать температуру в разных температурных шкалах


temperature	

✔︎*

	

Текущая температура. Функция обязательна для датчиков температуры и датчиков температуры и влажности. Для датчиков влажности, которые температуру не измеряют, ее указывать не нужно

Пример описания модели датчика температуры и влажности﻿

Модель описывается в соответствии со структурой model. В примере описан датчик температуры и вла

=== /docs/ru/smarthome/c2c/sensor_pir ===
Содержание раздела
Доступные функции устройства
Пример описания модели датчика движения
Пример описания датчика движения пользователя
sensor_pir
Обновлено 28 октября 2025

Датчик движения.

Доступные функции устройства﻿

У устройства могут быть все нижеперечисленные функции или только часть из них. Например, если датчик не умеет сообщать об уровне заряда батареи, включать функцию battery_percentage в описание его модели не нужно.

Некоторые функции обязательные: они должны быть у всех датчиков движения.

Функция	Обязательная?	Описание
battery_low_power		Разряжена ли батарея или нет
battery_percentage		Уровень заряда батареи
online	✔︎	Доступность устройства: офлайн или онлайн
pir	✔︎	Обнаружено ли движение
sensor_sensitive		

Чувствительность датчика


signal_strength		

Сила сигнала

Пример описания модели датчика движения﻿

Модель описывается в соответствии со структурой model. В примере описан датчик, который умеет сообщать об обнаруженном движении, силе сигнала, уровне заряда батареи и разряжена ли батарея. Также имеет настройку чувствительности.

Кроме того, у модели изменены доступные значения для функции sensor_sensitive (чувствительность датчика): эта модель поддерживает только два уровня чувствительности. Средний уровень medium не поддерживается и исключен.

{
    "id": "QWERTY124",
    "manufacturer": "Xiaqara",
    "model": "SM1123456789",
    "hw_version": "3.1",
    "sw_version": "5.6",
    "description": "Умный датчик движения Xiaqara",
    "category": "sensor_pir",
    "features": [
        "online",
        "pir",
        "battery_low_power",
        "battery_percentage",
        "sensor_sensitive",
        "signal_strength"
    ],
    "allowed_values": {
        "sensor_sensitive": {
            "type": "ENUM",
            "enum_values": {
                "values": [
                    "auto",
                    "high"
                ]
            }
        }
    }
}

Пример описания датчика движения пользователя﻿

Устройство описывается в соответс

=== /docs/ru/smarthome/c2c/sensor_door ===
Содержание раздела
Доступные функции устройства
Пример описания модели датчика открытия
Пример описания датчика открытия пользователя
sensor_door
Обновлено 28 октября 2025

Датчик открытия.

Доступные функции устройства﻿

У устройства могут быть все нижеперечисленные функции или только часть из них. Например, если датчик не умеет сообщать об уровне заряда батареи, включать функцию battery_percentage в описание его модели не нужно.

Некоторые функции обязательные: они должны быть у всех датчиков открытия.

Функция	Обязательная?	Описание
battery_low_power		Разряжена ли батарея или нет
battery_percentage		Уровень заряда батареи
doorcontact_state	✔︎	

Показывает, разомкнуты или сомкнуты контакты датчика. Если контакты разомкнуты, значит, створки двери, окна или другой подобной конструкции открыты. Сомкнутые контакты означают, что створки закрыты


online	✔︎	Доступность устройства: офлайн или онлайн
sensor_sensitive		

Чувствительность датчика


signal_strength		

Сила сигнала


tamper_alarm		

Сигнализация о вскрытии датчика

Пример описания модели датчика открытия﻿

Модель описывается в соответствии со структурой model. В примере описан датчик открытия, который умеет сообщать, открыты или закрыты сейчас створки и не был ли датчик вскрыт. Также датчик сообщает о силе сигнала, уровне заряда батареи и разряжена ли батарея, имеет настройку чувствительности.

Кроме того, у модели изменены доступные значения для функции sensor_sensitive (чувствительность датчика): эта модель поддерживает только два уровня чувствительности. Средний уровень medium не поддерживается и исключен.

{
    "id": "QWERTY124",
    "manufacturer": "Xiaqara",
    "model": "SM1123456789",
    "hw_version": "3.1",
    "sw_version": "5.6",
    "description": "Умный датчик открытия Xiaqara",
    "category": "sensor_door",
    "features": [
        "online",
        "doorcontact_state",
        "battery_low_power",
        "battery_percentage",
        "sensor_sensitive",
        "signal_strength",
        "

=== /docs/ru/smarthome/c2c/sensor_water_leak ===
Содержание раздела
Доступные функции устройства
Пример описания модели датчика протечки
Пример описания датчика протечки пользователя
sensor_water_leak
Обновлено 28 октября 2025

Датчик протечки.

Доступные функции устройства﻿

У устройства могут быть все нижеперечисленные функции или только часть из них. Например, если датчик не умеет сообщать об уровне заряда батареи, включать функцию battery_percentage в описание его модели не нужно.

Некоторые функции обязательные: они должны быть у всех датчиков протечки.

Функция	Обязательная?	Описание
battery_low_power		Разряжена ли батарея или нет
battery_percentage		Уровень заряда батареи
online	✔︎	Доступность устройства: офлайн или онлайн
signal_strength		

Сила сигнала


water_leak_state	✔︎	

Обнаружена ли протечка воды

Пример описания модели датчика протечки﻿

Модель описывается в соответствии со структурой model. В примере описан датчик, который умеет сообщать об обнаружении протечки, силе сигнала, уровне заряда батареи и разряжена ли батарея.

Кроме того, у модели изменены доступные значения для функции signal_strength (сила сигнала): эта модель поддерживает только два уровня силы сигнала. Средний уровень medium не поддерживается и исключен.

{
    "id": "QWERTY124",
    "manufacturer": "Xiaqara",
    "model": "SM1123456789",
    "hw_version": "3.1",
    "sw_version": "5.6",
    "description": "Умный датчик протечки Xiaqara",
    "category": "sensor_water_leak",
    "features": [
        "online",
        "battery_low_power",
        "battery_percentage",
        "signal_strength",
        "water_leak_state",
    ],
    "allowed_values": {
        "signal_strength": {
            "type": "ENUM",
            "enum_values": {
                "values": [
                    "low",
                    "high",
                ]
            }
        }
    }
}

Пример описания датчика протечки пользователя﻿

Устройство описывается в соответствии со структурой device. В примере нет описания модели датчика — считаем, что моде

=== /docs/ru/smarthome/c2c/valve ===
Содержание раздела
Доступные функции устройства
Пример описания модели сценарной кнопки
Пример описания сценарной кнопки пользователя
scenario_button
Обновлено 28 октября 2025

Сценарная кнопка — устройство, которое умеет запускать сценарии умного дома. Сценарная кнопка физически оснащается одной или несколькими кнопками, каждая из них может реагировать на разные типы нажатий: однократное, двукратное, долгое. На каждый тип нажатия пользователь может назначить сценарий или команду управления устройствами умного дома.

Доступные функции устройства﻿

У устройства могут быть все нижеперечисленные функции или только часть из них. Например, если сценарная кнопка кнопка оборудована только одной физической кнопкой, функции button_1_event, button_2_event и др. указывать не нужно.

Для сценарной кнопки обязательно должна быть описана функция online, а также как минимум одна функция нажатия на кнопку.

Функция	Обязательная?	Описание
battery_low_power		

Разряжена ли батарея или нет


battery_percentage		

Уровень заряда батареи


button_event		

Нажатие на кнопку


button_1_event		

Нажатие на первую кнопку


button_2_event		

Нажатие на вторую кнопку


button_3_event		

Нажатие на третью кнопку


button_4_event		

Нажатие на четвертую кнопку


button_5_event		

Нажатие на пятую кнопку


button_6_event		

Нажатие на шестую кнопку


button_7_event		

Нажатие на седьмую кнопку


button_8_event		

Нажатие на восьмую кнопку


button_9_event		

Нажатие на девятую кнопку


button_10_event		

Нажатие на десятую кнопку


button_bottom_left_event		

Нажатие на левую нижнюю кнопку


button_bottom_right_event		

Нажатие на правую нижнюю кнопку


button_left_event		

Нажатие на левую кнопку


button_right_event		

Нажатие на правую кнопку


button_top_left_event		

Нажатие на левую верхнюю кнопку


button_top_right_event		

Нажатие на правую верхнюю кнопку


online	✔︎	

Доступность устройства: офлайн или онлайн


signal_strength		

Сила сигнала

Пример описания модели сценарной кнопки﻿

М

=== /docs/ru/smarthome/c2c/scenario_button ===
Содержание раздела
Доступные функции устройства
Пример описания модели сценарной кнопки
Пример описания сценарной кнопки пользователя
scenario_button
Обновлено 28 октября 2025

Сценарная кнопка — устройство, которое умеет запускать сценарии умного дома. Сценарная кнопка физически оснащается одной или несколькими кнопками, каждая из них может реагировать на разные типы нажатий: однократное, двукратное, долгое. На каждый тип нажатия пользователь может назначить сценарий или команду управления устройствами умного дома.

Доступные функции устройства﻿

У устройства могут быть все нижеперечисленные функции или только часть из них. Например, если сценарная кнопка кнопка оборудована только одной физической кнопкой, функции button_1_event, button_2_event и др. указывать не нужно.

Для сценарной кнопки обязательно должна быть описана функция online, а также как минимум одна функция нажатия на кнопку.

Функция	Обязательная?	Описание
battery_low_power		

Разряжена ли батарея или нет


battery_percentage		

Уровень заряда батареи


button_event		

Нажатие на кнопку


button_1_event		

Нажатие на первую кнопку


button_2_event		

Нажатие на вторую кнопку


button_3_event		

Нажатие на третью кнопку


button_4_event		

Нажатие на четвертую кнопку


button_5_event		

Нажатие на пятую кнопку


button_6_event		

Нажатие на шестую кнопку


button_7_event		

Нажатие на седьмую кнопку


button_8_event		

Нажатие на восьмую кнопку


button_9_event		

Нажатие на девятую кнопку


button_10_event		

Нажатие на десятую кнопку


button_bottom_left_event		

Нажатие на левую нижнюю кнопку


button_bottom_right_event		

Нажатие на правую нижнюю кнопку


button_left_event		

Нажатие на левую кнопку


button_right_event		

Нажатие на правую кнопку


button_top_left_event		

Нажатие на левую верхнюю кнопку


button_top_right_event		

Нажатие на правую верхнюю кнопку


online	✔︎	

Доступность устройства: офлайн или онлайн


signal_strength		

Сила сигнала

Пример описания модели сценарной кнопки﻿

М

=== /docs/ru/smarthome/c2c/gate ===
Содержание раздела
Доступные функции устройства
Пример описания модели ворот
Пример описания ворот пользователя
gate
Обновлено 28 октября 2025

Ворота.

Доступные функции устройства﻿

У устройства могут быть все нижеперечисленные функции или только часть из них. Например, если устройство нельзя открыть на заданный процент, включать функцию open_percentage в описание его модели не нужно.

У устройства есть обязательные функции: online, open_state. Кроме того, обязательно должен быть описан способ открытия: либо open_set, либо open_percentage, либо они оба.

При одновременном использовании open_set и open_percentage необходимо соблюдать правило:

Если open_percentage не равен нулю, то open_set должен принять значение open. И наоборот: если open_set имеет значение open, open_percentage должен быть больше нуля.
Если open_percentage равен нулю, то open_set должен принять значение close. И наоборот: если open_set имеет значение close, open_percentage должен быть равен нулю.

При изменении значений функций open_left_state, open_left_percentage, open_right_state, open_right_percentage должны соответствующим образом меняться и значения функций open_state, open_percentage.

Функция	Обязательная?	Описание
online	

✔︎

	

Доступность устройства: офлайн или онлайн


open_left_percentage		

Открывание левой половины устройства в процентах


open_left_set		

Открывание левой половины устройства


open_left_state		

Статус открывания левой стороны устройства


open_percentage	

✔︎*

	

Открывание устройства в процентах. Для устройства обязательно должен быть описан способ открытия: либо open_percentage, либо open_set, либо они оба


open_rate		

Скорость открывания устройства


open_right_percentage		

Открывание правой половины устройства в процентах


open_right_set		

Статус открывания правой стороны устройства


open_right_state		

Открывание правой половины устройства


open_set	

✔︎*

	

Открывание устройства. Для устройства обязательно должен быть описан способ открытия: либ"
### Ran Playwright code
```js
await (async (page) => {
  const pages = [
    '/docs/ru/smarthome/c2c/light',
    '/docs/ru/smarthome/c2c/relay',
    '/docs/ru/smarthome/c2c/socket',
    '/docs/ru/smarthome/c2c/curtain',
    '/docs/ru/smarthome/c2c/hvac_ac',
    '/docs/ru/smarthome/c2c/sensor_temp',
    '/docs/ru/smarthome/c2c/sensor_pir',
    '/docs/ru/smarthome/c2c/sensor_door',
    '/docs/ru/smarthome/c2c/sensor_water_leak',
    '/docs/ru/smarthome/c2c/valve',
    '/docs/ru/smarthome/c2c/scenario_button',
    '/docs/ru/smarthome/c2c/gate',
  ];
  const results = [];
  for (const path of pages) {
    try {
      await page.goto('https://developers.sber.ru' + path, {waitUntil: 'domcontentloaded', timeout: 10000});
      await page.waitForTimeout(2000);
      const text = await page.evaluate(() => {
        const article = document.querySelector('article');
        return article ? article.innerText : 'NO_ARTICLE';
      });
      results.push('=== ' + path + ' ===
' + text.substring(0, 2000));
    } catch(e) {
      results.push('=== ' + path + ' === ERROR: ' + e.message);
    }
  }
  return results.join('

');
})(page);
```
### Page
- Page URL: https://developers.sber.ru/docs/ru/smarthome/c2c/gate
- Page Title: Устройство gate | Документация для разработчиков
- Console: 144 errors, 38 warnings
### Events
- New console entries: .playwright-mcp/console-2026-03-23T14-51-29-653Z.log#L1116-L2350
- [ERROR] Access to fetch at 'https://sentry-api.sbe...ers.sber.ru/docs/ru/smarthome/c2c/hvac_humidifier:489
- [ERROR] Failed to load resource: net::ERR_FAILED @...on=7&sentry_client=sentry.javascript.react%2F7.11.1:0
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [WARNING] It is recommended that a robustness leve... @ https://smartcaptcha.yandexcloud.net/captchapgrd:0
- [WARNING] It is recommended that a robustness leve... @ https://smartcaptcha.yandexcloud.net/captchapgrd:0
- [ERROR] Access to fetch at 'https://sentry-api.sbe...opers.sber.ru/docs/ru/smarthome/c2c/hvac_humidifier:0
- [ERROR] Failed to load resource: net::ERR_FAILED @...on=7&sentry_client=sentry.javascript.react%2F7.11.1:0
- [ERROR] Access to fetch at 'https://sentry-api.sbe...evelopers.sber.ru/docs/ru/smarthome/c2c/sensor_temp:0
- [ERROR] Failed to load resource: net::ERR_FAILED @...on=7&sentry_client=sentry.javascript.react%2F7.11.1:0
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [WARNING] It is recommended that a robustness leve... @ https://smartcaptcha.yandexcloud.net/captchapgrd:0
- [WARNING] It is recommended that a robustness leve... @ https://smartcaptcha.yandexcloud.net/captchapgrd:0
- [ERROR] Access to fetch at 'https://sentry-api.sbe...evelopers.sber.ru/docs/ru/smarthome/c2c/sensor_temp:0
- [ERROR] Failed to load resource: net::ERR_FAILED @...on=7&sentry_client=sentry.javascript.react%2F7.11.1:0
- [ERROR] Access to fetch at 'https://sentry-api.sbe...developers.sber.ru/docs/ru/smarthome/c2c/sensor_pir:0
- [ERROR] Failed to load resource: net::ERR_FAILED @...on=7&sentry_client=sentry.javascript.react%2F7.11.1:0
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [WARNING] It is recommended that a robustness leve... @ https://smartcaptcha.yandexcloud.net/captchapgrd:0
- [WARNING] It is recommended that a robustness leve... @ https://smartcaptcha.yandexcloud.net/captchapgrd:0
- [ERROR] Access to fetch at 'https://sentry-api.sbe...developers.sber.ru/docs/ru/smarthome/c2c/sensor_pir:0
- [ERROR] Failed to load resource: net::ERR_FAILED @...on=7&sentry_client=sentry.javascript.react%2F7.11.1:0
- [ERROR] Access to fetch at 'https://sentry-api.sbe...elopers.sber.ru/docs/ru/smarthome/c2c/sensor_door:490
- [ERROR] Failed to load resource: net::ERR_FAILED @...on=7&sentry_client=sentry.javascript.react%2F7.11.1:0
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Access to fetch at 'https://sentry-api.sbe...evelopers.sber.ru/docs/ru/smarthome/c2c/sensor_door:0
- [ERROR] Failed to load resource: net::ERR_FAILED @...on=7&sentry_client=sentry.javascript.react%2F7.11.1:0
- [WARNING] It is recommended that a robustness leve... @ https://smartcaptcha.yandexcloud.net/captchapgrd:0
- [WARNING] It is recommended that a robustness leve... @ https://smartcaptcha.yandexcloud.net/captchapgrd:0
- [WARNING] It is recommended that a robustness leve... @ https://smartcaptcha.yandexcloud.net/captchapgrd:0
- [ERROR] Access to fetch at 'https://sentry-api.sbe...://developers.sber.ru/docs/ru/smarthome/c2c/light:493
- [ERROR] Failed to load resource: net::ERR_FAILED @...on=7&sentry_client=sentry.javascript.react%2F7.11.1:0
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [WARNING] It is recommended that a robustness leve... @ https://smartcaptcha.yandexcloud.net/captchapgrd:0
- [WARNING] It is recommended that a robustness leve... @ https://smartcaptcha.yandexcloud.net/captchapgrd:0
- [WARNING] It is recommended that a robustness leve... @ https://smartcaptcha.yandexcloud.net/captchapgrd:0
- [ERROR] Access to fetch at 'https://sentry-api.sbe...ps://developers.sber.ru/docs/ru/smarthome/c2c/light:0
- [ERROR] Failed to load resource: net::ERR_FAILED @...on=7&sentry_client=sentry.javascript.react%2F7.11.1:0
- [ERROR] Access to fetch at 'https://sentry-api.sbe...s.sber.ru/docs/ru/smarthome/c2c/sensor_water_leak:490
- [ERROR] Failed to load resource: net::ERR_FAILED @...on=7&sentry_client=sentry.javascript.react%2F7.11.1:0
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Access to fetch at 'https://sentry-api.sbe...://developers.sber.ru/docs/ru/smarthome/c2c/relay:489
- [ERROR] Failed to load resource: net::ERR_FAILED @...on=7&sentry_client=sentry.javascript.react%2F7.11.1:0
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [WARNING] It is recommended that a robustness leve... @ https://smartcaptcha.yandexcloud.net/captchapgrd:0
- [WARNING] It is recommended that a robustness leve... @ https://smartcaptcha.yandexcloud.net/captchapgrd:0
- [WARNING] It is recommended that a robustness leve... @ https://smartcaptcha.yandexcloud.net/captchapgrd:0
- [ERROR] Access to fetch at 'https://sentry-api.sbe...ps://developers.sber.ru/docs/ru/smarthome/c2c/relay:0
- [ERROR] Failed to load resource: net::ERR_FAILED @...on=7&sentry_client=sentry.javascript.react%2F7.11.1:0
- [ERROR] Access to fetch at 'https://sentry-api.sbe...//developers.sber.ru/docs/ru/smarthome/c2c/socket:495
- [ERROR] Failed to load resource: net::ERR_FAILED @...on=7&sentry_client=sentry.javascript.react%2F7.11.1:0
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [WARNING] It is recommended that a robustness leve... @ https://smartcaptcha.yandexcloud.net/captchapgrd:0
- [WARNING] It is recommended that a robustness leve... @ https://smartcaptcha.yandexcloud.net/captchapgrd:0
- [WARNING] It is recommended that a robustness leve... @ https://smartcaptcha.yandexcloud.net/captchapgrd:0
- [ERROR] Access to fetch at 'https://sentry-api.sbe...s://developers.sber.ru/docs/ru/smarthome/c2c/socket:0
- [ERROR] Failed to load resource: net::ERR_FAILED @...on=7&sentry_client=sentry.javascript.react%2F7.11.1:0
- [ERROR] Access to fetch at 'https://sentry-api.sbe...://developers.sber.ru/docs/ru/smarthome/c2c/valve:494
- [ERROR] Failed to load resource: net::ERR_FAILED @...on=7&sentry_client=sentry.javascript.react%2F7.11.1:0
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Access to fetch at 'https://sentry-api.sbe.../developers.sber.ru/docs/ru/smarthome/c2c/curtain:495
- [ERROR] Failed to load resource: net::ERR_FAILED @...on=7&sentry_client=sentry.javascript.react%2F7.11.1:0
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [WARNING] It is recommended that a robustness leve... @ https://smartcaptcha.yandexcloud.net/captchapgrd:0
- [WARNING] It is recommended that a robustness leve... @ https://smartcaptcha.yandexcloud.net/captchapgrd:0
- [WARNING] It is recommended that a robustness leve... @ https://smartcaptcha.yandexcloud.net/captchapgrd:0
- [ERROR] Access to fetch at 'https://sentry-api.sbe...://developers.sber.ru/docs/ru/smarthome/c2c/curtain:0
- [ERROR] Failed to load resource: net::ERR_FAILED @...on=7&sentry_client=sentry.javascript.react%2F7.11.1:0
- [ERROR] Access to fetch at 'https://sentry-api.sbe.../developers.sber.ru/docs/ru/smarthome/c2c/hvac_ac:489
- [ERROR] Failed to load resource: net::ERR_FAILED @...on=7&sentry_client=sentry.javascript.react%2F7.11.1:0
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [WARNING] It is recommended that a robustness leve... @ https://smartcaptcha.yandexcloud.net/captchapgrd:0
- [WARNING] It is recommended that a robustness leve... @ https://smartcaptcha.yandexcloud.net/captchapgrd:0
- [WARNING] It is recommended that a robustness leve... @ https://smartcaptcha.yandexcloud.net/captchapgrd:0
- [ERROR] Access to fetch at 'https://sentry-api.sbe...://developers.sber.ru/docs/ru/smarthome/c2c/hvac_ac:0
- [ERROR] Failed to load resource: net::ERR_FAILED @...on=7&sentry_client=sentry.javascript.react%2F7.11.1:0
- [ERROR] Access to fetch at 'https://sentry-api.sbe...elopers.sber.ru/docs/ru/smarthome/c2c/sensor_temp:491
- [ERROR] Failed to load resource: net::ERR_FAILED @...on=7&sentry_client=sentry.javascript.react%2F7.11.1:0
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [WARNING] It is recommended that a robustness leve... @ https://smartcaptcha.yandexcloud.net/captchapgrd:0
- [WARNING] It is recommended that a robustness leve... @ https://smartcaptcha.yandexcloud.net/captchapgrd:0
- [WARNING] It is recommended that a robustness leve... @ https://smartcaptcha.yandexcloud.net/captchapgrd:0
- [ERROR] Access to fetch at 'https://sentry-api.sbe...evelopers.sber.ru/docs/ru/smarthome/c2c/sensor_temp:0
- [ERROR] Failed to load resource: net::ERR_FAILED @...on=7&sentry_client=sentry.javascript.react%2F7.11.1:0
- [ERROR] Access to fetch at 'https://sentry-api.sbe...velopers.sber.ru/docs/ru/smarthome/c2c/sensor_pir:490
- [ERROR] Failed to load resource: net::ERR_FAILED @...on=7&sentry_client=sentry.javascript.react%2F7.11.1:0
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [WARNING] It is recommended that a robustness leve... @ https://smartcaptcha.yandexcloud.net/captchapgrd:0
- [WARNING] It is recommended that a robustness leve... @ https://smartcaptcha.yandexcloud.net/captchapgrd:0
- [ERROR] Access to fetch at 'https://sentry-api.sbe...developers.sber.ru/docs/ru/smarthome/c2c/sensor_pir:0
- [ERROR] Failed to load resource: net::ERR_FAILED @...on=7&sentry_client=sentry.javascript.react%2F7.11.1:0
- [ERROR] Access to fetch at 'https://sentry-api.sbe...elopers.sber.ru/docs/ru/smarthome/c2c/sensor_door:490
- [ERROR] Failed to load resource: net::ERR_FAILED @...on=7&sentry_client=sentry.javascript.react%2F7.11.1:0
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [WARNING] It is recommended that a robustness leve... @ https://smartcaptcha.yandexcloud.net/captchapgrd:0
- [WARNING] It is recommended that a robustness leve... @ https://smartcaptcha.yandexcloud.net/captchapgrd:0
- [WARNING] It is recommended that a robustness leve... @ https://smartcaptcha.yandexcloud.net/captchapgrd:0
- [ERROR] Access to fetch at 'https://sentry-api.sbe...evelopers.sber.ru/docs/ru/smarthome/c2c/sensor_door:0
- [ERROR] Failed to load resource: net::ERR_FAILED @...on=7&sentry_client=sentry.javascript.react%2F7.11.1:0
- [ERROR] Access to fetch at 'https://sentry-api.sbe...s.sber.ru/docs/ru/smarthome/c2c/sensor_water_leak:490
- [ERROR] Failed to load resource: net::ERR_FAILED @...on=7&sentry_client=sentry.javascript.react%2F7.11.1:0
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [WARNING] It is recommended that a robustness leve... @ https://smartcaptcha.yandexcloud.net/captchapgrd:0
- [WARNING] It is recommended that a robustness leve... @ https://smartcaptcha.yandexcloud.net/captchapgrd:0
- [ERROR] Access to fetch at 'https://sentry-api.sbe...ers.sber.ru/docs/ru/smarthome/c2c/sensor_water_leak:0
- [ERROR] Failed to load resource: net::ERR_FAILED @...on=7&sentry_client=sentry.javascript.react%2F7.11.1:0
- [ERROR] Access to fetch at 'https://sentry-api.sbe...://developers.sber.ru/docs/ru/smarthome/c2c/valve:494
- [ERROR] Failed to load resource: net::ERR_FAILED @...on=7&sentry_client=sentry.javascript.react%2F7.11.1:0
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [WARNING] It is recommended that a robustness leve... @ https://smartcaptcha.yandexcloud.net/captchapgrd:0
- [WARNING] It is recommended that a robustness leve... @ https://smartcaptcha.yandexcloud.net/captchapgrd:0
- [ERROR] Access to fetch at 'https://sentry-api.sbe...ers.sber.ru/docs/ru/smarthome/c2c/scenario_button:489
- [ERROR] Failed to load resource: net::ERR_FAILED @...on=7&sentry_client=sentry.javascript.react%2F7.11.1:0
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [WARNING] It is recommended that a robustness leve... @ https://smartcaptcha.yandexcloud.net/captchapgrd:0
- [WARNING] It is recommended that a robustness leve... @ https://smartcaptcha.yandexcloud.net/captchapgrd:0
- [ERROR] Access to fetch at 'https://sentry-api.sbe...opers.sber.ru/docs/ru/smarthome/c2c/scenario_button:0
- [ERROR] Failed to load resource: net::ERR_FAILED @...on=7&sentry_client=sentry.javascript.react%2F7.11.1:0
- [ERROR] Access to fetch at 'https://sentry-api.sbe...ers.sber.ru/docs/ru/smarthome/c2c/scenario_button:489
- [ERROR] Failed to load resource: net::ERR_FAILED @...on=7&sentry_client=sentry.javascript.react%2F7.11.1:0
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [WARNING] It is recommended that a robustness leve... @ https://smartcaptcha.yandexcloud.net/captchapgrd:0
- [WARNING] It is recommended that a robustness leve... @ https://smartcaptcha.yandexcloud.net/captchapgrd:0
- [WARNING] It is recommended that a robustness leve... @ https://smartcaptcha.yandexcloud.net/captchapgrd:0
- [ERROR] Access to fetch at 'https://sentry-api.sbe...opers.sber.ru/docs/ru/smarthome/c2c/scenario_button:0
- [ERROR] Failed to load resource: net::ERR_FAILED @...on=7&sentry_client=sentry.javascript.react%2F7.11.1:0
- [ERROR] Access to fetch at 'https://sentry-api.sbe...s://developers.sber.ru/docs/ru/smarthome/c2c/gate:495
- [ERROR] Failed to load resource: net::ERR_FAILED @...on=7&sentry_client=sentry.javascript.react%2F7.11.1:0
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [ERROR] Docusaurus React Root onRecoverableError: .../bsm-docs/0.902.0/docs/assets/js/main.df1f7fd8.js:315
- [WARNING] It is recommended that a robustness leve... @ https://smartcaptcha.yandexcloud.net/captchapgrd:0
- [WARNING] It is recommended that a robustness leve... @ https://smartcaptcha.yandexcloud.net/captchapgrd:0
- [WARNING] It is recommended that a robustness leve... @ https://smartcaptcha.yandexcloud.net/captchapgrd:0
- [ERROR] Access to fetch at 'https://sentry-api.sbe...tps://developers.sber.ru/docs/ru/smarthome/c2c/gate:0
- [ERROR] Failed to load resource: net::ERR_FAILED @...on=7&sentry_client=sentry.javascript.react%2F7.11.1:0
