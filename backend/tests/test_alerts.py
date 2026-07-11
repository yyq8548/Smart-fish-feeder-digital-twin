import pytest
from app.services import create_alert


@pytest.mark.parametrize(
    ("temperature", "pump_state", "sensor_status", "expected"),
    [
        (2.49, "IDLE", "OK", "warning"),
        (2.5, "IDLE", "OK", "normal"),
        (5.0, "IDLE", "OK", "normal"),
        (5.01, "IDLE", "OK", "warning"),
        (6.0, "IDLE", "OK", "critical"),
        (4.0, "ERROR", "OK", "critical"),
        (None, "IDLE", "DISCONNECTED", "critical"),
    ],
)
def test_alert_boundaries(temperature: float | None, pump_state: str, sensor_status: str, expected: str) -> None:
    level, _, _ = create_alert(temperature, pump_state, sensor_status)
    assert level == expected
