import json
from pathlib import Path

from scripts.manufacture_device import write_bundle


def test_manufacturing_bundle_separates_claim_qr_from_long_term_secrets(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "feeder-100"
    files = write_bundle(
        bundle_dir,
        {
            "device_uid": "feeder-100",
            "api_key": "private-device-api-key",
            "proof_of_possession": "ONE-TIME-CLAIM-CODE",
            "claim_url": "https://feeder.example.test/?device_uid=feeder-100&claim_code=ONE-TIME-CLAIM-CODE",
            "claim_expires_at": "2026-10-01T00:00:00Z",
            "credential_version": 1,
        },
        mqtt_host="mqtt.example.test",
        mqtt_port=8883,
        mqtt_root_ca="-----BEGIN CERTIFICATE-----\nTEST\n-----END CERTIFICATE-----\n",
    )

    label = Path(files["label"]).read_text(encoding="utf-8")
    assert "feeder-100" in label
    assert "ONE-TIME-CLAIM-CODE" in label
    assert "private-device-api-key" not in label
    assert "<svg" in label
    assert Path(files["qr"]).read_text(encoding="utf-8").startswith("<?xml")

    stored_secrets = json.loads(Path(files["secrets"]).read_text(encoding="utf-8"))
    assert stored_secrets["device_api_key"] == "private-device-api-key"
    assert stored_secrets["mqtt_username"] == "feeder-100"
    assert len(stored_secrets["mqtt_password"]) >= 32
    assert len(stored_secrets["mqtt_shared_secret"]) == 64
    firmware_header = Path(files["firmware_header"]).read_text(encoding="utf-8")
    assert "FEEDER_ENABLE_SOFTAP_PROVISIONING 1" in firmware_header
    assert "-----BEGIN CERTIFICATE-----\\n" in firmware_header
