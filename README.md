# Smart Fish Feeder Digital Twin

An Arduino-based embedded control simulation for a temperature-controlled automated liquid fish-feeder system.  
The original hardware prototype used a Peltier-cooled reservoir, DS18B20 temperature sensing, DS1307 RTC scheduling, L293D motor control, and a peristaltic pump with reverse-cleaning support.

This upgraded version turns the hardware prototype into a software-oriented project with:

- Refactored Arduino firmware
- Online Wokwi simulation support
- Event-driven control logic
- State-machine documentation
- Web dashboard mock for feeder telemetry visualization

---

## Features

- Temperature monitoring using DS18B20
- RTC-based scheduled feeding using DS1307
- Manual feeding button support
- Pump forward control for liquid dosing
- Pump reverse control for tube cleaning
- MOSFET-driven Peltier cooling control
- Serial telemetry and event logs
- Web dashboard mock for temperature, cooling, pump state, and event history

---

## Project Structure

```text
smart_fish_feeder_digital_twin/
├── firmware/
│   └── sketch.ino
├── simulation/
│   ├── diagram.json
│   └── libraries.txt
├── dashboard/
│   ├── index.html
│   ├── style.css
│   └── app.js
├── docs/
│   ├── architecture.md
│   ├── state_machine.md
│   └── wiring.md
└── README.md
```

---

## Embedded Control Logic

The firmware is organized around a simple state machine:

```text
IDLE -> CHECK_TEMPERATURE -> FEEDING -> CLEANING -> LOGGING -> IDLE
```

The control loop continuously checks current time, temperature, and manual button input.  
When feeding is triggered, the pump runs forward for dosing and then reverses to clean the tube.

---

## Wokwi Simulation

Use the files in `simulation/` and `firmware/` to recreate the Arduino Mega simulation in Wokwi.

### Simulated Components

| Component | Simulated Role |
|---|---|
| Arduino Mega | Main controller |
| DS18B20 | Temperature sensor |
| DS1307 RTC | Feeding schedule clock |
| Push button | Manual feed |
| Blue LED | Peltier cooling |
| Yellow LED | Pump enable |
| Green LED | Pump forward feeding |
| Red LED | Pump reverse cleaning |

---

## Dashboard Mock

The `dashboard/` folder contains a lightweight web dashboard that simulates device telemetry.

To run it locally, open:

```text
dashboard/index.html
```

The dashboard displays:

- Current reservoir temperature
- Cooling status
- Pump state
- Next feeding time
- Mock temperature history chart
- Manual feed and pump-cleaning controls
- Event logs

---

## Resume Version

```text
Smart Fish Feeder Digital Twin | Personal Project
Atlanta, GA | Apr 2023 – Jan 2024

- Built an Arduino-based automated liquid fish-feeding system and reconstructed it as a Wokwi simulation to demonstrate embedded control logic online.
- Programmed modular firmware integrating DS18B20 temperature sensing, DS1307 RTC scheduling, L293D pump control, and MOSFET-driven Peltier cooling for timed dosing and reverse-pump cleaning.
- Developed a dashboard mock to visualize feeder status, temperature history, pump state, and scheduled feeding events.
```

---

## Future Improvements

- Connect ESP32 telemetry to a real backend API
- Store temperature and feeding logs in Firebase, Supabase, or PostgreSQL
- Add notification alerts for failed feeding or abnormal temperature
- Add camera-based fish activity detection
- Add adaptive feeding based on feeding history and water quality