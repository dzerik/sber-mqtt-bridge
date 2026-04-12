# MessageLogger

Ring-buffer для MQTT-сообщений (входящих и исходящих) плюс real-time
fan-out подписчикам через WebSocket (DevTools panel).

Извлечён из `SberBridge` в v1.25.1. Сохраняет последние `maxlen` сообщений
в `collections.deque`, поддерживает `subscribe(callback)` → возвращает
`unsubscribe` callable, и `resize(new_maxlen)` для runtime-изменения
размера буфера.

::: custom_components.sber_mqtt_bridge.message_logger
    options:
      show_root_heading: false
