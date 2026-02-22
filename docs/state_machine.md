# Feeder State Machine

```text
IDLE
  |
  v
CHECK_TEMPERATURE
  |
  +-- temperature > high threshold -> Cooling ON
  +-- temperature < low threshold  -> Cooling OFF
  |
  v
FEEDING
  |
  +-- pump forward for configured duration
  |
  v
CLEANING
  |
  +-- pump reverse for configured duration
  |
  v
LOGGING
  |
  v
IDLE
```

## State Descriptions

| State | Purpose |
|---|---|
| IDLE | Default monitoring state |
| CHECK_TEMPERATURE | Reads DS18B20 data and controls Peltier cooling |
| FEEDING | Runs the peristaltic pump forward for liquid food dosing |
| CLEANING | Reverses the pump to clean the tube after feeding |
| LOGGING | Prints event status to Serial Monitor |