"""Generate the ignored ESP32 configuration header for the Wokwi closed-loop test."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "firmware" / "esp32_mqtt" / "feeder_secrets.h"
DEFAULT_ROOT_CA = ROOT / "simulation" / "esp32-mqtt" / "amazon-root-ca-1.pem"


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value


def _quoted(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _pem_definition(pem: str) -> str:
    lines = [line for line in pem.splitlines() if line]
    if not lines or lines[0] != "-----BEGIN CERTIFICATE-----" or lines[-1] != "-----END CERTIFICATE-----":
        raise ValueError("MQTT root CA must be a PEM certificate")
    rendered = " \\\n".join(f'  "{_quoted(line)}\\n"' for line in lines)
    return f"#define FEEDER_MQTT_ROOT_CA \\\n{rendered}"


def generate_header(root_ca: Path) -> str:
    host = os.getenv("WOKWI_E2E_MQTT_HOST", "broker.hivemq.com").strip()
    port = int(os.getenv("WOKWI_E2E_MQTT_PORT", "8883"))
    if not host or not 1 <= port <= 65535:
        raise ValueError("WOKWI_E2E_MQTT_HOST and WOKWI_E2E_MQTT_PORT must identify a valid broker")

    values = {
        "FEEDER_WIFI_SSID": "Wokwi-GUEST",
        "FEEDER_WIFI_PASSWORD": "",
        "FEEDER_MQTT_HOST": host,
        "FEEDER_MQTT_USERNAME": os.getenv("WOKWI_E2E_MQTT_USERNAME", ""),
        "FEEDER_MQTT_PASSWORD": os.getenv("WOKWI_E2E_MQTT_PASSWORD", ""),
        "FEEDER_DEVICE_UID": _required("DEVICE_UID"),
        "FEEDER_MQTT_SHARED_SECRET": _required("MQTT_SHARED_SECRET"),
    }
    if values["FEEDER_MQTT_PASSWORD"] and not values["FEEDER_MQTT_USERNAME"]:
        raise ValueError("WOKWI_E2E_MQTT_PASSWORD requires WOKWI_E2E_MQTT_USERNAME")

    definitions = ["#pragma once", ""]
    definitions.extend(f'#define {name} "{_quoted(value)}"' for name, value in values.items())
    definitions.extend(
        [
            f"#define FEEDER_MQTT_PORT {port}",
            "#define FEEDER_MQTT_USE_TLS 1",
            "#define FEEDER_MQTT_TLS_INSECURE 0",
            _pem_definition(root_ca.read_text(encoding="ascii")),
            "",
        ]
    )
    return "\n".join(definitions)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--root-ca",
        type=Path,
        default=Path(os.getenv("WOKWI_E2E_MQTT_ROOT_CA_FILE", DEFAULT_ROOT_CA)),
    )
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(generate_header(args.root_ca), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
