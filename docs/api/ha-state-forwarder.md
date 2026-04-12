# HaStateForwarder

Переброс HA `state_changed` событий в Sber. Владеет подпиской на
state-change события через `async_track_state_change_event`, маршрутизацией
linked-сенсоров к primary-сущности, обнаружением изменения feature-листа
(триггер config republish), дебаунсингом публикации состояний.

Извлечён из `SberBridge` в v1.25.1. Не владеет состоянием моста — читает
сущности и linked-маппинг через callback'и, так что мост остаётся
единственным источником истины.

::: custom_components.sber_mqtt_bridge.ha_state_forwarder
    options:
      show_root_heading: false
