"""Bridge real ESP32/Wokwi MQTT telemetry into the authenticated HTTP API."""

import json
import os
import time
from typing import Any

import paho.mqtt.client as mqtt
import requests
from paho.mqtt.enums import CallbackAPIVersion

MQTT_HOST = os.getenv("MQTT_HOST", "127.0.0.1")
MQTT_TOPIC = os.getenv("MQTT_TOPIC", "fish-feeder/+/telemetry")
API_URL = os.getenv("API_URL", "http://127.0.0.1:8000/telemetry")
DEVICE_API_KEY = os.getenv("DEVICE_API_KEY", "local-development-key")


def forward(payload: dict[str, object]) -> None:
    for attempt in range(4):
        try:
            response = requests.post(API_URL, json=payload, headers={"X-Device-Key": DEVICE_API_KEY}, timeout=5)
            response.raise_for_status()
            return
        except requests.RequestException:
            if attempt == 3:
                raise
            time.sleep(2**attempt)


def on_connect(
    client: mqtt.Client, _userdata: object, _flags: dict[str, object], reason_code: Any, _properties: object
) -> None:
    if not reason_code.is_failure:
        client.subscribe(MQTT_TOPIC, qos=1)


def on_message(_client: mqtt.Client, _userdata: object, message: mqtt.MQTTMessage) -> None:
    payload = json.loads(message.payload.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Telemetry payload must be a JSON object")
    forward(payload)


def main() -> None:
    client = mqtt.Client(CallbackAPIVersion.VERSION2, client_id="fish-feeder-http-bridge")
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(MQTT_HOST, 1883, 60)
    client.loop_forever()


if __name__ == "__main__":
    main()
