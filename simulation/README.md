# Simulation

Two Wokwi layouts are retained:

| Path | Board | Network behavior |
| --- | --- | --- |
| `diagram.json` + `libraries.txt` | Arduino Mega | Legacy physical-feeder visualization; serial output only |
| `esp32-mqtt/` | ESP32 DevKit v1 | Active digital twin; publishes live MQTT telemetry |

Use [`esp32-mqtt/README.md`](esp32-mqtt/README.md) for the end-to-end setup.
The ESP32 circuit includes a DS18B20 with a 4.7 kOhm pull-up, a manual-feed
button, and current-limited LEDs for cooling, pump enable, forward pumping, and
reverse cleaning.
