# Physical ESP32 acceptance checklist

Use this checklist for the first production-bound ESP32. Record timestamps, screenshots, serial excerpts, measured
GPIO states, and command IDs. A failed safety check blocks connection of the pump, Peltier, food, or aquarium.

## Test record

| Field | Value |
| --- | --- |
| Date / operator | |
| Device UID | |
| Firmware commit | |
| Manufacturing bundle directory | |
| ESP32 board / MAC suffix | |
| Dashboard account | |
| Backup manual-feeding plan | |

## 0. Safety gate: loads disconnected

- [ ] Pump and Peltier power are physically disconnected.
- [ ] GPIO 25, 26, 27, and 33 connect only to LEDs, a logic analyzer, or unpowered driver inputs.
- [ ] Driver and ESP32 logic share ground; no actuator current flows through the ESP32.
- [ ] Fused actuator supply and a reachable physical cutoff are available for later stages.
- [ ] `feeder_secrets.h` is ignored by Git and does not appear in `git status --short`.
- [ ] `FEEDER_MQTT_TLS_INSECURE` is `0`; the device has the expected CA certificate.

## 1. Factory boot and SoftAP Wi-Fi provisioning

- [ ] Erase only the test board's network namespace or start with a factory manufacturing image.
- [ ] Boot the board and capture serial output showing provisioning mode, without printing Wi-Fi/MQTT secrets.
- [ ] A phone sees `FishFeeder-<device_uid>` and requires the unique label password.
- [ ] Browse to `http://192.168.4.1/`; `/status` reports provisioning mode.
- [ ] Invalid empty/oversized credentials are rejected and not stored.
- [ ] Submit the test Wi-Fi credentials; the ESP32 restarts and the SoftAP disappears.
- [ ] Reboot once more and confirm Wi-Fi credentials persisted in NVS.

Evidence: SoftAP screenshot, serial timestamps, `/status` result, and reboot result.

## 2. QR ownership claim

- [ ] Sign in with a verified customer account that has no devices.
- [ ] Scan the printed claim QR or upload its image; the UID and proof fields populate automatically.
- [ ] Claim succeeds once and the device appears only in that customer's dashboard.
- [ ] Replaying the same QR/proof is rejected without revealing whether another customer owns the device.
- [ ] A second customer cannot access telemetry, controls, schedules, alerts, or command history.

Evidence: before/after device list, one successful claim response, one replay rejection.

## 3. Verified MQTT TLS and online heartbeat

- [ ] Serial output shows NTP synchronization before MQTT certificate verification.
- [ ] Connection uses `mqtt.smartfishfeeder.org:8883`, the device-scoped username, and verified TLS.
- [ ] Subscription is only `fish-feeder/<device_uid>/commands`.
- [ ] A heartbeat reaches the cloud with a valid HMAC and strictly increasing sequence number.
- [ ] Dashboard shows online within the configured heartbeat window and displays temperature/pump/cooling state.
- [ ] Broker ACL test confirms this credential cannot subscribe or publish under another device UID.

Evidence: redacted serial log, dashboard screenshot, broker ACL rejection.

## 4. Telemetry and boundary behavior

- [ ] Normal DS18B20 reading appears in telemetry history.
- [ ] At 5.0 C, cooling retains its current hysteresis state.
- [ ] Above 5.0 C, cooling indicator turns on and telemetry agrees.
- [ ] At 2.5 C, cooling turns off and telemetry agrees.
- [ ] A disconnected sensor reports null temperature plus an explicit failure status; it never invents a value.
- [ ] The critical sensor alert appears and resolves after reconnection.

Evidence: readings at 2.5 C and 5.0 C, one high reading, alert open/resolved screenshots.

## 5. First FEED_NOW GPIO lifecycle, still without a pump

- [ ] Submit a 1,000 ms `FEED_NOW` and record its positive command ID.
- [ ] GPIO 26 forward and GPIO 33 enable activate; GPIO 27 reverse stays off.
- [ ] Forward stops, the configured pause occurs, then GPIO 27 reverse and GPIO 33 enable activate.
- [ ] All pump outputs return to the safe idle state at the end.
- [ ] ESP32 publishes one signed terminal result only after the entire forward/pause/reverse sequence finishes.
- [ ] Command history changes `PENDING -> CLAIMED -> COMPLETED` with `feeding_and_cleaning_completed`.

Evidence: logic trace/video with timestamps, command ID, signed-result log, completed dashboard row.

## 6. Disconnect, expiry, duplicate, and reboot safety

- [ ] Disconnect Wi-Fi; dashboard marks the device offline and disables physical controls.
- [ ] A new actuation request while offline is rejected with HTTP 409.
- [ ] Create a short-lived command, keep the ESP32 disconnected past expiry, reconnect, and confirm no GPIO change.
- [ ] Redeliver an already completed command ID; no GPIO output changes and the cached terminal result may repeat.
- [ ] Start a command with loads disconnected, reboot after its NVS watermark is written, and redeliver it.
- [ ] The rebooted ESP32 blocks actuation and returns `replay_after_restart_blocked` or the recorded terminal result.
- [ ] Restore Wi-Fi and verify monotonic telemetry resumes without accepting stale sequence numbers.

Evidence: offline screenshot, rejected request, expired command row, duplicate/reboot serial trace.

## 7. Recovery provisioning

- [ ] Hold GPIO 0 low for three seconds during boot.
- [ ] Wi-Fi credentials are cleared and the SoftAP returns.
- [ ] The MQTT command watermark is not erased.
- [ ] Reconfigure Wi-Fi, reconnect with verified TLS, and confirm the device remains owned by the same customer.
- [ ] Previously consumed claim proof and previously executed command IDs remain unusable.

Evidence: serial reset message, SoftAP screenshot, ownership screen, replay rejection.

## 8. Powered actuator calibration, only after sections 0-7 pass

- [ ] Power off, connect the driver and separately fused pump supply, and aim the outlet into a measuring container.
- [ ] Run at least five 1,000 ms cycles and record delivered volume for each.
- [ ] Calculate median mL/s and choose a duration within the server's 500-60,000 ms bounds.
- [ ] Reverse cleaning does not create a second dose, siphon, or leak.
- [ ] Test the physical cutoff while keeping ESP32 telemetry powered.
- [ ] Connect cooling only through a correctly rated 3.3 V-compatible driver and fused supply.
- [ ] Complete attended scheduled and manual cycles before an occupied-aquarium trial.

## Acceptance decision

| Result | Meaning |
| --- | --- |
| PASS | Every required item passed with evidence; proceed to a limited attended aquarium rollout. |
| CONDITIONAL | Only non-safety evidence is missing; keep physical loads disconnected until completed. |
| FAIL | Any TLS, ownership, replay, GPIO-idle, sensor-failsafe, fuse, or cutoff check failed. |

Final result: __________  Operator/sign-off: __________  Timestamp: __________
