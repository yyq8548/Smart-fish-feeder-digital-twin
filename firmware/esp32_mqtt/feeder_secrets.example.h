#pragma once

// Copy this file to feeder_secrets.h. The destination is ignored by Git.
// Replace every placeholder before using it on physical hardware.
#define FEEDER_WIFI_SSID "your-wifi-ssid"
#define FEEDER_WIFI_PASSWORD "your-wifi-password"
#define FEEDER_ENABLE_SOFTAP_PROVISIONING 1
#define FEEDER_PROVISIONING_AP_PASSWORD "unique-device-setup-password"

#define FEEDER_MQTT_HOST "your-broker.example.com"
#define FEEDER_MQTT_PORT 8883
#define FEEDER_MQTT_USE_TLS 1
#define FEEDER_MQTT_TLS_INSECURE 0
#define FEEDER_MQTT_USERNAME "your-device-username"
#define FEEDER_MQTT_PASSWORD "your-device-password"

// Paste the PEM root CA published by the broker provider. Verified TLS fails
// closed when this value is empty. Keep the line breaks exactly as shown.
#define FEEDER_MQTT_ROOT_CA \
  "-----BEGIN CERTIFICATE-----\n" \
  "PASTE_BROKER_ROOT_CA_BASE64_HERE\n" \
  "-----END CERTIFICATE-----\n"

#define FEEDER_DEVICE_UID "feeder-001"
#define FEEDER_MQTT_SHARED_SECRET "replace-with-a-unique-high-entropy-secret"
