import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SIMULATION = ROOT / "simulation" / "esp32-mqtt"
FIRMWARE = ROOT / "firmware" / "esp32_mqtt" / "esp32_mqtt.ino"


def _load_diagram() -> dict[str, object]:
    return json.loads((SIMULATION / "diagram.json").read_text(encoding="utf-8"))


def _firmware_pin(name: str) -> int:
    source = FIRMWARE.read_text(encoding="utf-8")
    match = re.search(rf"constexpr uint8_t {re.escape(name)} = (\d+);", source)
    assert match is not None, f"missing firmware pin constant {name}"
    return int(match.group(1))


def _diagram_edges(diagram: dict[str, object]) -> set[frozenset[str]]:
    connections = diagram["connections"]
    assert isinstance(connections, list)
    return {frozenset((connection[0], connection[1])) for connection in connections}


def test_wokwi_contains_virtual_esp32_and_feeder_hardware() -> None:
    diagram = _load_diagram()
    parts = diagram["parts"]
    assert isinstance(parts, list)
    part_types = {part["id"]: part["type"] for part in parts}

    assert part_types["esp"] == "wokwi-esp32-devkit-v1"
    assert part_types["temperature"] == "wokwi-ds18b20"
    assert part_types["manualFeed"] == "wokwi-pushbutton"
    assert part_types["coolingLed"] == "wokwi-led"
    assert part_types["pumpEnableLed"] == "wokwi-led"
    assert part_types["pumpForwardLed"] == "wokwi-led"
    assert part_types["pumpReverseLed"] == "wokwi-led"
    assert len(part_types) == len(parts), "Wokwi part IDs must be unique"


def test_wokwi_wiring_matches_firmware_pin_contract() -> None:
    edges = _diagram_edges(_load_diagram())
    expected_pin_edges = {
        "TEMP_SENSOR_PIN": ("temperature:DQ",),
        "MANUAL_FEED_BUTTON_PIN": ("manualFeed:1.l",),
        "COOLING_OUTPUT_PIN": ("coolingResistor:1",),
        "PUMP_ENABLE_PIN": ("pumpEnableResistor:1",),
        "PUMP_FORWARD_PIN": ("pumpForwardResistor:1",),
        "PUMP_REVERSE_PIN": ("pumpReverseResistor:1",),
    }

    for constant, endpoints in expected_pin_edges.items():
        esp_endpoint = f"esp:D{_firmware_pin(constant)}"
        for endpoint in endpoints:
            assert frozenset((esp_endpoint, endpoint)) in edges

    required_support_edges = {
        frozenset(("temperature:VCC", "esp:3V3")),
        frozenset(("temperature:GND", "esp:GND.1")),
        frozenset(("temperaturePullup:1", "temperature:DQ")),
        frozenset(("temperaturePullup:2", "esp:3V3")),
        frozenset(("manualFeed:2.r", "esp:GND.1")),
    }
    assert required_support_edges <= edges


def test_wokwi_configuration_uses_compiled_esp32_artifacts() -> None:
    config = tomllib.loads((SIMULATION / "wokwi.toml").read_text(encoding="utf-8"))
    wokwi = config["wokwi"]

    assert wokwi["version"] == 1
    assert wokwi["firmware"] == "../../build/wokwi/esp32_mqtt.ino.bin"
    assert wokwi["elf"] == "../../build/wokwi/esp32_mqtt.ino.elf"
    assert (SIMULATION / "diagram.json").is_file()
    assert (SIMULATION / "verify_feeder.yaml").is_file()


def test_wokwi_scenario_covers_boundaries_and_pump_phases() -> None:
    scenario = (SIMULATION / "verify_feeder.yaml").read_text(encoding="utf-8")

    for temperature in ("6.0", "5.0", "2.5"):
        assert f"value: {temperature}" in scenario
    assert "part-id: manualFeed" in scenario
    assert "delay: 500ms" in scenario
    assert "value: 1" in scenario
    assert "value: 0" in scenario
    for pin in (25, 26, 27, 33):
        assert f"pin: D{pin}" in scenario
    assert "expected:" not in scenario


def test_closed_loop_scenario_proves_command_gpio_and_completion() -> None:
    scenario = (SIMULATION / "verify_closed_loop.yaml").read_text(encoding="utf-8")
    firmware = (ROOT / "firmware" / "esp32_mqtt" / "esp32_mqtt.ino").read_text(
        encoding="utf-8"
    )

    assert "MQTT TLS enabled with CA and hostname verification" in scenario
    hardware_marker = 'Serial.println("Pump outputs: FEEDING");'
    assert "Pump outputs: FEEDING" in scenario
    assert hardware_marker in firmware
    assert firmware.index(hardware_marker) < firmware.index(
        "enqueueTelemetry(eventType, true, activeScheduleId);"
    )
    assert "completed: feeding_and_cleaning_completed" in scenario
    for assertion in (
        ("D33", 1),
        ("D26", 1),
        ("D27", 0),
        ("D33", 0),
        ("D26", 0),
        ("D27", 1),
    ):
        pin, value = assertion
        assert f"pin: {pin}\n      value: {value}" in scenario
    assert "expected:" not in scenario


def test_closed_loop_header_enables_verified_tls(tmp_path: Path) -> None:
    output = tmp_path / "feeder_secrets.h"
    environment = {
        **os.environ,
        "DEVICE_UID": "feeder-e2e-test",
        "MQTT_SHARED_SECRET": "test-signing-secret",
        "WOKWI_E2E_MQTT_HOST": "broker.hivemq.com",
        "WOKWI_E2E_MQTT_PORT": "8883",
    }
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "generate_wokwi_e2e_header.py"), "--output", str(output)],
        check=True,
        cwd=ROOT,
        env=environment,
    )
    header = output.read_text(encoding="utf-8")

    assert '#define FEEDER_DEVICE_UID "feeder-e2e-test"' in header
    assert '#define FEEDER_MQTT_HOST "broker.hivemq.com"' in header
    assert "#define FEEDER_MQTT_PORT 8883" in header
    assert "#define FEEDER_MQTT_USE_TLS 1" in header
    assert "#define FEEDER_MQTT_TLS_INSECURE 0" in header
    assert "-----BEGIN CERTIFICATE-----\\n" in header
