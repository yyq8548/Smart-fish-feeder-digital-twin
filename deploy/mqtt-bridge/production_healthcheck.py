"""Confirm that the bridge credentials complete an MQTT CONNECT handshake."""

import os
import sys
import threading

import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion


def main() -> int:
    host = os.environ.get("MQTT_HOST", "mqtt")
    port = int(os.environ.get("MQTT_PORT", "1883"))
    username = os.environ.get("MQTT_USERNAME", "")
    password = os.environ.get("MQTT_PASSWORD", "")
    if not username or not password:
        return 1

    finished = threading.Event()
    state = {"connected": False}

    def on_connect(
        _client: mqtt.Client,
        _userdata: object,
        _flags: dict[str, object],
        reason_code: object,
        _properties: object,
    ) -> None:
        state["connected"] = not getattr(reason_code, "is_failure", True)
        finished.set()

    client = mqtt.Client(CallbackAPIVersion.VERSION2, client_id="fish-feeder-bridge-health")
    client.username_pw_set(username, password)
    client.on_connect = on_connect
    try:
        client.connect(host, port, 5)
        client.loop_start()
        finished.wait(3)
    except OSError:
        return 1
    finally:
        client.loop_stop()
        client.disconnect()
    return 0 if state["connected"] else 1


if __name__ == "__main__":
    sys.exit(main())
