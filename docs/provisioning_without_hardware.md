# Self-service provisioning without physical hardware

This stage implements and tests every deterministic part of customer device
onboarding while the physical ESP32 is unavailable. It does not claim that RF,
flash-encryption eFuses, or powered actuators have been validated.

## Implemented flow

1. An operator runs `scripts/manufacture_device.py` once per unit.
2. The API creates a unique device API key and a high-entropy claim proof.
3. The tool creates a private firmware/server bundle and a separate printable
   QR label. The QR contains only `device_uid` and the expiring claim proof.
4. On first boot, firmware with no saved WiFi SSID starts a
   `FishFeeder-<device_uid>` SoftAP and serves `/`, `/status`, and `/configure`.
5. The customer supplies home WiFi locally. Firmware saves it in the
   `feeder_net` NVS namespace and restarts into station mode.
6. The verified customer scans the label or enters the proof manually.
   `POST /devices/claim` atomically validates and consumes the hash.
7. The already-flashed device credentials connect to the per-device MQTT topic
   namespace. Telemetry makes the dashboard online and enables the first feed.

## Security boundaries

- Claim and transfer proofs are stored only as keyed hashes.
- Initial claims expire after the configured inventory window; transfers expire
  after 24 hours by default.
- Claim and transfer proofs are single-use and rate-limited.
- QR labels never contain API keys, broker passwords, or HMAC secrets.
- MQTT usernames equal device UIDs and broker ACL `%u` substitution limits each
  device to its own topics.
- API credential rotation increments a visible credential version. Revocation
  blocks telemetry and command polling immediately; reactivation returns a new
  API key.
- A three-second GPIO 0 boot hold clears WiFi credentials without clearing the
  command replay watermark.

## Automated evidence

- Alembic migration tests cover fresh and legacy SQLite schemas.
- Backend tests cover expired claims, replay rejection, ownership transfer,
  transfer expiry, tenant isolation, API key rotation, revocation, and
  reactivation.
- Dashboard tests cover claim URLs, legacy QR URLs, JSON payloads, browser QR
  scanning, unsupported-browser fallback, transfer creation, and cancellation.
- The manufacturing test proves the printable label excludes long-term device
  secrets and that the private bundle contains a firmware header and broker
  registration entries.
- The deterministic simulator exercises factory state through WiFi save, cloud
  claim, MQTT online, first feed completion, and factory reset.
- Arduino CLI compiles the SoftAP-enabled firmware for `esp32:esp32:esp32`.
- An isolated Mosquitto container test creates and verifies primary plus
  additional per-device password entries.

## Required physical acceptance later

1. Confirm the phone sees and joins the SoftAP reliably.
2. Confirm the local setup page loads on Android and iOS; automatic captive
   portal detection is not yet claimed because no DNS redirector is included.
3. Verify WPA2 SoftAP behavior using the generated per-device password.
4. Verify WiFi credentials survive power loss and GPIO 0 reset clears only the
   network namespace.
5. Test weak signal, wrong password, router reboot, DHCP delay, and reconnection.
6. Validate TLS time synchronization and the production broker certificate.
7. Enable and validate NVS encryption, Flash Encryption, and Secure Boot on a
   sacrificial unit before burning irreversible eFuses on production stock.
8. Perform the first physical feed unloaded and supervised, then confirm the
   signed completion result in the dashboard.
