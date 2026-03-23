### Describe Device State with Humidity Value

Source: https://developers.sber.ru/docs/ru/smarthome/c2c/humidity

This example demonstrates how a device reports its current humidity state. It specifies the feature ('humidity'), its data type ('INTEGER'), and the actual measured value ('60'). This is crucial for applications to display and utilize the humidity information.

```json
{
    "states": [
        {
            "key": "humidity",
            "value": {
                "type": "INTEGER",
                "integer_value": "60"
            }
        }
    ]
}
```

--------------------------------

### Describe PIR Motion Detection State

Source: https://developers.sber.ru/docs/ru/smarthome/c2c/pir

This JSON object demonstrates how to describe the state of the PIR motion detection feature. It specifies the 'pir' key, its ENUM type, and the 'pir' enum value indicating motion detection.

```json
{
    "states": [
        {
            "key": "pir",
            "value": {
                "type": "ENUM",
                "enum_value": "pir"
            }
        }
    ]
}
```

--------------------------------

### Example Device State for volume_int

Source: https://developers.sber.ru/docs/ru/smarthome/c2c/volume-int

This example demonstrates the JSON structure for representing the state of the 'volume_int' function. It shows how to specify the current volume level (e.g., 30) using the 'integer_value' field within the 'value' object.

```json
{
    "states": [
        {
            "key": "volume_int",
            "value": {
                "type": "INTEGER",
                "integer_value": "30"
            }
        }
    ]
}
```

--------------------------------

### Device State Description with channel_int

Source: https://developers.sber.ru/docs/ru/smarthome/c2c/channel-int

This example demonstrates how to represent the state of the 'channel_int' function in a device's status. It specifies the type as INTEGER and provides the current channel value.

```json
{
    "states": [
        {
            "key": "channel_int",
            "value": {
                "type": "INTEGER",
                "integer_value": "11"
            }
        }
    ]
}
```

--------------------------------

### Describe Device State with 'online' Functionality

Source: https://developers.sber.ru/docs/ru/smarthome/c2c/online

This JSON structure illustrates how to represent the 'online' state of a device. It shows a 'states' array containing an object where the 'key' is 'online' and the 'value' specifies its boolean type and current state (true for online in this example).

```json
{
    "states": [
        {
            "key": "online",
            "value": {
                "type": "BOOL",
                "bool_value": true
            }
        }
    ]
}
```

--------------------------------

### Describe hvac_work_mode State in Device

Source: https://developers.sber.ru/docs/ru/smarthome/c2c/hvac_work_mode

This example demonstrates how to represent the current state of the 'hvac_work_mode' function within a device's state description. It specifies the type as ENUM and provides the current enum value, such as 'eco' for energy saving mode. The output is a JSON object describing device states.

```json
{
    "states": [
        {
            "key": "hvac_work_mode",
            "value": {
                "type": "ENUM",
                "enum_value": "eco"
            }
        }
    ]
}
```

--------------------------------

### Describe button_7_event State in Device Model

Source: https://developers.sber.ru/docs/ru/smarthome/c2c/button_7_event

This example demonstrates how to represent the state of the 'button_7_event' function within a device's state description. It specifies the ENUM type and the specific enum value, such as 'click' for a single press.

```json
{
    "states": [
        {
            "key": "button_7_event",
            "value": {
                "type": "ENUM",
                "enum_value": "click"
            }
        }
    ]
}
```

--------------------------------

### Successful device state response format

Source: https://developers.sber.ru/docs/ru/smarthome/c2c/webhook-post-query

This JSON structure represents a successful response from a vendor when querying device states. It details the 'devices' object, including device IDs and their 'states' with 'key', 'value', 'type', and 'type_value'.

```json
{
    "devices": {
        "id1": {
            "states": [
                {
                    "key": string,
                    "value": {
                        "type": string,
                        "type_value": object
                    }
                },
                {
                    // ...
                }
            ]
        }
    }
}
```

--------------------------------

### Describe button_4_event State in Device Model

Source: https://developers.sber.ru/docs/ru/smarthome/c2c/button_4_event

This JSON example shows how to define the state for the 'button_4_event' function. It specifies the type as ENUM and provides an example enum value for a single click, indicating a device's current status.

```json
{
    "states": [
        {
            "key": "button_4_event",
            "value": {
                "type": "ENUM",
                "enum_value": "click"
            }
        }
    ]
}
```

--------------------------------

### Describe sensor_sensitive state with medium sensitivity

Source: https://developers.sber.ru/docs/ru/smarthome/c2c/sensor_sensitive

This example shows how to describe the state of a sensor that is operating with medium sensitivity. It specifies the feature key and its enum value.

```json
{
    "states": [
        {
            "key": "sensor_sensitive",
            "value": {
                "type": "ENUM",
                "enum_value": "medium"
            }
        }
    ]
}
```

--------------------------------

### Describe signal_strength State with High Value (JSON)

Source: https://developers.sber.ru/docs/ru/smarthome/c2c/signal_strength

This example demonstrates how to represent a high signal strength state for a device. It uses a JSON object with a 'states' array, where each state has a 'key' and a 'value' object specifying the type and the enum value.

```json
{
    "states": [
        {
            "key": "signal_strength",
            "value": {
                "type": "ENUM",
                "enum_value": "high"
            }
        }
    ]
}
```

--------------------------------

### Example State: Temperature in Celsius

Source: https://developers.sber.ru/docs/ru/smarthome/c2c/temp_unit_view

This example demonstrates how to represent the current state of the 'temp_unit_view' function when a device is displaying temperature in Celsius. The 'enum_value' is set to 'c'.

```json
{
    "states": [
        {
            "key": "temp_unit_view",
            "value": {
                "type": "ENUM",
                "enum_value": "c"
            }
        }
    ]
}
```

--------------------------------

### Describe Device State for button_3_event (Click)

Source: https://developers.sber.ru/docs/ru/smarthome/c2c/button_3_event

This JSON snippet demonstrates how to describe the state of a device when the third button is clicked. It specifies the 'button_3_event' key, its type as ENUM, and the specific enum value 'click' for a single press.

```json
{
    "states": [
        {
            "key": "button_3_event",
            "value": {
                "type": "ENUM",
                "enum_value": "click"
            }
        }
    ]
}
```

--------------------------------

### Describe Device State with open_right_state

Source: https://developers.sber.ru/docs/ru/smarthome/c2c/open_right_state

This example demonstrates how to describe the state of a device's right side using the 'open_right_state' function. It specifies the 'open' enum value for a device whose right side is open.

```json
{
    "states": [
        {
            "key": "open_right_state",
            "value": {
                "type": "ENUM",
                "enum_value": "open"
            }
        }
    ]
}
```

--------------------------------

### Describe kitchen_water_temperature State in Device

Source: https://developers.sber.ru/docs/ru/smarthome/c2c/kitchen_water_temperature

This JSON snippet illustrates how a device reports its current water temperature using the 'kitchen_water_temperature' function. It specifies the data type as INTEGER and provides the integer value. This is used to communicate the device's state, with the 'value' object containing the relevant temperature data.

```json
{
    "states": [
        {
            "key": "kitchen_water_temperature",
            "value": {
                "type": "INTEGER",
                "integer_value": "60"
            }
        }
    ]
}
```

--------------------------------

### Describe Button Press State in Device Model

Source: https://developers.sber.ru/docs/ru/smarthome/c2c/button_1_event

This JSON structure illustrates how to describe the state of the 'button_1_event' function within a device model. It specifies the 'type' as ENUM and provides the 'enum_value' for a specific button press, such as 'click'. This is used to represent the current status of the button event.

```json
{
    "states": [
        {
            "key": "button_1_event",
            "value": {
                "type": "ENUM",
                "enum_value": "click"
            }
        }
    ]
}
```

--------------------------------

### Describe button_2_event State in Device Model

Source: https://developers.sber.ru/docs/ru/smarthome/c2c/button_2_event

This example demonstrates how to represent the state of the 'button_2_event' function within a device model's state. It specifies the event type and the specific enum value, such as 'click' for a single press.

```json
{
    "states": [
        {
            "key": "button_2_event",
            "value": {
                "type": "ENUM",
                "enum_value": "click"
            }
        }
    ]
}
```

--------------------------------

### Describe 'source' function state in device model

Source: https://developers.sber.ru/docs/ru/smarthome/c2c/source

This JSON snippet shows how to represent the current state of the 'source' function within a device model. It specifies the 'source' key and its value, including the type as ENUM and the current enumerated value (e.g., HDMI1).

```json
{
    "states": [
        {
            "key": "source",
            "value": {
                "type": "ENUM",
                "enum_value": "HDMI1"
            }
        }
    ]
}
```

--------------------------------

### Describe light_brightness State in Device

Source: https://developers.sber.ru/docs/ru/smarthome/c2c/light-brightness

This example demonstrates how to represent the current state of the 'light_brightness' function in a device's reported states. It specifies the type as INTEGER and provides the current integer value.

```json
{
    "states": [
        {
            "key": "light_brightness",
            "value": {
                "type": "INTEGER",
                "integer_value": "500"
            }
        }
    ]
}
```

--------------------------------

### Describe device state with 'current' - JSON

Source: https://developers.sber.ru/docs/ru/smarthome/c2c/current

This JSON structure demonstrates how to represent the current state of a device, specifically showing a current value of 9000 mA. It uses a nested structure for value type and the integer representation.

```json
{
    "states": [
        {
            "key": "current",
            "value": {
                "type": "INTEGER",
                "integer_value": "9000"
            }
        }
    ]
}
```

--------------------------------

### Describe Device State for 'on_off' (JSON)

Source: https://developers.sber.ru/docs/ru/smarthome/c2c/on-off

This JSON structure represents the state of a device, specifically for the 'on_off' function. It demonstrates how to report whether a device is currently on or off using a boolean value. This is used to reflect the actual state back to the user or system.

```json
{
    "states": [
        {
            "key": "on_off",
            "value": {
                "type": "BOOL",
                "bool_value": false
            }
        }
    ]
}
```

--------------------------------

### Add doorcontact_state to device model features

Source: https://developers.sber.ru/docs/ru/smarthome/c2c/doorcontact_state

This snippet shows how to include the 'doorcontact_state' feature in the 'features' array within a device model's configuration. This is necessary for devices that support the door contact state functionality.

```json
"features": [
    "doorcontact_state",
    // ...
 ]
```

--------------------------------

### Describe hvac_thermostat_mode State

Source: https://developers.sber.ru/docs/ru/smarthome/c2c/hvac_thermostat_mode

This example demonstrates how to represent the current state of the 'hvac_thermostat_mode' function in a device's state information. It specifies the type as ENUM and provides an example value for the 'cooling' mode.

```json
{
    "states": [
        {
            "key": "hvac_thermostat_mode",
            "value": {
                "type": "ENUM",
                "enum_value": "cooling"
            }
        }
    ]
}
```

--------------------------------

### Describe Device State with kitchen_water_low_level

Source: https://developers.sber.ru/docs/ru/smarthome/c2c/kitchen_water_low_level

This JSON example demonstrates how to represent the state of a device, specifically a kettle, when the water has run out. It uses the 'kitchen_water_low_level' key with a boolean value of 'true'.

```json
{
    "states": [
        {
            "key": "kitchen_water_low_level",
            "value": {
                "type": "BOOL",
                "bool_value": true
            }
        }
    ]
}
```

--------------------------------

### Describe vacuum_cleaner_cleaning_type State in Device Model

Source: https://developers.sber.ru/docs/ru/smarthome/c2c/vacuum_cleaner_cleaning_type

This JSON example demonstrates how to represent the state of the 'vacuum_cleaner_cleaning_type' function within a device model's 'states' array. It specifies the type as ENUM and sets the current value to 'wet' for wet cleaning.

```json
{
    "states": [
        {
            "key": "vacuum_cleaner_cleaning_type",
            "value": {
                "type": "ENUM",
                "enum_value": "wet"
            }
        }
    ]
}
```

--------------------------------

### Add 'smoke_state' Feature to Device Model

Source: https://developers.sber.ru/docs/ru/smarthome/c2c/smoke_state

This code snippet shows how to include the 'smoke_state' feature in the 'features' array within a device model's configuration. It's a simple string addition to an existing array.

```json
{
    "features": [
        "smoke_state",
        // ...
    ]
}
```

--------------------------------

### Example State Description for open_state - JSON

Source: https://developers.sber.ru/docs/ru/smarthome/c2c/open_state

This JSON example demonstrates how to describe the 'open_state' of a device when it is in the 'open' state. It specifies the key as 'open_state' and its type and enumerated value.

```json
{
    "states": [
        {
            "key": "open_state",
            "value": {
                "type": "ENUM",
                "enum_value": "open"
            }
        }
    ]
}
```

--------------------------------

### Describe Battery Low Power State (JSON)

Source: https://developers.sber.ru/docs/ru/smarthome/c2c/battery_low_power

This JSON example illustrates how to represent the 'battery_low_power' state for a device. It shows the 'key' as 'battery_low_power' and the 'value' object containing the type ('BOOL') and the actual boolean value (true if discharged, false otherwise). This is used to report the current status of the battery.

```json
{
    "states": [
        {
            "key": "battery_low_power",
            "value": {
                "type": "BOOL",
                "bool_value": true
            }
        }
    ]
}
```

--------------------------------

### Represent child_lock feature state - JSON

Source: https://developers.sber.ru/docs/ru/smarthome/c2c/child-lock

This JSON example illustrates how to represent the current state of the 'child_lock' feature. It specifies the key as 'child_lock', the type as 'BOOL', and provides the boolean value indicating whether the lock is enabled or disabled.

```json
{
    "states": [
        {
            "key": "child_lock",
            "value": {
                "type": "BOOL",
                "bool_value": true
            }
        }
    ]
}
```

--------------------------------

### Report Current Air Pressure State

Source: https://developers.sber.ru/docs/ru/smarthome/c2c/air_pressure

This JSON structure demonstrates how a device can report its current atmospheric pressure. The 'air_pressure' key holds a 'value' object, which contains the 'integer_value' representing the pressure in mmHg.

```json
{
    "states": [
        {
            "key": "air_pressure",
            "value": {
                "type": "INTEGER",
                "integer_value": "720"
            }
        }
    ]
}
```

--------------------------------

### Successful Device State Response

Source: https://developers.sber.ru/docs/ru/smarthome/c2c/api-get-state

The successful response from the Sber Smart Home API when requesting device states. It returns a JSON object containing a 'devices' key, which maps device IDs to their respective states, including key-value pairs for device functionalities.

```JSON
{
    "devices": {
        "id1": {
            "states": [
                {
                    "key": string,
                    "value": {
                        "type": string,
                        "type_value": object
                    }
                },
                {
                    // ...
                }
            ]
        }
    }
}

```

--------------------------------

### Describe 'smoke_state' as 'true' (Smoke Detected)

Source: https://developers.sber.ru/docs/ru/smarthome/c2c/smoke_state

This example demonstrates how to describe the state of a device when smoke is detected. The 'smoke_state' key is set to a boolean value of 'true' within the 'states' array, indicating the presence of smoke.

```json
{
    "states": [
        {
            "key": "smoke_state",
            "value": {
                "type": "BOOL",
                "bool_value": true
            }
        }
    ]
}
```

--------------------------------

### Describe doorcontact_state in device state

Source: https://developers.sber.ru/docs/ru/smarthome/c2c/doorcontact_state

This JSON example demonstrates how to represent the state of the doorcontact_state function. It includes the key 'doorcontact_state' and its value, which is a boolean indicating whether the contacts are closed (false) or open (true).

```json
{
    "states": [
        {
            "key": "doorcontact_state",
            "value": {
                "type": "BOOL",
                "bool_value": false
            }
        }
    ]
}
```

--------------------------------

### Device State Structure

Source: https://developers.sber.ru/docs/ru/smarthome/c2c/state

Describes the current state of a device's function. This structure is used when vendors send device state information to the smart home system, in response to device state queries, or when the smart home system commands device state changes.

```APIDOC
## Device State (state)

### Description
This structure describes the current state of a device function. For example, it can specify the current brightness level of a lamp.

It is used in the following scenarios:
- When a vendor sends smart home device state information:
  - In response to a webhook request for Device State Query (POST /query).
  - When sending a Device State Update request (POST /state).
- When the smart home system sends a Device State Change Request to a vendor (POST /command).
- When the smart home system responds to a vendor's Device State Query (GET /state).

### Parameters
#### Request Body
- **states** (array) - Required - An array of state objects for the device.
  - **key** (string) - Required - The name of the device function (e.g., 'light_mode').
  - **value** (object) - Required - The current value of the function.
    - **type** (string) - Required - The data type of the value (e.g., 'ENUM', 'NUMBER').
    - **type_value** (object) - Required - The actual value, corresponding to the specified type.

### Request Example
```json
{
    "states": [
        {
            "key": "light_mode",
            "value": {
                "type": "ENUM",
                "enum_value": "colour"
            }
        }
    ]
}
```

### Response
#### Success Response (200)
- **states** (array) - An array of state objects reflecting the device's current status.

#### Response Example
```json
{
    "states": [
        {
            "key": "light_mode",
            "value": {
                "type": "ENUM",
                "enum_value": "colour"
            }
        },
        {
            "key": "brightness",
            "value": {
                "type": "NUMBER",
                "number_value": 85
            }
        }
    ]
}
```
```

--------------------------------

### JSON Payload for Device State Change (e.g., Turning On a Socket)

Source: https://developers.sber.ru/docs/ru/smarthome/c2c/webhook-post-command

This JSON structure is used within the request body to specify which device to control and what state change to apply. It targets a specific device ID and sets the 'on_off' state to true, indicating the socket should be turned on.

```json
{
    "devices": {
        "ABCD_003": {
            "states": [
                {
                    "key": "on_off",
                    "value": {
                        "type": "BOOL",
                        "bool_value": true
                    }
                }
            ]
        }
    }
}
```

--------------------------------

### Get Device State (POST /query)

Source: https://developers.sber.ru/docs/ru/smarthome/c2c/webhook

Queries the current state of one or more devices.

```APIDOC
## POST /query

### Description
Queries the current state of one or more devices.

### Method
POST

### Endpoint
/query

### Parameters
#### Query Parameters
None

#### Path Parameters
None

#### Request Body
- **devices** (array) - Required - A list of device identifiers to query.
  - **device_id** (string) - Required - The unique identifier for the device.

### Request Example
```json
{
  "devices": [
    {
      "device_id": "device001"
    },
    {
      "device_id": "device002"
    }
  ]
}
```

### Response
#### Success Response (200)
- **devices** (array) - A list of device states.
  - **device_id** (string) - The unique identifier for the device.
  - **state** (object) - The current state of the device (e.g., {"on": true, "brightness": 50}).

#### Response Example
```json
{
  "devices": [
    {
      "device_id": "device001",
      "state": {
        "on": true,
        "brightness": 50
      }
    },
    {
      "device_id": "device002",
      "state": {
        "temperature": 22,
        "mode": "cool"
      }
    }
  ]
}
```
```

--------------------------------

### Describe State for Filter Replacement Needed

Source: https://developers.sber.ru/docs/ru/smarthome/c2c/hvac_replace_filter

This example shows how to structure the state of a device to indicate that its filter needs to be replaced. It uses a boolean value for `hvac_replace_filter` set to `true`.

```json
{
    "states": [
        {
            "key": "hvac_replace_filter",
            "value": {
                "type": "BOOL",
                "bool_value": true
            }
        }
    ]
}

```

--------------------------------

### MQTT Topic for Device Status Updates

Source: https://developers.sber.ru/docs/ru/smarthome/reference/mqtt-u-status

Данный топик используется для отправки обновлений статуса устройств от клиентского приложения к облаку Sber. Он включает в себя динамический параметр <username>.

```mqtt
sberdevices/v1/<username>/up/status
```

--------------------------------

### GET /v1/state

Source: https://developers.sber.ru/docs/ru/smarthome/c2c/api-get-state

Retrieves the current state of user devices. Vendors can request the state of specific devices by providing their IDs, or request the state of all devices associated with a user if no specific device IDs are provided.

```APIDOC
## GET /v1/state

### Description
Retrieves the current state of user devices. Vendors can request the state of specific devices by providing their IDs, or request the state of all devices associated with a user if no specific device IDs are provided.

### Method
GET

### Endpoint
`https://partners.iot.sberdevices.ru/v1/state`

### Parameters
#### Query Parameters
- **user_id** (string) - Required - Identifier for the user in the vendor's system. The Sber Smart Home retrieves and stores this ID during account linking.
- **device_ids** (list<string>) - Optional - A list of vendor-specific device identifiers for which the state should be returned. If omitted, the state of all user devices will be returned.

### Request Example
```curl
curl -i -X GET https://partners.iot.sberdevices.ru/v1/state?user_id=AB12345&device_ids=ABCD_003 \
-H "Host: example.com" \
-H "Content-Type: application/json" \
-H "Authorization: Bearer qwerty-1234-..." \
-H "X-Request-Id: abcd-0000-ifgh-..."
```

### Response
#### Success Response (200)
- **devices** (list<object>) - Required - A list containing the states of the devices. Each object in the list represents a device and its current states.

#### Response Example
```json
{
    "devices": {
        "ABCD_003": {
            "states": [
                {
                    "key": "online",
                    "value": {
                        "type": "BOOL",
                        "bool_value": true
                    }
                },
                {
                    "key": "on_off",
                    "value": {
                        "type": "BOOL",
                        "bool_value": true
                    }
                }
            ]
        }
    }
}
```

#### Error Response
```json
{
    "code": integer,
    "message": string,
    "details": list<string>
}
```
```

--------------------------------

### Describe 'open_percentage' State - JSON

Source: https://developers.sber.ru/docs/ru/smarthome/c2c/open_percentage

This JSON example demonstrates how to represent the current state of the 'open_percentage' function for a device. It shows the feature key and its integer value, indicating the device's opening percentage.

```json
{
    "states": [
        {
            "key": "open_percentage",
            "value": {
                "type": "INTEGER",
                "integer_value": "30"
            }
        }
    ]
}
```

--------------------------------

### JSON Structure for Device Status Update Message

Source: https://developers.sber.ru/docs/ru/smarthome/reference/mqtt-u-status

Структура JSON для тела сообщения, передающего изменения статуса устройств. Включает информацию об устройствах, их ID и список состояний с ключами и значениями.

```json
{
    "devices": {
        "id1": {
            "states": [
                {
                    "key": "string",
                    "value": {
                        "type": "string",
                        "type_value": object
                    }
                },
                {
                    // ...
                }
            ]
        }
    }
}
```

--------------------------------

### Describe button_left_event state with click type (JSON)

Source: https://developers.sber.ru/docs/ru/smarthome/c2c/button_left_event

This example demonstrates how to describe the state of a device when the left button has been single-clicked. It specifies the 'button_left_event' key, its type as ENUM, and the specific enum value 'click'.

```json
{
    "states": [
        {
            "key": "button_left_event",
            "value": {
                "type": "ENUM",
                "enum_value": "click"
            }
        }
    ]
}
```

--------------------------------

### Example State Representation for 'open_left_state' (JSON)

Source: https://developers.sber.ru/docs/ru/smarthome/c2c/open_left_state

This JSON example demonstrates how to represent the state of the 'open_left_state' function. It specifies the type as ENUM and provides a sample value, 'open', indicating the left side is open.

```json
{
    "states": [
        {
            "key": "open_left_state",
            "value": {
                "type": "ENUM",
                "enum_value": "open"
            }
        }
    ]
}
```

--------------------------------

### Change Device State (POST /command)

Source: https://developers.sber.ru/docs/ru/smarthome/c2c/webhook

Sends a command to change the state of a device.

```APIDOC
## POST /command

### Description
Sends a command to change the state of a device.

### Method
POST

### Endpoint
/command

### Parameters
#### Query Parameters
None

#### Path Parameters
None

#### Request Body
- **device_id** (string) - Required - The unique identifier for the device.
- **command** (object) - Required - The command to execute (e.g., {"on": false, "brightness": 100}).

### Request Example
```json
{
  "device_id": "device001",
  "command": {
    "on": false,
    "brightness": 100
  }
}
```

### Response
#### Success Response (200)
- **device_id** (string) - The unique identifier for the device.
- **status** (string) - The status of the command execution (e.g., "success", "failed").

#### Response Example
```json
{
  "device_id": "device001",
  "status": "success"
}
```
```

--------------------------------

### JSON Payload for Device Configuration

Source: https://developers.sber.ru/docs/ru/smarthome/reference/mqtt-u-config

Тело сообщения в формате JSON, содержащее список устройств с их конфигурационными данными. Каждое устройство представлено объектом с обязательными полями id, name, и default_name. Дополнительные поля могут быть добавлены по мере необходимости.

```json
{
    "devices": [
        {
            "id": string,
            "name": string,
            "default_name": string
            // ...
        },
        {
            "id": string,
            "name": string,
            "default_name": string
            // ...
        }
    ]
}
```

--------------------------------

### Describe temperature feature state (JSON)

Source: https://developers.sber.ru/docs/ru/smarthome/c2c/temperature

This example demonstrates how to represent the current state of the 'temperature' feature. It uses a JSON object with a 'states' array, where each state has a 'key' (e.g., 'temperature') and a 'value' object specifying the data type and the integer value (scaled by 10).

```json
{
    "states": [
        {
            "key": "temperature",
            "value": {
                "type": "INTEGER",
                "integer_value": "220"
            }
        }
    ]
}
```

--------------------------------

### Function State Description - JSON

Source: https://developers.sber.ru/docs/ru/smarthome/c2c/number

This JSON snippet illustrates the state description for the 'number' function when a specific digit (e.g., '1') is pressed on the remote. It shows the key as 'number' and the value as an INTEGER type with the corresponding integer_value.

```json
{
    "states": [
        {
            "key": "number",
            "value": {
                "type": "INTEGER",
                "integer_value": "1"
            }
        }
    ]
}
```

--------------------------------

### MQTT Topic for Device Configuration Update

Source: https://developers.sber.ru/docs/ru/smarthome/reference/mqtt-u-config

Этот топик MQTT используется для отправки обновлений конфигурации устройств от клиентского агента к облачной платформе Sber. Он включает переменную <username> для идентификации пользователя.

```mqtt
sberdevices/v1/<username>/up/config
```

--------------------------------

### Example Device Configuration Message

Source: https://developers.sber.ru/docs/ru/smarthome/reference/mqtt-u-config

Пример сообщения, демонстрирующий отправку конфигурации одного умного устройства (умной лампы) в Sber Smart Home. Сообщение включает топик MQTT с идентификатором пользователя и JSON-тело с информацией об устройстве.

```json
{
    "devices": [
        {
        "id": "ABCD_005",
        "name": "Ночник",
        "default_name": "Умная лампа"
        }
    ]
}
```

--------------------------------

### Describing 'mute' function state (JSON)

Source: https://developers.sber.ru/docs/ru/smarthome/c2c/mute

This JSON example shows how to describe the state of the 'mute' function for a device. It specifies the key as 'mute' and the value as a boolean type with 'bool_value' set to true, indicating silent mode is enabled.

```json
{
    "states": [
        {
            "key": "mute",
            "value": {
                "type": "BOOL",
                "bool_value": true
            }
        }
    ]
}
```

--------------------------------

### MQTT Topic Format for Status Change Commands

Source: https://developers.sber.ru/docs/ru/smarthome/reference/mqtt-d-commands

Определяет формат топика MQTT для отправки команд на изменение статуса устройств умного дома. Требует указание username для подключения к MQTT-серверу.

```plaintext
sberdevices/v1/<username>/down/commands
```

--------------------------------

### Empty Response for Device State Change

Source: https://developers.sber.ru/docs/ru/smarthome/c2c/webhook-post-command

An example of an empty JSON response, which may be returned by the vendor if the device state change is not immediate. The actual state update might be sent later via a separate POST state method.

```json
{}

```

--------------------------------

### POST /sberdevices/v1/<username>/up/status

Source: https://developers.sber.ru/docs/ru/smarthome/reference/mqtt-u-status

This endpoint is used by an agent application to send device status updates to the Sber smart home cloud. It allows for the reporting of changes in device functions, such as 'online' or 'on_off' states.

```APIDOC
## POST /sberdevices/v1/<username>/up/status

### Description
This endpoint allows an agent application to notify the Sber smart home system about changes in the status of connected devices. This is typically used when a device's state is altered, either manually or through external commands.

### Method
POST

### Endpoint
`sberdevices/v1/<username>/up/status`

### Parameters
#### Path Parameters
- **username** (string) - Required - The username used for connecting to the Sber MQTT server.

#### Request Body
- **devices** (dict<string, object>) - Required - An object containing device information. The keys are device IDs, and the values are objects detailing the states of each device.
  - **ID** (string) - Required - The unique identifier of the device within the vendor's system.
  - **states** (list<object>) - Required - A list of state objects for the device.
    - **key** (string) - Required - The name of the state (e.g., 'online', 'on_off').
    - **value** (object) - Required - An object containing the state's value and type.
      - **type** (string) - Required - The data type of the state value (e.g., 'BOOL', 'STRING', 'INTEGER').
      - **type_value** (object) - Required - The actual value of the state, corresponding to the specified type (e.g., 'bool_value' for boolean, 'string_value' for string, 'integer_value' for integer).

### Request Example
```json
{
    "devices": {
        "ABCD_003": {
            "states": [
                {
                    "key": "online",
                    "value": {
                        "type": "BOOL",
                        "bool_value": true
                    }
                },
                {
                    "key": "on_off",
                    "value": {
                        "type": "BOOL",
                        "bool_value": true
                    }
                }
            ]
        }
    }
}
```

### Response
#### Success Response (200)
- **status** (string) - Indicates the success of the status update (e.g., 'success').

#### Response Example
```json
{
  "status": "success"
}
```
```

--------------------------------

### Отправка статуса устройства умного дома через MQTT - JSON

Source: https://developers.sber.ru/docs/ru/smarthome/mqtt-diy/agent-connect

Пример JSON-сообщения для передачи текущего статуса устройства (датчика температуры и влажности с ID 'temp1') в облако Sber Smart Home. Включает информацию о наличии связи ('online') и текущей температуре. Сообщение отправляется в топик 'sberdevices/v1/username/up/status'.

```json
{
    "devices":{
        "temp1":{
            "states":[
                {
                    "key":"online",
                    "value":{"type":"BOOL","bool_value":true}
                },
                {
                    "key":"temperature",
                    "value":{"type":"INTEGER","integer_value":256}
                }
            ]
        }
    }
}
```

--------------------------------

### Describe light_colour State in Device Model

Source: https://developers.sber.ru/docs/ru/smarthome/c2c/light-colour

This JSON example illustrates how to represent the state of a device with the 'light_colour' function. It specifies the color value using the HSV color model (hue, saturation, value) and indicates maximum saturation and brightness.

```json
{
    "states": [
        {
            "key": "light_colour",
            "value": {
                "type": "COLOUR",
                "colour_value": { "h": 360, "s": 1000, "v": 1000 }
            }
        }
    ]
}
```

--------------------------------

### Example MQTT Topic for Status Change Commands

Source: https://developers.sber.ru/docs/ru/smarthome/reference/mqtt-d-commands

Пример топика MQTT, используемого для отправки команды на изменение состояния розетки. Замените <username> на актуальный логин.

```plaintext
sberdevices/v1/1234567/down/commands
```

--------------------------------

### Update Device State

Source: https://developers.sber.ru/docs/ru/smarthome/mqtt-diy/agent-connect

Use the `sberdevices/v1/username/up/status` topic to send state updates for your devices.

```APIDOC
## POST /sberdevices/v1/{username}/up/status

### Description
Send state updates for your devices to the `sberdevices/v1/username/up/status` topic.

### Method
POST

### Endpoint
`sberdevices/v1/{username}/up/status`

### Parameters

#### Path Parameters
- **username** (string) - Required - The username associated with your Sber account.

#### Request Body
- **devices** (object) - Required - An object containing device states.
  - **[deviceId]** (object) - Required - An object representing a specific device.
    - **states** (array) - Required - An array of state objects for the device.
      - **key** (string) - Required - The key identifying the state (e.g., `online`, `temperature`).
      - **value** (object) - Required - The value of the state.
        - **type** (string) - Required - The data type of the state value (e.g., `BOOL`, `INTEGER`).
        - **bool_value** (boolean) - Required if type is `BOOL` - The boolean value of the state.
        - **integer_value** (integer) - Required if type is `INTEGER` - The integer value of the state.

### Request Example
```json
{
  "devices": {
    "temp1": {
      "states": [
        {
          "key": "online",
          "value": {"type": "BOOL", "bool_value": true}
        },
        {
          "key": "temperature",
          "value": {"type": "INTEGER", "integer_value": 256}
        }
      ]
    }
  }
}
```

### Response
#### Success Response (200)
- **status** (string) - Indicates the success of the operation.

#### Response Example
```json
{
  "status": "success"
}
```
```

--------------------------------

### Topic for Status Request (MQTT)

Source: https://developers.sber.ru/docs/ru/smarthome/reference/mqtt-d-status-request

MQTT топик, используемый для отправки запроса статуса устройств от облака к приложению-агенту. Указывает на необходимость получения актуального состояния конкретных устройств.

```text
sberdevices/v1/<username>/down/status_request
```

--------------------------------

### Example Status Request Topic (MQTT)

Source: https://developers.sber.ru/docs/ru/smarthome/reference/mqtt-d-status-request

Пример MQTT топика, демонстрирующий запрос статуса для конкретного пользователя. Используется для получения состояния розетки.

```text
sberdevices/v1/1234567/down/status_request
```

--------------------------------

### Describe 'open_set' Function State

Source: https://developers.sber.ru/docs/ru/smarthome/c2c/open_set

This JSON example demonstrates how to represent the state of the 'open_set' function within a device's state description. It specifies the key as 'open_set' and the value as an ENUM with a specific value like 'open'.

```json
{
    "states": [
        {
            "key": "open_set",
            "value": {
                "type": "ENUM",
                "enum_value": "open"
            }
        }
    ]
}
```

--------------------------------

### Represent hvac_night_mode State

Source: https://developers.sber.ru/docs/ru/smarthome/c2c/hvac_night_mode

This JSON example demonstrates how to represent the state of the 'hvac_night_mode' function. It shows a device with the night mode turned off (false) and specifies the data type as boolean.

```json
{
    "states": [
        {
            "key": "hvac_night_mode",
            "value": {
                "type": "BOOL",
                "bool_value": false
            }
        }
    ]
}
```

--------------------------------

### Пример описания значения функции light_mode (JSON)

Source: https://developers.sber.ru/docs/ru/smarthome/c2c/value

Пример JSON, демонстрирующий описание функции 'light_mode' с типом значения 'ENUM' и значением 'colour'.

```json
{
   "key": "light_mode",
   "value": {
         "type": "ENUM",
         "enum_value": "colour"
   }
}
```

--------------------------------

### Enable zigbee2mqtt Web Interface

Source: https://developers.sber.ru/docs/ru/smarthome/mqtt-integrators/modules

This snippet shows how to enable the web interface for zigbee2mqtt by modifying the configuration file and restarting the service. This is useful if the default converter is insufficient. Ensure the port and host are correctly set.

```bash
nano /mnt/data/root/zigbee2mqtt/data/configuration.yaml
```

```yaml
frontend:
  port: 8081
  host: 0.0.0.0
```

```bash
systemctl restart zigbee2mqtt
```

--------------------------------

### Example Curtain Model Description

Source: https://developers.sber.ru/docs/ru/smarthome/c2c/curtain

This JSON object demonstrates the structure for describing a curtain device model. It includes device identification, hardware and software versions, a description, category, a list of supported features, and allowed values for specific features like 'open_rate'. This example omits 'open_percentage' and customizes 'open_rate' values.

```json
{
   "id": "QWERTY124",
   "manufacturer": "Xiaqara",
   "model": "SM1123456789",
   "hw_version": "3.1",
   "sw_version": "5.6",
   "description": "Умные шторы Xiaqara",
   "category": "curtain",
   "features": [
      "battery_low_power",
      "battery_percentage",
      "online",
      "open_left_percentage",
      "open_rate",
      "open_right_percentage",
      "open_right_set",
      "open_right_state",
      "open_set",
      "open_state",
      "signal_strength"
   ],
   "allowed_values": {
      "open_rate": {
         "type": "ENUM",
         "enum_values": {
            "values": [
               "auto",
               "low",
               "high"
            ]
         }
      }
   }
}
```

--------------------------------

### Describe Device State with hvac_heating_rate

Source: https://developers.sber.ru/docs/ru/smarthome/c2c/hvac_heating_rate

This JSON example shows how to describe the current state of a device when the 'hvac_heating_rate' function is active, specifically set to 'low'. It includes the key for the function and its enumerated value.

```json
{
    "states": [
        {
            "key": "hvac_heating_rate",
            "value": {
                "type": "ENUM",
                "enum_value": "low"
            }
        }
    ]
}
```

--------------------------------

### Example successful response for device state

Source: https://developers.sber.ru/docs/ru/smarthome/c2c/webhook-post-query

This JSON output shows a successful response after querying a device's state. It includes the device ID and its current states, such as 'online' and 'on_off' status.

```json
{
    "devices": {
        "ABCD_003": {
            "states": [
                {
                    "key": "online",
                    "value": {
                        "type": "BOOL",
                        "bool_value": true
                    }
                },
                {
                    "key": "on_off",
                    "value": {
                        "type": "BOOL",
                        "bool_value": true
                    }
                }
            ]
        }
    }
}
```

--------------------------------

### Создание устройства умного дома через MQTT - JSON

Source: https://developers.sber.ru/docs/ru/smarthome/mqtt-diy/agent-connect

Пример JSON-сообщения для создания нового устройства (датчика температуры и влажности) на основе предопределенной модели в Sber Smart Home. Сообщение отправляется в топик 'sberdevices/v1/username/up/config'.

```json
{
    "devices": [
        {
            "id": "temp1",
            "name": "temp1",
            "default_name": "temp1",
            "model_id": "my_temp_sensor"
        }
    ]
}
```

--------------------------------

### Describe Device State with 'direction' (JSON)

Source: https://developers.sber.ru/docs/ru/smarthome/c2c/direction

This JSON example demonstrates how to describe the current state of a device, specifically when the 'direction' function has been used. It shows the 'key' as 'direction' and its 'value' indicating the specific direction command executed, such as 'up'. This is crucial for feedback and state management.

```json
{
    "states": [
        {
            "key": "direction",
            "value": {
                "type": "ENUM",
                "enum_value": "up"
            }
        }
    ]
}
```

--------------------------------

### Example Successful Response for Smart Plug

Source: https://developers.sber.ru/docs/ru/smarthome/c2c/api-get-state

This is an example of a successful response from the Sber Smart Home API when querying the state of a smart plug. It shows the 'online' and 'on_off' states of the device 'ABCD_003' as boolean true.

```JSON
{
    "devices": {
        "ABCD_003": {
            "states": [
                {
                    "key": "online",
                    "value": {
                        "type": "BOOL",
                        "bool_value": true
                    }
                },
                {
                    "key": "on_off",
                    "value": {
                        "type": "BOOL",
                        "bool_value": true
                    }
                }
            ]
        }
    }
}

```

--------------------------------

### POST /sberdevices/v1/<username>/down/status_request

Source: https://developers.sber.ru/docs/ru/smarthome/reference/mqtt-d-status-request

Requests the current status of specified devices from an agent application. The agent should respond with the actual device states.

```APIDOC
## POST /sberdevices/v1/<username>/down/status_request

### Description
This endpoint is used by the Sber Smart Home system to request the current status of specific devices from an agent application. The agent application is expected to reply with the actual states of the requested devices.

### Method
POST

### Endpoint
`/sberdevices/v1/<username>/down/status_request`

### Parameters
#### Path Parameters
- **username** (string) - Required - The login username used for connecting to the Sber MQTT server.

#### Query Parameters
None

#### Request Body
- **devices** (list<string>) - Required - A list of device identifiers for which the status is requested.

### Request Example
```json
{
    "devices": [
        "device1_id",
        "device2_id",
        "device3_id"
    ]
}
```

### Response
#### Success Response (200)
- **(Response structure not explicitly defined in the source, but implies a status update from the agent)**

#### Response Example
(Example not provided in the source, but would typically include device states corresponding to the request)
```

--------------------------------

### Пример описания допустимых значений для функций (JSON)

Source: https://developers.sber.ru/docs/ru/smarthome/c2c/allowed_values

Пример JSON-объекта, демонстрирующий задание допустимых значений для функций hvac_water_level (FLOAT), hvac_humidity_set (INTEGER) и hvac_air_flow_power (ENUM).

```json
{
    "allowed_values": {
        "hvac_water_level": {
            "type": "FLOAT",
            "float_values": {
                "min": 0.5,
                "max": 5
            }
        },
        "hvac_humidity_set": {
            "type": "INTEGER",
            "integer_values": {
                "min": "35",
                "max": "85",
                "step": "5"
            }
        },
        "hvac_air_flow_power": {
            "type": "ENUM",
            "enum_values": {
                "values": [
                    "auto",
                    "high",
                    "low",
                    "medium"
                ]
            }
        }
    }
}
```
