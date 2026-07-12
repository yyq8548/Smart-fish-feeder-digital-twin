# Physical ESP32 commissioning

This procedure connects the online operator console to a physical feeder while
keeping actuation disabled until each layer has been verified. The active cloud
firmware targets an ESP32 DevKit v1; the preserved Arduino Mega sketch is the
original offline prototype and cannot connect to MQTT by itself.

## Safety boundary

- Install a physical, normally accessible cutoff for pump and Peltier power.
- Never power either load from an ESP32 pin or its USB/3.3 V rail.
- Use a fused, correctly rated actuator supply, a common logic ground, and an
  enclosure that keeps condensation away from mains and low-voltage wiring.
- Start with the pump disconnected and LEDs or a logic analyzer on the output
  pins. Connect real loads only after the output sequence is correct.
- Calibrate with water into a measuring container before using food or
  connecting the feeder to an occupied aquarium.

## 1. Deploy and secure the control plane

Follow [cloud deployment](cloud_deployment.md). Confirm that:

1. The dashboard is available only over HTTPS.
2. MQTT port 8883 presents the expected certificate for the MQTT hostname.
3. Anonymous MQTT is rejected and the device account cannot read or write
   another device's topics.
4. The API, broker, bridge, and dashboard are healthy.
5. `.env.production` is ignored by Git and readable only by the deployment
   account.

The backend and bridge must use the same `DEVICE_UID`, device API key, and MQTT
HMAC secret configured for the ESP32. Broker passwords and HMAC secrets are
different credentials and must not be reused.

## 2. Prepare the ESP32 configuration

Copy the ignored secret template:

```text
firmware/esp32_mqtt/feeder_secrets.example.h
    → firmware/esp32_mqtt/feeder_secrets.h
```

Set the Wi-Fi SSID/password, MQTT hostname and port 8883, TLS verification,
device-scoped broker username/password, device UID, unique HMAC secret, and the
broker certificate's root CA. Keep `FEEDER_MQTT_TLS_INSECURE` set to `0`.

Before flashing, confirm `git status --short` does not list
`feeder_secrets.h`. If it appears, stop and fix the ignore rule before doing
anything else.

## 3. Verify without physical loads

Wire the DS18B20, local button, and LED indicators using [the ESP32 pin
map](wiring.md#networked-esp32-control-wiring). Leave pump and Peltier power
disconnected.

1. Flash the ESP32 and open the serial monitor.
2. Confirm Wi-Fi, NTP synchronization, verified MQTT TLS, and command-topic
   subscription complete without insecure-mode warnings.
3. Sign in to the dashboard and wait for the device to show online.
4. Change the sensor temperature and verify telemetry, cooling state, and alert
   boundaries in the dashboard.
5. Submit a 1,000 ms cleaning command and verify only the reverse and enable
   indicators activate.
6. Submit a 1,000 ms feeding command and verify forward, wait, and reverse-clean
   phases occur in order.
7. Disconnect Wi-Fi and verify the dashboard disables controls after the
   heartbeat timeout. A manual actuation request must receive HTTP 409.
8. Reconnect after a command's expiry and verify the old command does not
   actuate. The command history should show an expired or failed terminal state.

## 4. Connect and calibrate the pump

With actuator power off, connect the ESP32 to the L293D inputs and enable pin,
then connect the pump to its separately fused supply. Restore power with the
pump outlet aimed into a measuring container.

Run several short feed commands and calculate:

```text
flow rate (mL/s) = measured volume (mL) / command duration (s)
desired duration (ms) = desired dose (mL) / flow rate (mL/s) × 1000
```

Use the median of repeated measurements. Begin with 1,000 ms, remain within the
server's 500–60,000 ms bounds, and do not select a production dose until volume
is repeatable. Verify reverse cleaning does not siphon or deliver an unintended
second dose.

## 5. Connect cooling and perform failure tests

Connect the Peltier module only through a correctly rated 3.3 V-compatible
driver and fused supply. Verify automatic 3–5 °C hysteresis before trying a
forced mode. Test at least these failures with the aquarium disconnected:

- DS18B20 unplugged: pump/cooling must stop safely and a critical alert appears.
- Broker unavailable: local state remains safe and old commands do not execute
  after their deadline.
- ESP32 reboot during a command: the NVS watermark blocks replayed actuation.
- API unavailable: the console reports failure rather than showing success.
- Physical cutoff opened: actuator power is removed while ESP32 telemetry stays
  available.

## 6. Limited live rollout

Operate attended until multiple scheduled and manual cycles complete with the
expected measured dose. Review command history, feeding executions, and alerts
after every cycle. Keep the physical cutoff available and retain a manual
feeding fallback. Cloud connectivity and automated tests reduce software risk;
they do not make an uncalibrated electromechanical feeder safe for unattended
operation.
