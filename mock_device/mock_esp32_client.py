import os
import random
import time
from datetime import datetime

import requests

API_URL = os.getenv("API_URL", "http://127.0.0.1:8000/telemetry")
DEVICE_API_KEY = os.getenv("DEVICE_API_KEY", "local-development-key")

TEMP_LOW = 3.0
TEMP_HIGH = 5.0

temperature = 4.3
cycle_count = 0


def get_pump_state(cycle: int) -> tuple[str, str | None]:
    if cycle % 30 == 10:
        return "FEEDING", "scheduled_feeding"

    if cycle % 30 == 11:
        return "CLEANING", "reverse_pump_cleaning"

    if cycle % 80 == 45:
        return "ERROR", "pump_error_simulation"

    return "IDLE", None


def build_payload(cycle: int) -> dict[str, object]:
    global temperature

    drift = random.uniform(-0.25, 0.35)
    temperature = max(2.0, min(6.5, temperature + drift))

    # Simulate occasional warm reservoir condition
    if cycle % 55 in [20, 21, 22, 23, 24]:
        temperature += random.uniform(0.3, 0.6)

    cooling_on = temperature > TEMP_HIGH
    pump_state, event_type = get_pump_state(cycle)

    return {
        "device_uid": "feeder-001",
        "idempotency_key": f"mock-{cycle}",
        "temperature_c": round(temperature, 2),
        "cooling_on": cooling_on,
        "pump_state": pump_state,
        "event_type": event_type,
    }


def main() -> None:
    print("Mock ESP32 telemetry client started.")
    print(f"Posting telemetry to {API_URL}")
    print("Press Ctrl+C to stop.")

    cycle = 0

    while True:
        payload = build_payload(cycle)

        try:
            response = requests.post(API_URL, json=payload, headers={"X-Device-Key": DEVICE_API_KEY}, timeout=5)
            response.raise_for_status()
            saved = response.json()

            print(
                f"[{datetime.now().strftime('%H:%M:%S')}] "
                f"temp={saved['temperature_c']}C "
                f"cooling={saved['cooling_on']} "
                f"pump={saved['pump_state']} "
                f"alert={saved['alert_level']}"
            )

        except requests.RequestException as exc:
            print(f"Failed to post telemetry: {exc}")

        cycle += 1
        time.sleep(2)


if __name__ == "__main__":
    main()
