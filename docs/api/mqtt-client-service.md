# MqttClientService

Транспортный слой: персистентное MQTT-соединение к брокеру Sber, цикл
реконнекта с экспоненциальным backoff, примитивы publish / subscribe.
Извлечён из `SberBridge` в рамках рефакторинга v1.25.1 для изоляции
транспортных забот от оркестрации моста (SRP).

Сервис управляется через `SberMqttCredentials` (value object с учётными
данными) и `MqttServiceHooks` (коллбэки для on_message / on_connected /
on_disconnected). Не знает о сущностях, командах или состоянии HA — вся
высокоуровневая логика инжектируется через хуки.

::: custom_components.sber_mqtt_bridge.mqtt_client_service
    options:
      show_root_heading: false
