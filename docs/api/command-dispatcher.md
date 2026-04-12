# SberCommandDispatcher

Интерпретация входящих Sber MQTT-сообщений и диспатч side-эффектов.
Владеет обработчиками `handle_command`, `handle_status_request`,
`handle_config_request`, `handle_error`, `handle_change_group`,
`handle_rename_device`, `handle_global_config`.

Извлечён из `SberBridge` в v1.25.1 для изоляции Sber-протокольной
логики от транспорта и HA state forwarding (SRP). Держит ссылку на
родительский `SberBridge`, так как ряд handler'ов мутирует состояние
моста (entities, redefinitions, acknowledgements) и инициирует publish.

::: custom_components.sber_mqtt_bridge.command_dispatcher
    options:
      show_root_heading: false
