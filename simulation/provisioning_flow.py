"""Deterministic no-hardware model of the ESP32 onboarding state machine."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ProvisioningPhase(StrEnum):
    FACTORY = "factory"
    ACCESS_POINT = "access_point"
    WIFI_SAVED = "wifi_saved"
    CLOUD_CLAIMED = "cloud_claimed"
    MQTT_ONLINE = "mqtt_online"
    FIRST_FEED_COMPLETED = "first_feed_completed"


@dataclass
class ProvisioningSimulator:
    device_uid: str
    phase: ProvisioningPhase = ProvisioningPhase.FACTORY
    wifi_ssid: str | None = None

    def boot(self) -> None:
        if self.phase is ProvisioningPhase.FACTORY:
            self.phase = ProvisioningPhase.ACCESS_POINT

    def save_wifi(self, ssid: str, password: str) -> None:
        if self.phase is not ProvisioningPhase.ACCESS_POINT:
            raise ValueError("WiFi can only be configured from the provisioning access point")
        if not ssid or len(ssid) > 32 or len(password) > 63:
            raise ValueError("Invalid WiFi credentials")
        self.wifi_ssid = ssid
        self.phase = ProvisioningPhase.WIFI_SAVED

    def record_cloud_claim(self) -> None:
        if self.phase is not ProvisioningPhase.WIFI_SAVED:
            raise ValueError("The device must have network credentials before cloud claim")
        self.phase = ProvisioningPhase.CLOUD_CLAIMED

    def record_mqtt_connection(self) -> None:
        if self.phase is not ProvisioningPhase.CLOUD_CLAIMED:
            raise ValueError("MQTT may connect only after the device is claimed")
        self.phase = ProvisioningPhase.MQTT_ONLINE

    def record_first_feed(self) -> None:
        if self.phase is not ProvisioningPhase.MQTT_ONLINE:
            raise ValueError("The first feed requires an online MQTT device")
        self.phase = ProvisioningPhase.FIRST_FEED_COMPLETED

    def factory_reset(self) -> None:
        self.wifi_ssid = None
        self.phase = ProvisioningPhase.ACCESS_POINT
