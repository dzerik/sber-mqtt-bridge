# MQTT Connection & Message Flow

## Connection Lifecycle

```mermaid
stateDiagram-v2
    [*] --> async_start: Integration loaded

    async_start --> LoadEntities: _load_exposed_entities()
    LoadEntities --> SubscribeHA: _subscribe_ha_events()
    SubscribeHA --> MqttLoop: asyncio.create_task(_mqtt_connection_loop)

    state MqttLoop {
        [*] --> Connecting: aiomqtt.Client()
        Connecting --> Connected: TLS handshake OK
        Connected --> WaitHA: _ha_ready not set?
        Connected --> PublishFirst: _ha_ready already set
        WaitHA --> PublishFirst: _ha_ready.wait() unblocked

        PublishFirst --> PubConfig: _publish_config()
        PubConfig --> PubStates: _publish_states(force=True)

        PubStates --> Subscribe: client.subscribe(down/#)
        Subscribe --> GracePeriod: start 5s grace timer

        GracePeriod --> Listening: async for message

        Listening --> Listening: process messages
        Listening --> Disconnected: MqttError / OSError
        Disconnected --> Backoff: exponential wait
        Backoff --> Connecting: retry
    }

    MqttLoop --> [*]: async_stop()
```

## (Re)connect Sequence — Publish Before Subscribe

```mermaid
sequenceDiagram
    participant HA as Home Assistant
    participant Bridge as SberBridge
    participant Broker as Sber MQTT Broker
    participant Cloud as Sber Cloud

    Note over Bridge,Broker: TLS connection established

    Bridge->>Bridge: Wait for HA ready (_ha_ready)
    HA-->>Bridge: HA started event (entities available)

    rect rgb(220, 245, 220)
        Note over Bridge,Cloud: Phase 1 — Publish (HA is authoritative)
        Bridge->>Broker: PUBLISH up/config (device list)
        Broker->>Cloud: Forward config
        Bridge->>Broker: PUBLISH up/status (all entity states)
        Broker->>Cloud: Forward states
        Note over Cloud: Sber now knows real HA state
    end

    rect rgb(220, 230, 255)
        Note over Bridge,Broker: Phase 2 — Subscribe (buffer is empty)
        Bridge->>Broker: SUBSCRIBE down/#
        Bridge->>Broker: SUBSCRIBE global_config
        Note over Bridge: Start 5s grace period
    end

    rect rgb(255, 240, 220)
        Note over Bridge,Cloud: Phase 3 — Grace period (safety net)
        Cloud->>Broker: PUBLISH down/commands (stale correction)
        Broker->>Bridge: down/commands
        Bridge->>Bridge: REJECT command (grace period)
        Bridge->>Broker: PUBLISH up/status (re-confirm HA state)
        Note over Bridge: WARNING logged
    end

    rect rgb(255, 255, 255)
        Note over Bridge,Cloud: Phase 4 — Normal operation
        Cloud->>Broker: PUBLISH down/commands (user action)
        Broker->>Bridge: down/commands
        Bridge->>HA: hass.services.async_call()
        HA-->>Bridge: state_changed event
        Bridge->>Broker: PUBLISH up/status (confirmation)
    end
```

## HA → Sber State Sync (Normal Operation)

```mermaid
sequenceDiagram
    participant User as User / Automation
    participant HA as Home Assistant
    participant Bridge as SberBridge
    participant Broker as Sber MQTT Broker
    participant App as Salute / Sber App

    User->>HA: Toggle light (UI / automation)
    HA-->>Bridge: state_changed event
    Bridge->>Bridge: entity.process_state_change()
    Bridge->>Bridge: _schedule_debounced_publish(entity_id)

    Note over Bridge: Debounce 100ms (coalesce rapid changes)

    Bridge->>Bridge: build_states_list_json()
    alt Payload valid
        Bridge->>Broker: PUBLISH up/status
        Bridge->>Bridge: mark_state_published()
        Broker->>App: State update
        Note over App: UI reflects new state
    else Payload invalid
        Bridge->>Broker: PUBLISH up/status (best effort)
        Note over Bridge: mark_state_published() SKIPPED → retry next cycle
    end
```

## Sber → HA Command Flow (Normal Operation)

```mermaid
sequenceDiagram
    participant App as Salute / Sber App
    participant Cloud as Sber Cloud
    participant Broker as Sber MQTT Broker
    participant Bridge as SberBridge
    participant HA as Home Assistant

    App->>Cloud: "Салют, включи свет"
    Cloud->>Broker: PUBLISH down/commands
    Broker->>Bridge: down/commands

    Bridge->>Bridge: parse_sber_command()
    Bridge->>Bridge: entity.process_cmd()
    Bridge->>HA: hass.services.async_call(light.turn_on, context=Context)

    Note over HA: Context for logbook attribution

    HA-->>Bridge: state_changed event
    Bridge->>Bridge: fill_by_ha_state() → debounced publish
    Bridge->>Broker: PUBLISH up/status (state confirmation)
    Broker->>Cloud: Forward status
    Cloud->>App: State updated
    Note over App: Light shown as ON
```

## Reconnect with Exponential Backoff

```mermaid
flowchart TD
    A[MQTT Disconnected] --> B{running?}
    B -- No --> Z[Stop]
    B -- Yes --> C[_handle_disconnect]
    C --> D["_connected = False\n_mqtt_client = None"]
    D --> E[check_and_create_issues]
    E --> F["sleep(reconnect_interval)"]
    F --> G["reconnect_interval *= 2\n(capped at reconnect_max)"]
    G --> H[Reconnect attempt]
    H -- Success --> I["reconnect_interval = reconnect_min\nPublish config + states\nSubscribe + grace period"]
    H -- Failure --> B
```

## Message Routing

```mermaid
flowchart TD
    MSG["MQTT Message Received"] --> SIZE{payload > max?}
    SIZE -- Yes --> DROP[Drop + WARNING log]
    SIZE -- No --> LOG["_log_message() → ring buffer + WebSocket push"]
    LOG --> ROUTE{topic suffix}

    ROUTE -- "down/commands" --> GRACE{grace period?}
    GRACE -- Yes --> REJECT["REJECT + re-publish states"]
    GRACE -- No --> CMD["_handle_sber_command\nprocess_cmd → async_call"]

    ROUTE -- "down/status_request" --> STATUS["_handle_sber_status_request\npublish states for requested IDs"]
    ROUTE -- "down/config_request" --> CONFIG["_handle_sber_config_request\npublish full device config"]
    ROUTE -- "down/errors" --> ERR["_handle_sber_error\nlog warning"]
    ROUTE -- "down/change_group" --> GROUP["_handle_change_group\nstore room redefinition"]
    ROUTE -- "down/rename_device" --> RENAME["_handle_rename_device\nstore name redefinition"]
    ROUTE -- "global_config" --> GLOBAL["_handle_global_config\nlog HTTP endpoint"]
    ROUTE -- other --> UNKNOWN["debug log: unhandled"]
```

## Background Task Safety (_create_safe_task)

```mermaid
flowchart LR
    CALLER["_fire_debounced_publish\n_on_homeassistant_started\n_finalize_entity_load\n_on_ha_state_changed"] --> SAFE["_create_safe_task(coro)"]
    SAFE --> TASK["hass.async_create_task\n(eager_start=True)"]
    TASK --> CB["done_callback"]
    CB --> CHECK{exception?}
    CHECK -- Yes --> WARN["_LOGGER.warning\n(prevents silent drops)"]
    CHECK -- No --> OK[OK]
```
