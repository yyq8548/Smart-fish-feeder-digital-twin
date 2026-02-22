# System Architecture

```text
User / Scheduler
      |
      v
Arduino Mega Firmware
      |
      +-- DS1307 RTC -> scheduled feeding window
      +-- DS18B20 -> reservoir temperature monitoring
      +-- Button -> manual feed command
      |
      v
Control Logic / State Machine
      |
      +-- Peltier MOSFET control
      +-- L293D pump forward control
      +-- L293D pump reverse cleaning
      +-- Serial event logging
      |
      v
Wokwi Simulation + Web Dashboard Mock
```

## Key Software Concepts

- Event-driven embedded control
- Sensor-based decision logic
- Time-based scheduling
- Actuator state management
- Serial telemetry logging
- Digital twin dashboard visualization