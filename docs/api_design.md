# API design v4

## Identities

Operators obtain a JWT from `POST /auth/token`. Devices authenticate independently with `X-Device-ID` and `X-Device-Key`; a device key never grants operator permissions.

## Telemetry ingestion

`POST /telemetry` validates:

- header and payload device IDs match;
- the device is active and its keyed credential digest matches;
- the idempotency key has not already been processed;
- the sequence number is newer than the last accepted event;
- `recorded_at` is timezone-aware, recent enough, and not too far in the future;
- sensor status and nullable temperature are internally consistent.

An exact idempotent retry is verified by a persisted canonical payload fingerprint and returns the original record. Reusing the key with changed content, or sending a different old sequence, returns `409`; concurrent insert races are recovered inside the guarded transaction.

## Operator resources

- Devices and one-time credential provisioning
- Feeding schedules with weekday, timezone, and grace-period rules
- Feeding execution history
- Durable alerts and acknowledgements
- Device commands with pending, claimed, completed, and failed states
- On-demand reliability scanning

The automatic scanner uses the same deterministic service function as the on-demand endpoint, which makes missed-feeding and offline behavior independently testable.

At a schedule's timezone-aware due time, the scanner creates one date-scoped `FEED_NOW` command containing the schedule ID. Commands use type-specific, size-bounded payloads, caller idempotency keys, conditional claims, and expiring leases. The ESP32 persists the monotonic command ID before actuation so a reclaimed lease cannot repeat a feed after reboot. It reports completion only after the physical feed and reverse-clean cycle finishes; the signed terminal result reconciles a successful execution even if completion telemetry was lost, while pump or sensor failures remain unsuccessful.
