#include <DS18B20.h>
#include <RTClib.h>

/*
  Smart Fish Feeder Digital Twin
  Refactored Arduino firmware for temperature-controlled scheduled liquid feeding.

  Simulated / controlled components:
  - DS18B20 temperature sensor on D2
  - L293D motor direction pins on D3 and D4
  - Manual feed button on D6
  - MOSFET-driven Peltier cooling control on D8
  - Pump enable on D10
  - DS1307 RTC over I2C
*/

#define TEMP_SENSOR_PIN 2
#define PUMP_FORWARD_PIN 3
#define PUMP_REVERSE_PIN 4
#define BUTTON_PIN 6
#define PELTIER_MOSFET_PIN 8
#define PUMP_ENABLE_PIN 10

#define TEMP_LOW_THRESHOLD 3.0
#define TEMP_HIGH_THRESHOLD 5.0

#define FEED_DURATION_MS 10000
#define CLEAN_DURATION_MS 10000
#define POST_FEED_WAIT_MS 2000
#define LOOP_DELAY_MS 1000

DS18B20 ds(TEMP_SENSOR_PIN);
RTC_DS1307 rtc;

enum FeederState {
  IDLE,
  CHECK_TEMPERATURE,
  FEEDING,
  CLEANING,
  LOGGING
};

FeederState currentState = IDLE;

struct FeedingWindow {
  uint8_t startHour;
  uint8_t startMinute;
  uint8_t endHour;
  uint8_t endMinute;
};

FeedingWindow feedingWindows[] = {
  {19, 16, 19, 17},
  {21, 16, 21, 17}
};

const int FEEDING_WINDOW_COUNT = sizeof(feedingWindows) / sizeof(feedingWindows[0]);

bool alreadyFedThisMinute = false;
int lastFedMinute = -1;

char daysOfTheWeek[7][12] = {
  "Sunday", "Monday", "Tuesday", "Wednesday",
  "Thursday", "Friday", "Saturday"
};

void setup() {
  Serial.begin(9600);

  pinMode(PUMP_FORWARD_PIN, OUTPUT);
  pinMode(PUMP_REVERSE_PIN, OUTPUT);
  pinMode(PUMP_ENABLE_PIN, OUTPUT);
  pinMode(PELTIER_MOSFET_PIN, OUTPUT);
  pinMode(BUTTON_PIN, INPUT_PULLUP);

  stopPump();
  digitalWrite(PELTIER_MOSFET_PIN, LOW);

  while (ds.selectNext()) {
    ds.setAlarms(TEMP_LOW_THRESHOLD, TEMP_HIGH_THRESHOLD);
  }

  if (!rtc.begin()) {
    Serial.println("ERROR: Couldn't find RTC");
    while (1);
  }

  // For Wokwi/demo use. For production, set RTC once and then comment this out.
  rtc.adjust(DateTime(F(__DATE__), F(__TIME__)));

  Serial.println("Smart Fish Feeder Digital Twin started.");
  Serial.println("State machine: IDLE -> CHECK_TEMPERATURE -> FEEDING -> CLEANING -> LOGGING -> IDLE");
}

void loop() {
  DateTime now = rtc.now();
  float temperatureC = readTemperatureC();

  currentState = CHECK_TEMPERATURE;
  controlCooling(temperatureC);

  bool manualFeedRequested = isManualFeedRequested();
  bool scheduledFeedRequested = isScheduledFeedingTime(now);

  if (manualFeedRequested || scheduledFeedRequested) {
    currentState = FEEDING;
    logEvent(now, temperatureC, manualFeedRequested ? "Manual feeding started" : "Scheduled feeding started");

    runPumpForward(FEED_DURATION_MS);

    delay(POST_FEED_WAIT_MS);

    currentState = CLEANING;
    logEvent(now, temperatureC, "Reverse-pump cleaning started");
    runPumpReverse(CLEAN_DURATION_MS);

    currentState = LOGGING;
    logEvent(now, temperatureC, "Feeding cycle completed");
  } else {
    currentState = IDLE;
    logStatus(now, temperatureC);
  }

  updateFeedingDebounce(now);
  delay(LOOP_DELAY_MS);
}

float readTemperatureC() {
  ds.doConversion();
  return ds.getTempC();
}

void controlCooling(float temperatureC) {
  if (temperatureC > TEMP_HIGH_THRESHOLD) {
    digitalWrite(PELTIER_MOSFET_PIN, HIGH);
  } else if (temperatureC < TEMP_LOW_THRESHOLD) {
    digitalWrite(PELTIER_MOSFET_PIN, LOW);
  }
}

bool isManualFeedRequested() {
  return digitalRead(BUTTON_PIN) == LOW;
}

bool isScheduledFeedingTime(DateTime now) {
  for (int i = 0; i < FEEDING_WINDOW_COUNT; i++) {
    FeedingWindow window = feedingWindows[i];

    bool withinHour = now.hour() >= window.startHour && now.hour() <= window.endHour;
    bool afterStart = now.hour() > window.startHour || now.minute() >= window.startMinute;
    bool beforeEnd = now.hour() < window.endHour || now.minute() < window.endMinute;

    if (withinHour && afterStart && beforeEnd && !alreadyFedThisMinute) {
      return true;
    }
  }

  return false;
}

void updateFeedingDebounce(DateTime now) {
  if (now.minute() != lastFedMinute) {
    alreadyFedThisMinute = false;
    lastFedMinute = now.minute();
  } else if (currentState == FEEDING || currentState == CLEANING || currentState == LOGGING) {
    alreadyFedThisMinute = true;
  }
}

void runPumpForward(int durationMs) {
  digitalWrite(PUMP_ENABLE_PIN, HIGH);
  digitalWrite(PUMP_FORWARD_PIN, HIGH);
  digitalWrite(PUMP_REVERSE_PIN, LOW);
  delay(durationMs);
  stopPump();
}

void runPumpReverse(int durationMs) {
  digitalWrite(PUMP_ENABLE_PIN, HIGH);
  digitalWrite(PUMP_FORWARD_PIN, LOW);
  digitalWrite(PUMP_REVERSE_PIN, HIGH);
  delay(durationMs);
  stopPump();
}

void stopPump() {
  digitalWrite(PUMP_ENABLE_PIN, LOW);
  digitalWrite(PUMP_FORWARD_PIN, LOW);
  digitalWrite(PUMP_REVERSE_PIN, LOW);
}

void logStatus(DateTime now, float temperatureC) {
  Serial.print("[STATUS] ");
  printTimestamp(now);
  Serial.print(" | State: ");
  Serial.print(stateToString(currentState));
  Serial.print(" | Temperature: ");
  Serial.print(temperatureC);
  Serial.print(" C | Cooling: ");
  Serial.print(digitalRead(PELTIER_MOSFET_PIN) == HIGH ? "ON" : "OFF");
  Serial.print(" | Pump: ");
  Serial.println(digitalRead(PUMP_ENABLE_PIN) == HIGH ? "ON" : "OFF");
}

void logEvent(DateTime now, float temperatureC, const char* message) {
  Serial.print("[EVENT] ");
  printTimestamp(now);
  Serial.print(" | ");
  Serial.print(message);
  Serial.print(" | Temperature: ");
  Serial.print(temperatureC);
  Serial.println(" C");
}

void printTimestamp(DateTime time) {
  Serial.print(time.year(), DEC);
  Serial.print('/');
  Serial.print(time.month(), DEC);
  Serial.print('/');
  Serial.print(time.day(), DEC);
  Serial.print(" ");
  Serial.print(time.hour(), DEC);
  Serial.print(':');
  Serial.print(time.minute(), DEC);
  Serial.print(':');
  Serial.print(time.second(), DEC);
}

const char* stateToString(FeederState state) {
  switch (state) {
    case IDLE: return "IDLE";
    case CHECK_TEMPERATURE: return "CHECK_TEMPERATURE";
    case FEEDING: return "FEEDING";
    case CLEANING: return "CLEANING";
    case LOGGING: return "LOGGING";
    default: return "UNKNOWN";
  }
}