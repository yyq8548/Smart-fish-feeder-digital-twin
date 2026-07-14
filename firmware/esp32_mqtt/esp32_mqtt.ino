#include <Arduino.h>
#include <ArduinoJson.h>
#include <DallasTemperature.h>
#include <OneWire.h>
#include <Preferences.h>
#include <PubSubClient.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <ctype.h>
#include <esp_system.h>
#include <math.h>
#include <mbedtls/md.h>
#include <sys/time.h>
#include <time.h>

#if __has_include("feeder_secrets.h")
#include "feeder_secrets.h"
#endif

/*
  Smart Fish Feeder Digital Twin - ESP32 MQTT firmware

  Wokwi defaults:
    WiFi: Wokwi-GUEST (open network, channel 6)
    MQTT: broker.hivemq.com:1883 (public demo broker)
    Topics: fish-feeder/feeder-001/{telemetry,commands,command-results}

  Override any FEEDER_* value with a compiler build flag for real hardware.
  Do not put production credentials in this file.
*/

#ifndef FEEDER_WIFI_SSID
#define FEEDER_WIFI_SSID "Wokwi-GUEST"
#endif

#ifndef FEEDER_WIFI_PASSWORD
#define FEEDER_WIFI_PASSWORD ""
#endif

#ifndef FEEDER_MQTT_HOST
#define FEEDER_MQTT_HOST "broker.hivemq.com"
#endif

#ifndef FEEDER_MQTT_PORT
#define FEEDER_MQTT_PORT 1883
#endif

#ifndef FEEDER_MQTT_USE_TLS
#define FEEDER_MQTT_USE_TLS 0
#endif

#ifndef FEEDER_MQTT_TLS_INSECURE
#define FEEDER_MQTT_TLS_INSECURE 0
#endif

#ifndef FEEDER_MQTT_ROOT_CA
#define FEEDER_MQTT_ROOT_CA ""
#endif

#if FEEDER_MQTT_TLS_INSECURE && !FEEDER_MQTT_USE_TLS
#error "FEEDER_MQTT_TLS_INSECURE requires FEEDER_MQTT_USE_TLS=1"
#endif

#ifndef FEEDER_MQTT_USERNAME
#define FEEDER_MQTT_USERNAME ""
#endif

#ifndef FEEDER_MQTT_PASSWORD
#define FEEDER_MQTT_PASSWORD ""
#endif

#ifndef FEEDER_MQTT_SHARED_SECRET
#define FEEDER_MQTT_SHARED_SECRET "local-development-mqtt-secret"
#endif

#ifndef FEEDER_DEVICE_UID
#define FEEDER_DEVICE_UID "feeder-001"
#endif

#ifndef FEEDER_MQTT_TOPIC_PREFIX
#define FEEDER_MQTT_TOPIC_PREFIX "fish-feeder"
#endif

constexpr uint8_t TEMP_SENSOR_PIN = 4;
constexpr uint8_t MANUAL_FEED_BUTTON_PIN = 18;
constexpr uint8_t COOLING_OUTPUT_PIN = 25;
constexpr uint8_t PUMP_FORWARD_PIN = 26;
constexpr uint8_t PUMP_REVERSE_PIN = 27;
constexpr uint8_t PUMP_ENABLE_PIN = 33;

constexpr float TEMP_LOW_THRESHOLD_C = 3.0F;
constexpr float TEMP_HIGH_THRESHOLD_C = 5.0F;
constexpr float API_MIN_TEMPERATURE_C = -20.0F;
constexpr float API_MAX_TEMPERATURE_C = 80.0F;

constexpr uint32_t FEED_DURATION_MS = 10000;
constexpr uint32_t POST_FEED_WAIT_MS = 2000;
constexpr uint32_t CLEAN_DURATION_MS = 10000;
constexpr uint32_t SENSOR_INTERVAL_MS = 2000;
constexpr uint32_t HEARTBEAT_INTERVAL_MS = 5000;
constexpr uint32_t RECONNECT_INTERVAL_MS = 5000;
constexpr uint32_t BUTTON_DEBOUNCE_MS = 50;
constexpr size_t TELEMETRY_QUEUE_CAPACITY = 12;
constexpr size_t COMMAND_RESULT_QUEUE_CAPACITY = 12;
constexpr size_t COMMAND_HISTORY_CAPACITY = 16;
constexpr size_t MAX_RUNTIME_SCHEDULES = 8;
constexpr size_t COMMAND_MESSAGE_CAPACITY = 2048;
constexpr size_t COMMAND_PAYLOAD_CAPACITY = 1536;
constexpr uint32_t MIN_COMMAND_DURATION_MS = 500;
constexpr uint32_t MAX_COMMAND_DURATION_MS = 60000;
constexpr char TELEMETRY_CANONICAL_VERSION[] = "fish-feeder-telemetry-v1";

// The optional runtime schedule mirror preserves backend schedule metadata.
// It never actuates locally; only server-dispatched FEED_NOW commands can feed.
struct RuntimeSchedule {
  uint32_t id;
  uint8_t hour;
  uint8_t minute;
  uint8_t daysMask;
  bool enabled;
};

enum class CyclePhase : uint8_t {
  IDLE,
  FEEDING,
  POST_FEED_WAIT,
  CLEANING,
  ERROR,
};

enum class CoolingMode : uint8_t {
  AUTOMATIC,
  FORCED_ON,
  FORCED_OFF,
};

enum class ActiveCommandKind : uint8_t {
  NONE,
  FEED_NOW,
  CLEAN_PUMP,
};

struct TelemetrySnapshot {
  uint64_t sequenceNumber;
  bool temperatureAvailable;
  int32_t temperatureMilliC;
  bool coolingOn;
  char pumpState[12];
  char sensorStatus[16];
  char eventType[48];
  char recordedAt[21];
  char idempotencyKey[100];
  char signature[65];
  bool hasScheduleId;
  uint32_t scheduleId;
};

struct CommandResultSnapshot {
  uint64_t commandId;
  char status[12];
  char result[96];
  char signature[65];
};

struct CommandHistoryEntry {
  bool used;
  bool completed;
  uint64_t commandId;
  char status[12];
  char result[96];
};

#if FEEDER_MQTT_USE_TLS
WiFiClientSecure networkClient;
#else
WiFiClient networkClient;
#endif
PubSubClient mqttClient(networkClient);
OneWire oneWire(TEMP_SENSOR_PIN);
DallasTemperature temperatureSensor(&oneWire);
Preferences preferences;

CyclePhase cyclePhase = CyclePhase::IDLE;
CoolingMode coolingMode = CoolingMode::AUTOMATIC;
ActiveCommandKind activeCommandKind = ActiveCommandKind::NONE;
uint64_t activeCommandId = 0;
uint32_t phaseStartedAtMs = 0;
uint32_t activeFeedDurationMs = FEED_DURATION_MS;
uint32_t activeCleanDurationMs = CLEAN_DURATION_MS;
uint32_t activeScheduleId = 0;
bool coolingOn = false;
bool sensorInitialized = false;
bool sensorHealthy = false;
bool sensorDisconnected = false;
float lastValidTemperatureC = 4.0F;

TelemetrySnapshot telemetryQueue[TELEMETRY_QUEUE_CAPACITY];
size_t telemetryHead = 0;
size_t telemetryTail = 0;
size_t telemetryCount = 0;

CommandResultSnapshot commandResultQueue[COMMAND_RESULT_QUEUE_CAPACITY];
size_t commandResultHead = 0;
size_t commandResultTail = 0;
size_t commandResultCount = 0;

CommandHistoryEntry commandHistory[COMMAND_HISTORY_CAPACITY] = {};
size_t commandHistoryCursor = 0;
uint64_t persistedCommandWatermark = 0;
bool commandWatermarkReady = false;

RuntimeSchedule runtimeSchedules[MAX_RUNTIME_SCHEDULES] = {};
size_t runtimeScheduleCount = 0;

char commandMessageBuffer[COMMAND_MESSAGE_CAPACITY];
char commandCanonicalBuffer[COMMAND_MESSAGE_CAPACITY];
char expectedCommandSignature[65];
StaticJsonDocument<COMMAND_MESSAGE_CAPACITY> commandDocument;
StaticJsonDocument<COMMAND_PAYLOAD_CAPACITY> commandPayloadDocument;

uint64_t sequenceCounter = 0;
uint32_t bootNonce = 0;

uint32_t lastSensorReadAtMs = 0;
uint32_t lastHeartbeatAtMs = 0;
uint32_t lastWiFiAttemptAtMs = 0;
uint32_t lastMqttAttemptAtMs = 0;
uint32_t buttonChangedAtMs = 0;
int lastButtonReading = HIGH;
int stableButtonState = HIGH;

bool timeConfigured = false;
bool startupTelemetryQueued = false;
bool mqttTransportConfigured = false;
char mqttTelemetryTopic[128];
char mqttCommandTopic[128];
char mqttCommandResultTopic[128];
char mqttClientId[64];

void failActiveCommand(const char *result);
void onMqttMessage(char *topic, uint8_t *payload, unsigned int length);

bool clockIsReady() {
  return time(nullptr) >= 1700000000;
}

bool formatUtcNow(char *destination, size_t destinationSize) {
  const time_t now = time(nullptr);
  if (now < 1700000000) {
    return false;
  }

  struct tm utcTime;
  gmtime_r(&now, &utcTime);
  return strftime(destination, destinationSize, "%Y-%m-%dT%H:%M:%SZ", &utcTime) > 0;
}

uint64_t nextSequenceNumber() {
  struct timeval currentTime;
  gettimeofday(&currentTime, nullptr);
  uint64_t candidate = static_cast<uint64_t>(currentTime.tv_sec) * 1000000ULL +
                       static_cast<uint64_t>(currentTime.tv_usec);
  if (candidate <= sequenceCounter) {
    candidate = sequenceCounter + 1;
  }

  sequenceCounter = candidate;
  return sequenceCounter;
}

void setPumpOutputs(bool enabled, bool forward, bool reverse) {
  digitalWrite(PUMP_ENABLE_PIN, enabled ? HIGH : LOW);
  digitalWrite(PUMP_FORWARD_PIN, forward ? HIGH : LOW);
  digitalWrite(PUMP_REVERSE_PIN, reverse ? HIGH : LOW);
}

void stopPump() {
  setPumpOutputs(false, false, false);
}

const char *pumpStateForTelemetry() {
  if (!sensorHealthy || cyclePhase == CyclePhase::ERROR) {
    return "ERROR";
  }

  switch (cyclePhase) {
    case CyclePhase::FEEDING:
      return "FEEDING";
    case CyclePhase::CLEANING:
      return "CLEANING";
    case CyclePhase::IDLE:
    case CyclePhase::POST_FEED_WAIT:
    default:
      return "IDLE";
  }
}

const char *sensorStatusForTelemetry() {
  if (sensorHealthy) {
    return "OK";
  }
  return sensorDisconnected ? "DISCONNECTED" : "ERROR";
}

bool computeHmacHex(const char *canonical, char *signature, size_t signatureSize) {
  if (strlen(FEEDER_MQTT_SHARED_SECRET) == 0) {
    Serial.println("ERROR FEEDER_MQTT_SHARED_SECRET must not be empty");
    return false;
  }
  if (signatureSize < 65) {
    Serial.println("ERROR HMAC signature buffer is too small");
    return false;
  }

  const mbedtls_md_info_t *sha256 = mbedtls_md_info_from_type(MBEDTLS_MD_SHA256);
  if (sha256 == nullptr) {
    Serial.println("ERROR SHA-256 is unavailable");
    return false;
  }

  uint8_t digest[32];
  const int result = mbedtls_md_hmac(
      sha256,
      reinterpret_cast<const unsigned char *>(FEEDER_MQTT_SHARED_SECRET),
      strlen(FEEDER_MQTT_SHARED_SECRET),
      reinterpret_cast<const unsigned char *>(canonical),
      strlen(canonical),
      digest);
  if (result != 0) {
    Serial.print("ERROR HMAC-SHA256 failed, code=");
    Serial.println(result);
    return false;
  }

  constexpr char HEX_DIGITS[] = "0123456789abcdef";
  for (size_t index = 0; index < sizeof(digest); ++index) {
    signature[index * 2] = HEX_DIGITS[digest[index] >> 4];
    signature[index * 2 + 1] = HEX_DIGITS[digest[index] & 0x0F];
  }
  signature[64] = '\0';
  return true;
}

bool constantTimeSignatureMatches(const char *actual, const char *expected) {
  if (actual == nullptr || expected == nullptr) {
    return false;
  }

  const size_t actualLength = strlen(actual);
  uint8_t difference = actualLength == 64 ? 0 : 1;
  for (size_t index = 0; index < 64; ++index) {
    const char actualCharacter = index < actualLength ? actual[index] : '\0';
    difference |= static_cast<uint8_t>(actualCharacter ^ expected[index]);
  }
  return difference == 0;
}

bool appendCanonicalField(
    char *canonical,
    size_t canonicalSize,
    size_t &used,
    const char *label,
    const char *value) {
  if (used >= canonicalSize) {
    return false;
  }
  const size_t valueLength = strlen(value);
  const int written = snprintf(
      canonical + used,
      canonicalSize - used,
      "\n%s:%u:%s",
      label,
      static_cast<unsigned int>(valueLength),
      value);
  if (written < 0 || static_cast<size_t>(written) >= canonicalSize - used) {
    return false;
  }
  used += static_cast<size_t>(written);
  return true;
}

bool signTelemetrySnapshot(TelemetrySnapshot &snapshot) {
  char canonical[768];
  const int headerLength = snprintf(canonical, sizeof(canonical), "%s", TELEMETRY_CANONICAL_VERSION);
  if (headerLength < 0 || static_cast<size_t>(headerLength) >= sizeof(canonical)) {
    return false;
  }
  size_t used = static_cast<size_t>(headerLength);

  char sequenceNumber[24];
  char temperatureMilliC[16];
  char scheduleId[16];
  snprintf(
      sequenceNumber,
      sizeof(sequenceNumber),
      "%llu",
      static_cast<unsigned long long>(snapshot.sequenceNumber));
  if (snapshot.temperatureAvailable) {
    snprintf(
        temperatureMilliC,
        sizeof(temperatureMilliC),
        "%ld",
        static_cast<long>(snapshot.temperatureMilliC));
  } else {
    snprintf(temperatureMilliC, sizeof(temperatureMilliC), "null");
  }
  if (snapshot.hasScheduleId) {
    snprintf(scheduleId, sizeof(scheduleId), "%lu", static_cast<unsigned long>(snapshot.scheduleId));
  } else {
    snprintf(scheduleId, sizeof(scheduleId), "null");
  }

  const char *eventType = snapshot.eventType[0] == '\0' ? "null" : snapshot.eventType;
  const bool canonicalComplete =
      appendCanonicalField(canonical, sizeof(canonical), used, "device_uid", FEEDER_DEVICE_UID) &&
      appendCanonicalField(canonical, sizeof(canonical), used, "sequence_number", sequenceNumber) &&
      appendCanonicalField(canonical, sizeof(canonical), used, "idempotency_key", snapshot.idempotencyKey) &&
      appendCanonicalField(canonical, sizeof(canonical), used, "recorded_at", snapshot.recordedAt) &&
      appendCanonicalField(canonical, sizeof(canonical), used, "temperature_mdeg", temperatureMilliC) &&
      appendCanonicalField(canonical, sizeof(canonical), used, "cooling_on", snapshot.coolingOn ? "1" : "0") &&
      appendCanonicalField(canonical, sizeof(canonical), used, "pump_state", snapshot.pumpState) &&
      appendCanonicalField(canonical, sizeof(canonical), used, "sensor_status", snapshot.sensorStatus) &&
      appendCanonicalField(canonical, sizeof(canonical), used, "event_type", eventType) &&
      appendCanonicalField(canonical, sizeof(canonical), used, "schedule_id", scheduleId);
  if (!canonicalComplete) {
    Serial.println("ERROR telemetry HMAC canonical payload overflow");
    return false;
  }
  return computeHmacHex(canonical, snapshot.signature, sizeof(snapshot.signature));
}

bool enqueueTelemetry(const char *eventType, bool important, uint32_t scheduleId = 0) {
  if (!clockIsReady()) {
    return false;
  }

  // Heartbeats are disposable. Do not build a stale heartbeat backlog while
  // disconnected or while state-change events are waiting to be published.
  if (!important && (!mqttClient.connected() || telemetryCount > 0)) {
    return false;
  }

  if (telemetryCount == TELEMETRY_QUEUE_CAPACITY) {
    if (!important) {
      return false;
    }

    Serial.println("WARN telemetry queue full; dropping oldest snapshot");
    telemetryHead = (telemetryHead + 1) % TELEMETRY_QUEUE_CAPACITY;
    --telemetryCount;
  }

  TelemetrySnapshot &snapshot = telemetryQueue[telemetryTail];
  snapshot.sequenceNumber = nextSequenceNumber();
  snapshot.temperatureAvailable = sensorHealthy;
  snapshot.temperatureMilliC = static_cast<int32_t>(lroundf(lastValidTemperatureC * 1000.0F));
  snapshot.coolingOn = coolingOn;
  snapshot.hasScheduleId = scheduleId > 0;
  snapshot.scheduleId = scheduleId;
  snprintf(snapshot.pumpState, sizeof(snapshot.pumpState), "%s", pumpStateForTelemetry());
  snprintf(snapshot.sensorStatus, sizeof(snapshot.sensorStatus), "%s", sensorStatusForTelemetry());
  snprintf(snapshot.eventType, sizeof(snapshot.eventType), "%s", eventType == nullptr ? "" : eventType);

  if (!formatUtcNow(snapshot.recordedAt, sizeof(snapshot.recordedAt))) {
    return false;
  }

  snprintf(
      snapshot.idempotencyKey,
      sizeof(snapshot.idempotencyKey),
      "mqtt-%08lx-%llu",
      static_cast<unsigned long>(bootNonce),
      static_cast<unsigned long long>(snapshot.sequenceNumber));
  if (!signTelemetrySnapshot(snapshot)) {
    return false;
  }

  telemetryTail = (telemetryTail + 1) % TELEMETRY_QUEUE_CAPACITY;
  ++telemetryCount;
  return true;
}

void publishQueuedTelemetry() {
  if (!mqttClient.connected() || telemetryCount == 0) {
    return;
  }

  const TelemetrySnapshot &snapshot = telemetryQueue[telemetryHead];
  StaticJsonDocument<768> document;
  document["device_uid"] = FEEDER_DEVICE_UID;
  document["sequence_number"] = snapshot.sequenceNumber;
  document["idempotency_key"] = snapshot.idempotencyKey;
  document["recorded_at"] = snapshot.recordedAt;
  if (snapshot.temperatureAvailable) {
    document["temperature_c"] = static_cast<float>(snapshot.temperatureMilliC) / 1000.0F;
  } else {
    document["temperature_c"] = nullptr;
  }
  document["cooling_on"] = snapshot.coolingOn;
  document["pump_state"] = snapshot.pumpState;
  document["sensor_status"] = snapshot.sensorStatus;
  if (snapshot.eventType[0] != '\0') {
    document["event_type"] = snapshot.eventType;
  } else {
    document["event_type"] = nullptr;
  }
  if (snapshot.hasScheduleId) {
    document["schedule_id"] = snapshot.scheduleId;
  } else {
    document["schedule_id"] = nullptr;
  }
  document["signature"] = snapshot.signature;

  char payload[768];
  const size_t payloadLength = serializeJson(document, payload, sizeof(payload));
  if (payloadLength == 0 || payloadLength >= sizeof(payload)) {
    Serial.println("ERROR telemetry serialization overflow");
    return;
  }

  if (!mqttClient.publish(mqttTelemetryTopic, reinterpret_cast<const uint8_t *>(payload), payloadLength, false)) {
    Serial.print("WARN MQTT publish failed, state=");
    Serial.println(mqttClient.state());
    return;
  }

  Serial.print("MQTT ");
  Serial.print(mqttTelemetryTopic);
  Serial.print(" <- ");
  Serial.println(payload);

  telemetryHead = (telemetryHead + 1) % TELEMETRY_QUEUE_CAPACITY;
  --telemetryCount;
}

CommandHistoryEntry *findCommandHistory(uint64_t commandId) {
  for (CommandHistoryEntry &entry : commandHistory) {
    if (entry.used && entry.commandId == commandId) {
      return &entry;
    }
  }
  return nullptr;
}

void initializeCommandWatermark() {
  commandWatermarkReady = preferences.begin("fishfeeder", false);
  if (!commandWatermarkReady) {
    Serial.println("ERROR failed to open NVS command watermark; command actuation disabled");
    return;
  }
  persistedCommandWatermark = preferences.getULong64("cmd_watermark", 0);
  Serial.printf("Command watermark: %llu\n", static_cast<unsigned long long>(persistedCommandWatermark));
}

bool persistCommandWatermark(uint64_t commandId) {
  if (!commandWatermarkReady || commandId <= persistedCommandWatermark) {
    return false;
  }
  if (preferences.putULong64("cmd_watermark", commandId) != sizeof(uint64_t)) {
    Serial.println("ERROR failed to persist NVS command watermark");
    return false;
  }
  persistedCommandWatermark = commandId;
  return true;
}

CommandHistoryEntry *rememberCommand(uint64_t commandId) {
  for (size_t offset = 0; offset < COMMAND_HISTORY_CAPACITY; ++offset) {
    const size_t index = (commandHistoryCursor + offset) % COMMAND_HISTORY_CAPACITY;
    CommandHistoryEntry &entry = commandHistory[index];
    if (!entry.used || entry.completed) {
      entry.used = true;
      entry.completed = false;
      entry.commandId = commandId;
      entry.status[0] = '\0';
      entry.result[0] = '\0';
      commandHistoryCursor = (index + 1) % COMMAND_HISTORY_CAPACITY;
      return &entry;
    }
  }
  return nullptr;
}

bool enqueueCommandResult(uint64_t commandId, const char *status, const char *result) {
  if (commandResultCount == COMMAND_RESULT_QUEUE_CAPACITY) {
    Serial.println("WARN command-result queue full; dropping oldest result");
    commandResultHead = (commandResultHead + 1) % COMMAND_RESULT_QUEUE_CAPACITY;
    --commandResultCount;
  }

  CommandResultSnapshot &snapshot = commandResultQueue[commandResultTail];
  snapshot.commandId = commandId;
  snprintf(snapshot.status, sizeof(snapshot.status), "%s", status);
  snprintf(snapshot.result, sizeof(snapshot.result), "%s", result);

  char canonical[256];
  const int canonicalLength = snprintf(
      canonical,
      sizeof(canonical),
      "%llu|%s|%s",
      static_cast<unsigned long long>(snapshot.commandId),
      snapshot.status,
      snapshot.result);
  if (canonicalLength < 0 || static_cast<size_t>(canonicalLength) >= sizeof(canonical) ||
      !computeHmacHex(canonical, snapshot.signature, sizeof(snapshot.signature))) {
    Serial.println("ERROR command-result signing failed");
    return false;
  }

  commandResultTail = (commandResultTail + 1) % COMMAND_RESULT_QUEUE_CAPACITY;
  ++commandResultCount;
  return true;
}

void finishCommand(uint64_t commandId, const char *status, const char *result) {
  CommandHistoryEntry *entry = findCommandHistory(commandId);
  if (entry != nullptr) {
    entry->completed = true;
    snprintf(entry->status, sizeof(entry->status), "%s", status);
    snprintf(entry->result, sizeof(entry->result), "%s", result);
  }
  enqueueCommandResult(commandId, status, result);
}

void completeActiveCommand(const char *result) {
  if (activeCommandKind == ActiveCommandKind::NONE) {
    return;
  }
  const uint64_t completedCommandId = activeCommandId;
  Serial.printf(
      "Command %llu completed: %s\n",
      static_cast<unsigned long long>(completedCommandId),
      result);
  activeCommandKind = ActiveCommandKind::NONE;
  activeCommandId = 0;
  finishCommand(completedCommandId, "COMPLETED", result);
}

void failActiveCommand(const char *result) {
  if (activeCommandKind == ActiveCommandKind::NONE) {
    return;
  }
  const uint64_t failedCommandId = activeCommandId;
  activeCommandKind = ActiveCommandKind::NONE;
  activeCommandId = 0;
  finishCommand(failedCommandId, "FAILED", result);
}

void publishQueuedCommandResult() {
  if (!mqttClient.connected() || commandResultCount == 0) {
    return;
  }

  const CommandResultSnapshot &snapshot = commandResultQueue[commandResultHead];
  StaticJsonDocument<512> document;
  document["device_uid"] = FEEDER_DEVICE_UID;
  document["command_id"] = snapshot.commandId;
  document["status"] = snapshot.status;
  document["result"] = snapshot.result;
  document["signature"] = snapshot.signature;

  char payload[512];
  const size_t payloadLength = serializeJson(document, payload, sizeof(payload));
  if (payloadLength == 0 || payloadLength >= sizeof(payload)) {
    Serial.println("ERROR command-result serialization overflow");
    return;
  }

  if (!mqttClient.publish(
          mqttCommandResultTopic, reinterpret_cast<const uint8_t *>(payload), payloadLength, false)) {
    Serial.print("WARN MQTT command-result publish failed, state=");
    Serial.println(mqttClient.state());
    return;
  }

  Serial.print("MQTT ");
  Serial.print(mqttCommandResultTopic);
  Serial.print(" <- ");
  Serial.println(payload);
  commandResultHead = (commandResultHead + 1) % COMMAND_RESULT_QUEUE_CAPACITY;
  --commandResultCount;
}

void beginWiFiConnection() {
  Serial.print("Connecting WiFi SSID=");
  Serial.println(FEEDER_WIFI_SSID);
  WiFi.disconnect();

  if (strcmp(FEEDER_WIFI_SSID, "Wokwi-GUEST") == 0) {
    WiFi.begin(FEEDER_WIFI_SSID, FEEDER_WIFI_PASSWORD, 6);
  } else {
    WiFi.begin(FEEDER_WIFI_SSID, FEEDER_WIFI_PASSWORD);
  }
}

bool configureMqttTransport() {
  if (strlen(FEEDER_MQTT_PASSWORD) > 0 && strlen(FEEDER_MQTT_USERNAME) == 0) {
    Serial.println("ERROR FEEDER_MQTT_PASSWORD requires FEEDER_MQTT_USERNAME");
    return false;
  }

#if FEEDER_MQTT_USE_TLS
#if FEEDER_MQTT_TLS_INSECURE
  networkClient.setInsecure();
  Serial.println(
      "WARN MQTT TLS certificate verification disabled; FEEDER_MQTT_TLS_INSECURE is development-only");
#else
  if (strlen(FEEDER_MQTT_ROOT_CA) == 0) {
    Serial.println("ERROR verified MQTT TLS requires FEEDER_MQTT_ROOT_CA");
    return false;
  }
  networkClient.setCACert(FEEDER_MQTT_ROOT_CA);
  Serial.println("MQTT TLS enabled with CA and hostname verification");
#endif
#else
  Serial.println("WARN MQTT transport is plaintext; use only for Wokwi or a trusted local network");
#endif

  return true;
}

void maintainWiFi(uint32_t nowMs) {
  if (WiFi.status() == WL_CONNECTED) {
    if (!timeConfigured) {
      configTime(0, 0, "pool.ntp.org", "time.nist.gov");
      timeConfigured = true;
      Serial.print("WiFi connected, IP=");
      Serial.println(WiFi.localIP());
    }
    return;
  }

  if (nowMs - lastWiFiAttemptAtMs < RECONNECT_INTERVAL_MS) {
    return;
  }

  lastWiFiAttemptAtMs = nowMs;
  beginWiFiConnection();
}

void maintainMqtt(uint32_t nowMs) {
  if (!mqttTransportConfigured || WiFi.status() != WL_CONNECTED || mqttClient.connected()) {
    return;
  }

#if FEEDER_MQTT_USE_TLS && !FEEDER_MQTT_TLS_INSECURE
  // X.509 certificate validity cannot be checked safely before NTP sets UTC.
  if (!clockIsReady()) {
    return;
  }
#endif

  if (nowMs - lastMqttAttemptAtMs < RECONNECT_INTERVAL_MS) {
    return;
  }

  lastMqttAttemptAtMs = nowMs;
  bool connected = false;
  if (strlen(FEEDER_MQTT_USERNAME) == 0) {
    connected = mqttClient.connect(mqttClientId);
  } else {
    connected = mqttClient.connect(mqttClientId, FEEDER_MQTT_USERNAME, FEEDER_MQTT_PASSWORD);
  }

  if (connected) {
    if (!mqttClient.subscribe(mqttCommandTopic, 1)) {
      Serial.println("WARN MQTT command subscription failed");
      mqttClient.disconnect();
      return;
    }
    Serial.print("MQTT connected to ");
    Serial.print(FEEDER_MQTT_HOST);
    Serial.print(':');
    Serial.println(FEEDER_MQTT_PORT);
  } else {
    Serial.print("WARN MQTT connect failed, state=");
    Serial.println(mqttClient.state());
  }
}

void updateCooling() {
  if (!sensorHealthy) {
    coolingOn = false;
  } else {
    switch (coolingMode) {
      case CoolingMode::FORCED_ON:
        coolingOn = true;
        break;
      case CoolingMode::FORCED_OFF:
        coolingOn = false;
        break;
      case CoolingMode::AUTOMATIC:
      default:
        if (lastValidTemperatureC > TEMP_HIGH_THRESHOLD_C) {
          coolingOn = true;
        } else if (lastValidTemperatureC < TEMP_LOW_THRESHOLD_C) {
          coolingOn = false;
        }
        break;
    }
  }

  digitalWrite(COOLING_OUTPUT_PIN, coolingOn ? HIGH : LOW);
}

void abortForSensorError() {
  stopPump();
  coolingOn = false;
  digitalWrite(COOLING_OUTPUT_PIN, LOW);
  cyclePhase = CyclePhase::ERROR;
  phaseStartedAtMs = millis();
  failActiveCommand("temperature_sensor_error");
}

void readTemperature(uint32_t nowMs) {
  if (sensorInitialized && nowMs - lastSensorReadAtMs < SENSOR_INTERVAL_MS) {
    return;
  }

  lastSensorReadAtMs = nowMs;
  temperatureSensor.requestTemperatures();
  const float readingC = temperatureSensor.getTempCByIndex(0);
  const bool validReading = isfinite(readingC) && readingC != DEVICE_DISCONNECTED_C &&
                            readingC >= API_MIN_TEMPERATURE_C && readingC <= API_MAX_TEMPERATURE_C;

  if (!validReading) {
    const bool errorIsNew = !sensorInitialized || sensorHealthy;
    sensorInitialized = true;
    sensorHealthy = false;
    sensorDisconnected = readingC == DEVICE_DISCONNECTED_C;
    abortForSensorError();
    if (errorIsNew) {
      enqueueTelemetry("temperature_sensor_error", true, activeScheduleId);
    }
    activeScheduleId = 0;
    return;
  }

  const bool recovered = sensorInitialized && !sensorHealthy;
  sensorInitialized = true;
  sensorHealthy = true;
  sensorDisconnected = false;
  lastValidTemperatureC = readingC;

  if (cyclePhase == CyclePhase::ERROR) {
    cyclePhase = CyclePhase::IDLE;
    phaseStartedAtMs = nowMs;
  }

  updateCooling();
  if (recovered) {
    enqueueTelemetry("temperature_sensor_recovered", true);
  }
}

bool startFeedingCycle(
    const char *eventType,
    uint32_t nowMs,
    uint32_t feedDurationMs = FEED_DURATION_MS,
    uint32_t scheduleId = 0) {
  if (!sensorHealthy || cyclePhase != CyclePhase::IDLE) {
    return false;
  }

  cyclePhase = CyclePhase::FEEDING;
  phaseStartedAtMs = nowMs;
  activeFeedDurationMs = feedDurationMs;
  activeCleanDurationMs = CLEAN_DURATION_MS;
  activeScheduleId = scheduleId;
  setPumpOutputs(true, true, false);
  enqueueTelemetry(eventType, true, activeScheduleId);
  return true;
}

bool startCleaningCycle(uint32_t nowMs, uint32_t cleanDurationMs) {
  if (!sensorHealthy || cyclePhase != CyclePhase::IDLE) {
    return false;
  }

  cyclePhase = CyclePhase::CLEANING;
  phaseStartedAtMs = nowMs;
  activeCleanDurationMs = cleanDurationMs;
  activeScheduleId = 0;
  setPumpOutputs(true, false, true);
  enqueueTelemetry("command_cleaning_started", true);
  return true;
}

void updateFeedingCycle(uint32_t nowMs) {
  const uint32_t elapsedMs = nowMs - phaseStartedAtMs;

  switch (cyclePhase) {
    case CyclePhase::FEEDING:
      if (elapsedMs >= activeFeedDurationMs) {
        stopPump();
        cyclePhase = CyclePhase::POST_FEED_WAIT;
        phaseStartedAtMs = nowMs;
        enqueueTelemetry("feeding_dispensed", true, activeScheduleId);
      }
      break;

    case CyclePhase::POST_FEED_WAIT:
      if (elapsedMs >= POST_FEED_WAIT_MS) {
        cyclePhase = CyclePhase::CLEANING;
        phaseStartedAtMs = nowMs;
        setPumpOutputs(true, false, true);
        enqueueTelemetry("cleaning_started", true, activeScheduleId);
      }
      break;

    case CyclePhase::CLEANING:
      if (elapsedMs >= activeCleanDurationMs) {
        const bool cleaningCommand = activeCommandKind == ActiveCommandKind::CLEAN_PUMP;
        stopPump();
        cyclePhase = CyclePhase::IDLE;
        phaseStartedAtMs = nowMs;
        enqueueTelemetry(
            cleaningCommand ? "cleaning_cycle_completed" : "feeding_cycle_completed", true, activeScheduleId);
        activeScheduleId = 0;
        if (cleaningCommand) {
          completeActiveCommand("cleaning_completed");
        } else if (activeCommandKind == ActiveCommandKind::FEED_NOW) {
          completeActiveCommand("feeding_and_cleaning_completed");
        }
      }
      break;

    case CyclePhase::IDLE:
    case CyclePhase::ERROR:
    default:
      break;
  }
}

void updateManualFeedButton(uint32_t nowMs) {
  const int reading = digitalRead(MANUAL_FEED_BUTTON_PIN);
  if (reading != lastButtonReading) {
    lastButtonReading = reading;
    buttonChangedAtMs = nowMs;
  }

  if (nowMs - buttonChangedAtMs < BUTTON_DEBOUNCE_MS || reading == stableButtonState) {
    return;
  }

  stableButtonState = reading;
  if (stableButtonState == LOW) {
    startFeedingCycle("manual_feeding", nowMs);
  }
}

bool parseCommandPayload(const char *payloadJson) {
  commandPayloadDocument.clear();
  const DeserializationError error = deserializeJson(commandPayloadDocument, payloadJson);
  if (error || !commandPayloadDocument.is<JsonObject>()) {
    Serial.print("WARN invalid command payload_json: ");
    Serial.println(error.c_str());
    return false;
  }
  return true;
}

bool parseCommandDuration(const char *payloadJson, uint32_t defaultDurationMs, uint32_t &durationMs) {
  if (!parseCommandPayload(payloadJson)) {
    return false;
  }

  const JsonVariantConst durationValue = commandPayloadDocument["duration_ms"];
  if (durationValue.isNull()) {
    durationMs = defaultDurationMs;
    return true;
  }
  if (!durationValue.is<unsigned long>()) {
    return false;
  }

  durationMs = durationValue.as<uint32_t>();
  return durationMs >= MIN_COMMAND_DURATION_MS && durationMs <= MAX_COMMAND_DURATION_MS;
}

bool parseFeedCommand(const char *payloadJson, uint32_t &durationMs, uint32_t &scheduleId) {
  if (!parseCommandDuration(payloadJson, FEED_DURATION_MS, durationMs)) {
    return false;
  }

  const JsonVariantConst scheduleIdValue = commandPayloadDocument["schedule_id"];
  if (scheduleIdValue.isNull()) {
    scheduleId = 0;
    return true;
  }
  if (!scheduleIdValue.is<unsigned long>()) {
    return false;
  }
  scheduleId = scheduleIdValue.as<uint32_t>();
  return scheduleId > 0;
}

bool parseDaysMask(JsonVariantConst daysValue, uint8_t &daysMask) {
  daysMask = 0;
  if (daysValue.is<JsonArrayConst>()) {
    for (JsonVariantConst dayValue : daysValue.as<JsonArrayConst>()) {
      if (!dayValue.is<int>()) {
        return false;
      }
      const int day = dayValue.as<int>();
      if (day < 0 || day > 6) {
        return false;
      }
      daysMask |= static_cast<uint8_t>(1U << day);
    }
    return daysMask != 0;
  }

  if (!daysValue.is<const char *>()) {
    return false;
  }
  const char *cursor = daysValue.as<const char *>();
  while (*cursor != '\0') {
    while (isspace(static_cast<unsigned char>(*cursor))) {
      ++cursor;
    }
    char *end = nullptr;
    const long day = strtol(cursor, &end, 10);
    if (end == cursor || day < 0 || day > 6) {
      return false;
    }
    daysMask |= static_cast<uint8_t>(1U << day);
    cursor = end;
    while (isspace(static_cast<unsigned char>(*cursor))) {
      ++cursor;
    }
    if (*cursor == ',') {
      ++cursor;
    } else if (*cursor != '\0') {
      return false;
    }
  }
  return daysMask != 0;
}

bool synchronizeSchedules(const char *payloadJson, char *result, size_t resultSize) {
  if (!parseCommandPayload(payloadJson)) {
    return false;
  }

  const JsonVariantConst schedulesValue = commandPayloadDocument["schedules"];
  if (!schedulesValue.is<JsonArrayConst>()) {
    return false;
  }
  const JsonArrayConst schedules = schedulesValue.as<JsonArrayConst>();
  if (schedules.size() > MAX_RUNTIME_SCHEDULES) {
    return false;
  }

  RuntimeSchedule stagedSchedules[MAX_RUNTIME_SCHEDULES] = {};
  size_t stagedCount = 0;
  for (JsonVariantConst scheduleValue : schedules) {
    if (!scheduleValue.is<JsonObjectConst>()) {
      return false;
    }
    const JsonObjectConst item = scheduleValue.as<JsonObjectConst>();
    if (!item["id"].is<unsigned long>() || !item["hour"].is<int>() || !item["minute"].is<int>()) {
      return false;
    }

    RuntimeSchedule &schedule = stagedSchedules[stagedCount];
    schedule.id = item["id"].as<uint32_t>();
    const int hour = item["hour"].as<int>();
    const int minute = item["minute"].as<int>();
    if (schedule.id == 0 || hour < 0 || hour > 23 || minute < 0 || minute > 59 ||
        !parseDaysMask(item["days_of_week"], schedule.daysMask)) {
      return false;
    }
    schedule.hour = static_cast<uint8_t>(hour);
    schedule.minute = static_cast<uint8_t>(minute);

    const JsonVariantConst enabledValue = item["enabled"];
    if (!enabledValue.isNull() && !enabledValue.is<bool>()) {
      return false;
    }
    schedule.enabled = enabledValue.isNull() ? true : enabledValue.as<bool>();

    const JsonVariantConst timezoneValue = item["timezone"];
    if (!timezoneValue.isNull() && !timezoneValue.is<const char *>()) {
      return false;
    }
    for (size_t previousIndex = 0; previousIndex < stagedCount; ++previousIndex) {
      if (stagedSchedules[previousIndex].id == schedule.id) {
        return false;
      }
    }
    ++stagedCount;
  }

  for (size_t index = 0; index < stagedCount; ++index) {
    runtimeSchedules[index] = stagedSchedules[index];
  }
  runtimeScheduleCount = stagedCount;
  snprintf(result, resultSize, "schedules_synced:%u", static_cast<unsigned int>(stagedCount));
  return true;
}

bool applyCoolingCommand(const char *payloadJson, const char *&result) {
  if (!parseCommandPayload(payloadJson)) {
    return false;
  }

  CoolingMode requestedMode;
  const JsonVariantConst modeValue = commandPayloadDocument["mode"];
  if (!modeValue.isNull()) {
    if (!modeValue.is<const char *>()) {
      return false;
    }
    const char *mode = modeValue.as<const char *>();
    if (strcmp(mode, "AUTO") == 0) {
      requestedMode = CoolingMode::AUTOMATIC;
      result = "cooling_auto";
    } else if (strcmp(mode, "FORCED_ON") == 0) {
      requestedMode = CoolingMode::FORCED_ON;
      result = "cooling_forced_on";
    } else if (strcmp(mode, "FORCED_OFF") == 0) {
      requestedMode = CoolingMode::FORCED_OFF;
      result = "cooling_forced_off";
    } else {
      return false;
    }
  } else {
    const JsonVariantConst enabledValue = commandPayloadDocument["enabled"];
    if (!enabledValue.is<bool>()) {
      return false;
    }
    if (enabledValue.as<bool>()) {
      requestedMode = CoolingMode::FORCED_ON;
      result = "cooling_forced_on";
    } else {
      requestedMode = CoolingMode::FORCED_OFF;
      result = "cooling_forced_off";
    }
  }

  if (requestedMode == CoolingMode::FORCED_ON && !sensorHealthy) {
    result = "temperature_sensor_unavailable";
    return false;
  }
  coolingMode = requestedMode;
  updateCooling();
  enqueueTelemetry("cooling_mode_changed", true);
  return true;
}

bool parseDigits(const char *value, size_t offset, size_t count, int &parsed) {
  parsed = 0;
  for (size_t index = 0; index < count; ++index) {
    const char character = value[offset + index];
    if (character < '0' || character > '9') {
      return false;
    }
    parsed = parsed * 10 + (character - '0');
  }
  return true;
}

bool isLeapYear(int year) {
  return (year % 4 == 0 && year % 100 != 0) || year % 400 == 0;
}

int daysInMonth(int year, int month) {
  static const uint8_t days[] = {31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31};
  if (month < 1 || month > 12) {
    return 0;
  }
  if (month == 2 && isLeapYear(year)) {
    return 29;
  }
  return days[month - 1];
}

int64_t daysSinceUnixEpoch(int year, unsigned int month, unsigned int day) {
  year -= month <= 2;
  const int era = (year >= 0 ? year : year - 399) / 400;
  const unsigned int yearOfEra = static_cast<unsigned int>(year - era * 400);
  const int shiftedMonth = static_cast<int>(month) + (month > 2 ? -3 : 9);
  const unsigned int dayOfYear = static_cast<unsigned int>((153 * shiftedMonth + 2) / 5) + day - 1;
  const unsigned int dayOfEra = yearOfEra * 365 + yearOfEra / 4 - yearOfEra / 100 + dayOfYear;
  return static_cast<int64_t>(era) * 146097 + static_cast<int64_t>(dayOfEra) - 719468;
}

bool parseUtcTimestamp(const char *value, time_t &parsedTime) {
  if (value == nullptr) {
    return false;
  }
  const size_t length = strlen(value);
  if (length < 20 || length > 40 || value[4] != '-' || value[7] != '-' || value[10] != 'T' ||
      value[13] != ':' || value[16] != ':') {
    return false;
  }

  int year;
  int month;
  int day;
  int hour;
  int minute;
  int second;
  if (!parseDigits(value, 0, 4, year) || !parseDigits(value, 5, 2, month) ||
      !parseDigits(value, 8, 2, day) || !parseDigits(value, 11, 2, hour) ||
      !parseDigits(value, 14, 2, minute) || !parseDigits(value, 17, 2, second) || year < 1970 ||
      month < 1 || month > 12 || day < 1 || day > daysInMonth(year, month) || hour > 23 || minute > 59 ||
      second > 59) {
    return false;
  }

  size_t timezoneOffset = 19;
  if (timezoneOffset < length && value[timezoneOffset] == '.') {
    ++timezoneOffset;
    const size_t fractionStart = timezoneOffset;
    while (timezoneOffset < length && isdigit(static_cast<unsigned char>(value[timezoneOffset]))) {
      ++timezoneOffset;
    }
    if (timezoneOffset == fractionStart) {
      return false;
    }
  }

  const bool usesZulu = timezoneOffset + 1 == length && value[timezoneOffset] == 'Z';
  const bool usesExplicitUtc = timezoneOffset + 6 == length && value[timezoneOffset] == '+' &&
                               value[timezoneOffset + 1] == '0' && value[timezoneOffset + 2] == '0' &&
                               value[timezoneOffset + 3] == ':' && value[timezoneOffset + 4] == '0' &&
                               value[timezoneOffset + 5] == '0';
  if (!usesZulu && !usesExplicitUtc) {
    return false;
  }

  const int64_t epochSeconds = daysSinceUnixEpoch(year, month, day) * 86400 + hour * 3600 + minute * 60 + second;
  parsedTime = static_cast<time_t>(epochSeconds);
  if (static_cast<int64_t>(parsedTime) != epochSeconds) {
    return false;
  }

  struct tm normalized = {};
  gmtime_r(&parsedTime, &normalized);
  return normalized.tm_year == year - 1900 && normalized.tm_mon == month - 1 && normalized.tm_mday == day &&
         normalized.tm_hour == hour && normalized.tm_min == minute && normalized.tm_sec == second;
}

bool verifyCommandSignature(
    uint64_t commandId,
    const char *commandType,
    const char *payloadJson,
    const char *expiresAt,
    const char *signature) {
  int canonicalLength;
  if (expiresAt == nullptr) {
    canonicalLength = snprintf(
        commandCanonicalBuffer,
        sizeof(commandCanonicalBuffer),
        "%llu|%s|%s",
        static_cast<unsigned long long>(commandId),
        commandType,
        payloadJson);
  } else {
    canonicalLength = snprintf(
        commandCanonicalBuffer,
        sizeof(commandCanonicalBuffer),
        "%llu|%s|%s|%s",
        static_cast<unsigned long long>(commandId),
        commandType,
        payloadJson,
        expiresAt);
  }
  if (canonicalLength < 0 || static_cast<size_t>(canonicalLength) >= sizeof(commandCanonicalBuffer) ||
      !computeHmacHex(commandCanonicalBuffer, expectedCommandSignature, sizeof(expectedCommandSignature))) {
    return false;
  }
  return constantTimeSignatureMatches(signature, expectedCommandSignature);
}

void handleVerifiedCommand(
    uint64_t commandId,
    const char *commandType,
    const char *payloadJson,
    bool commandExpired) {
  CommandHistoryEntry *existing = findCommandHistory(commandId);
  if (existing != nullptr) {
    if (existing->completed) {
      enqueueCommandResult(existing->commandId, existing->status, existing->result);
    } else {
      Serial.println("INFO duplicate in-progress command ignored");
    }
    return;
  }

  if (commandWatermarkReady && commandId <= persistedCommandWatermark) {
    if (rememberCommand(commandId) != nullptr) {
      finishCommand(commandId, "FAILED", "replay_after_restart_blocked");
    } else {
      enqueueCommandResult(commandId, "FAILED", "replay_after_restart_blocked");
    }
    return;
  }

  if (rememberCommand(commandId) == nullptr) {
    Serial.println("ERROR command history capacity exhausted");
    return;
  }
  if (!persistCommandWatermark(commandId)) {
    finishCommand(commandId, "FAILED", "command_watermark_persist_failed");
    return;
  }

  if (commandExpired) {
    finishCommand(commandId, "FAILED", "command_expired");
    return;
  }

  if (strcmp(commandType, "FEED_NOW") == 0) {
    uint32_t durationMs = FEED_DURATION_MS;
    uint32_t scheduleId = 0;
    if (!parseFeedCommand(payloadJson, durationMs, scheduleId)) {
      finishCommand(commandId, "FAILED", "invalid_feed_payload");
      return;
    }
    if (!sensorHealthy) {
      finishCommand(commandId, "FAILED", "temperature_sensor_unavailable");
      return;
    }
    const char *eventType = scheduleId > 0 ? "scheduled_feeding" : "manual_feeding";
    if (!startFeedingCycle(eventType, millis(), durationMs, scheduleId)) {
      finishCommand(commandId, "FAILED", "device_busy");
      return;
    }
    activeCommandKind = ActiveCommandKind::FEED_NOW;
    activeCommandId = commandId;
    Serial.printf(
        "Command %llu started: FEED_NOW\n",
        static_cast<unsigned long long>(commandId));
    return;
  }

  if (strcmp(commandType, "CLEAN_PUMP") == 0) {
    uint32_t durationMs = CLEAN_DURATION_MS;
    if (!parseCommandDuration(payloadJson, CLEAN_DURATION_MS, durationMs)) {
      finishCommand(commandId, "FAILED", "invalid_clean_payload");
      return;
    }
    if (!sensorHealthy) {
      finishCommand(commandId, "FAILED", "temperature_sensor_unavailable");
      return;
    }
    if (!startCleaningCycle(millis(), durationMs)) {
      finishCommand(commandId, "FAILED", "device_busy");
      return;
    }
    activeCommandKind = ActiveCommandKind::CLEAN_PUMP;
    activeCommandId = commandId;
    return;
  }

  if (strcmp(commandType, "SET_COOLING") == 0) {
    const char *result = "invalid_cooling_payload";
    if (applyCoolingCommand(payloadJson, result)) {
      finishCommand(commandId, "COMPLETED", result);
    } else {
      finishCommand(commandId, "FAILED", result);
    }
    return;
  }

  if (strcmp(commandType, "SYNC_SCHEDULES") == 0) {
    char result[96];
    if (synchronizeSchedules(payloadJson, result, sizeof(result))) {
      finishCommand(commandId, "COMPLETED", result);
    } else {
      finishCommand(commandId, "FAILED", "invalid_schedule_payload");
    }
    return;
  }

  finishCommand(commandId, "FAILED", "unsupported_command_type");
}

void onMqttMessage(char *topic, uint8_t *payload, unsigned int length) {
  if (strcmp(topic, mqttCommandTopic) != 0) {
    return;
  }
  if (length == 0 || length >= sizeof(commandMessageBuffer)) {
    Serial.println("WARN rejected oversized MQTT command");
    return;
  }

  memcpy(commandMessageBuffer, payload, length);
  commandMessageBuffer[length] = '\0';
  commandDocument.clear();
  const DeserializationError error = deserializeJson(commandDocument, commandMessageBuffer);
  if (error || !commandDocument.is<JsonObject>()) {
    Serial.println("WARN rejected malformed MQTT command");
    return;
  }

  const JsonVariantConst commandIdValue = commandDocument["command_id"];
  const JsonVariantConst commandTypeValue = commandDocument["command_type"];
  const JsonVariantConst payloadJsonValue = commandDocument["payload_json"];
  const JsonVariantConst expiresAtValue = commandDocument["expires_at"];
  const JsonVariantConst signatureValue = commandDocument["signature"];
  if (!commandIdValue.is<unsigned long long>() || !commandTypeValue.is<const char *>() ||
      !payloadJsonValue.is<const char *>() ||
      (!expiresAtValue.isNull() && !expiresAtValue.is<const char *>()) ||
      !signatureValue.is<const char *>()) {
    Serial.println("WARN rejected MQTT command with missing fields");
    return;
  }

  const uint64_t commandId = commandIdValue.as<uint64_t>();
  const char *commandType = commandTypeValue.as<const char *>();
  const char *payloadJson = payloadJsonValue.as<const char *>();
  const char *expiresAt = expiresAtValue.is<const char *>() ? expiresAtValue.as<const char *>() : nullptr;
  const char *signature = signatureValue.as<const char *>();
  if (commandId == 0 || strlen(commandType) == 0 || strlen(commandType) > 40 ||
      (expiresAt != nullptr && (strlen(expiresAt) == 0 || strlen(expiresAt) > 40)) ||
      !verifyCommandSignature(commandId, commandType, payloadJson, expiresAt, signature)) {
    Serial.println("WARN rejected MQTT command with invalid signature");
    return;
  }

  bool commandExpired = false;
  if (expiresAt != nullptr) {
    time_t expiryTime;
    if (!parseUtcTimestamp(expiresAt, expiryTime)) {
      Serial.println("WARN rejected MQTT command with invalid expires_at");
      return;
    }
    if (!clockIsReady()) {
      Serial.println("WARN rejected expiring MQTT command before UTC synchronization");
      return;
    }
    commandExpired = time(nullptr) >= expiryTime;
  }

  handleVerifiedCommand(commandId, commandType, payloadJson, commandExpired);
}

void setup() {
  Serial.begin(115200);
  initializeCommandWatermark();

  pinMode(MANUAL_FEED_BUTTON_PIN, INPUT_PULLUP);
  pinMode(COOLING_OUTPUT_PIN, OUTPUT);
  pinMode(PUMP_FORWARD_PIN, OUTPUT);
  pinMode(PUMP_REVERSE_PIN, OUTPUT);
  pinMode(PUMP_ENABLE_PIN, OUTPUT);
  stopPump();
  digitalWrite(COOLING_OUTPUT_PIN, LOW);

  temperatureSensor.begin();
  temperatureSensor.setResolution(10);

  bootNonce = esp_random() ^ static_cast<uint32_t>(ESP.getEfuseMac());
  snprintf(
      mqttTelemetryTopic,
      sizeof(mqttTelemetryTopic),
      "%s/%s/telemetry",
      FEEDER_MQTT_TOPIC_PREFIX,
      FEEDER_DEVICE_UID);
  snprintf(
      mqttCommandTopic,
      sizeof(mqttCommandTopic),
      "%s/%s/commands",
      FEEDER_MQTT_TOPIC_PREFIX,
      FEEDER_DEVICE_UID);
  snprintf(
      mqttCommandResultTopic,
      sizeof(mqttCommandResultTopic),
      "%s/%s/command-results",
      FEEDER_MQTT_TOPIC_PREFIX,
      FEEDER_DEVICE_UID);
  snprintf(
      mqttClientId,
      sizeof(mqttClientId),
      "fish-feeder-%04lx-%08lx",
      static_cast<unsigned long>(ESP.getEfuseMac() & 0xFFFF),
      static_cast<unsigned long>(bootNonce));

  mqttTransportConfigured = configureMqttTransport();
  mqttClient.setServer(FEEDER_MQTT_HOST, FEEDER_MQTT_PORT);
  mqttClient.setCallback(onMqttMessage);
  mqttClient.setBufferSize(3072);
  mqttClient.setKeepAlive(30);
  mqttClient.setSocketTimeout(5);

  WiFi.mode(WIFI_STA);
  lastWiFiAttemptAtMs = millis();
  lastMqttAttemptAtMs = millis() - RECONNECT_INTERVAL_MS;
  lastSensorReadAtMs = millis() - SENSOR_INTERVAL_MS;
  beginWiFiConnection();

  Serial.println("Smart Fish Feeder ESP32 MQTT firmware started");
  Serial.print("Telemetry topic: ");
  Serial.println(mqttTelemetryTopic);
  Serial.print("Command topic: ");
  Serial.println(mqttCommandTopic);
  Serial.print("Command result topic: ");
  Serial.println(mqttCommandResultTopic);
  if (strcmp(FEEDER_MQTT_SHARED_SECRET, "local-development-mqtt-secret") == 0) {
    Serial.println("WARN using development-only MQTT HMAC secret");
  }
}

void loop() {
  const uint32_t nowMs = millis();

  maintainWiFi(nowMs);
  maintainMqtt(nowMs);
  if (mqttClient.connected()) {
    mqttClient.loop();
  }

  readTemperature(nowMs);

  if (!startupTelemetryQueued && sensorInitialized && clockIsReady()) {
    startupTelemetryQueued = enqueueTelemetry("device_started", true);
    lastHeartbeatAtMs = nowMs;
  }

  updateManualFeedButton(nowMs);
  updateFeedingCycle(nowMs);

  if (startupTelemetryQueued && nowMs - lastHeartbeatAtMs >= HEARTBEAT_INTERVAL_MS) {
    if (enqueueTelemetry("heartbeat", false)) {
      lastHeartbeatAtMs = nowMs;
    }
  }

  publishQueuedCommandResult();
  publishQueuedTelemetry();
  delay(5);
}
