import pytest
from app.services import create_alert


@pytest.mark.parametrize(
    ("temperature", "pump_state", "expected"),
    [
        (2.49, "IDLE", "warning"),
        (2.5, "IDLE", "normal"),
        (5.0, "IDLE", "normal"),
        (5.01, "IDLE", "warning"),
        (6.0, "IDLE", "critical"),
        (4.0, "ERROR", "critical"),
    ],
)
def test_alert_boundaries(temperature: float, pump_state: str, expected: str) -> None:
    level, _ = create_alert(temperature, pump_state)
    assert level == expected
