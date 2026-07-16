import pytest

from simulation.provisioning_flow import ProvisioningPhase, ProvisioningSimulator


def test_no_hardware_provisioning_reaches_first_feed_and_can_factory_reset() -> None:
    device = ProvisioningSimulator("feeder-simulated")
    device.boot()
    assert device.phase is ProvisioningPhase.ACCESS_POINT
    device.save_wifi("Home Reef", "correct-horse-battery-staple")
    device.record_cloud_claim()
    device.record_mqtt_connection()
    device.record_first_feed()
    assert device.phase is ProvisioningPhase.FIRST_FEED_COMPLETED

    device.factory_reset()
    assert device.phase is ProvisioningPhase.ACCESS_POINT
    assert device.wifi_ssid is None


def test_no_hardware_provisioning_rejects_out_of_order_and_invalid_transitions() -> None:
    device = ProvisioningSimulator("feeder-simulated")
    with pytest.raises(ValueError, match="provisioning access point"):
        device.save_wifi("Home Reef", "password")
    device.boot()
    with pytest.raises(ValueError, match="Invalid WiFi"):
        device.save_wifi("", "password")
    device.save_wifi("Home Reef", "")
    with pytest.raises(ValueError, match="claimed"):
        device.record_mqtt_connection()
