# API design v5

## Identities

Operators obtain a JWT from `POST /auth/token`. Customers register by email, verify a signed time-limited link, and use the same token endpoint after activation. Password reset links are signed, expire quickly, and become invalid as soon as the password hash changes. Devices authenticate independently with `X-Device-ID` and `X-Device-Key`; a device key never grants customer or operator permissions.

Customer accounts see only rows connected to a device whose `owner_user_id` matches the authenticated user. This ownership predicate applies to device lists, telemetry, status, schedules, feeding executions, alerts, acknowledgements, and commands. Unauthorized device identifiers return `404` so one customer cannot enumerate another customer's hardware.

An operator-provisioned device includes a one-time pairing code stored only as a keyed hash. `POST /devices/pair` consumes that code and assigns the device to the verified customer. Unpairing rotates the code before releasing ownership, which supports a controlled physical transfer without reusing the original credential.

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

At a schedule's timezone-aware due time, the scanner creates one date-scoped `FEED_NOW` command containing the schedule ID. Commands use type-specific, size-bounded payloads, caller idempotency keys, conditional claims, and expiring leases. A short deadline limits when a command may begin, while a separate result grace keeps an already claimed long-running cycle from being mislabeled before its physical terminal result can arrive. The ESP32 persists the monotonic command ID before actuation so a reclaimed lease cannot repeat a feed after reboot. It reports completion only after the physical feed and reverse-clean cycle finishes; the signed terminal result reconciles a successful execution even if completion telemetry was lost, while pump or sensor failures remain unsuccessful.
