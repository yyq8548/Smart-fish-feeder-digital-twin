# Wokwi / Arduino Wiring

| Arduino Mega Pin | Component | Purpose |
|---|---|---|
| D2 | DS18B20 data | Reservoir temperature sensing |
| D3 | L293D input / green LED | Pump forward feeding |
| D4 | L293D input / red LED | Pump reverse cleaning |
| D6 | Push button | Manual feed trigger |
| D8 | MOSFET / blue LED | Peltier cooling control |
| D10 | Pump enable / yellow LED | Pump enable signal |
| SDA 20 | DS1307 SDA | RTC data |
| SCL 21 | DS1307 SCL | RTC clock |
| 5V / GND | Sensors/modules | Power and ground |

## Networked ESP32 control wiring

The online control path runs `firmware/esp32_mqtt/esp32_mqtt.ino` on an ESP32
DevKit v1. It does not run on the original Arduino Mega without a separate
gateway. For the current firmware, move the sensor and actuator-control inputs
to these ESP32 pins:

| ESP32 pin | Component connection | Purpose |
| --- | --- | --- |
| GPIO 4 | DS18B20 data with 4.7 kΩ pull-up to 3.3 V | Reservoir temperature |
| GPIO 18 | Momentary button to ground (`INPUT_PULLUP`) | Local manual-feed input |
| GPIO 25 | Logic-level MOSFET/driver input | Peltier cooling control |
| GPIO 26 | L293D forward input | Pump forward feeding |
| GPIO 27 | L293D reverse input | Pump reverse cleaning |
| GPIO 33 | L293D enable input | Pump enable |
| 3.3 V / GND | DS18B20 and logic reference | Sensor power and common ground |

Do not power the pump or Peltier module from the ESP32. Use a correctly rated,
fused actuator supply and connect its ground to the ESP32/driver logic ground.
The Peltier switch must be a 3.3 V logic-level MOSFET or a compatible driver;
verify the L293D input thresholds and motor supply independently. Install a
physical emergency cutoff that removes actuator power without removing power
from the ESP32, so telemetry remains available after an emergency stop.

See [physical commissioning](physical_commissioning.md) before connecting the
real pump, food reservoir, or Peltier load.
