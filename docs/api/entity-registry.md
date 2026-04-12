# SberEntityLoader

Загрузчик сущностей моста: чтение HA registry, применение YAML-overrides,
разрешение linked-сенсоров, детекция конфликтов устройств.

Извлечён из `SberBridge._load_exposed_entities` в v1.25.1 — метод моста
превратился в 30-строчный оркестратор поверх `SberEntityLoader.load()`,
возвращающего `EntityLoadResult` для атомарного swap-on-replace.

::: custom_components.sber_mqtt_bridge.entity_registry
    options:
      show_root_heading: false
