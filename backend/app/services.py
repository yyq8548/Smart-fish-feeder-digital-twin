from typing import Literal

AlertLevel = Literal["normal", "warning", "critical"]


def create_alert(temperature_c: float, pump_state: str) -> tuple[AlertLevel, str | None]:
    if pump_state.upper() == "ERROR":
        return "critical", "Pump reported an error state."
    if temperature_c >= 6.0:
        return "critical", "Reservoir temperature is dangerously high."
    if temperature_c > 5.0:
        return "warning", "Reservoir temperature is above target range."
    if temperature_c < 2.5:
        return "warning", "Reservoir temperature is below target range."
    return "normal", None
