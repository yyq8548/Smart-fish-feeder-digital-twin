"""Provision a feeder and create a printable one-time claim bundle."""

from __future__ import annotations

import argparse
import html
import json
import os
import secrets
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import qrcode
import qrcode.image.svg


def request_json(
    url: str,
    *,
    method: str = "GET",
    token: str | None = None,
    json_body: dict[str, object] | None = None,
    form_body: dict[str, str] | None = None,
) -> dict[str, Any]:
    headers: dict[str, str] = {}
    body = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if json_body is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(json_body).encode()
    elif form_body is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        body = urllib.parse.urlencode(form_body).encode()
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode())


def write_bundle(
    output_dir: Path,
    provisioned: dict[str, Any],
    *,
    mqtt_host: str,
    mqtt_port: int,
    mqtt_root_ca: str,
) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=False)
    device_uid = str(provisioned["device_uid"])
    claim_url = str(provisioned["claim_url"])
    proof = str(provisioned["proof_of_possession"])
    mqtt_password = secrets.token_urlsafe(32)
    mqtt_shared_secret = secrets.token_hex(32)
    access_point_password = secrets.token_urlsafe(12)
    if "-----BEGIN CERTIFICATE-----" not in mqtt_root_ca or "-----END CERTIFICATE-----" not in mqtt_root_ca:
        raise ValueError("mqtt_root_ca must contain a PEM certificate")
    root_ca_literal = " \\\n".join(
        f'"{line.replace(chr(34), chr(92) + chr(34))}\\n"' for line in mqtt_root_ca.strip().splitlines()
    )

    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=4)
    qr.add_data(claim_url)
    qr.make(fit=True)
    qr_path = output_dir / "claim-qr.svg"
    qr.make_image(image_factory=qrcode.image.svg.SvgPathFillImage).save(qr_path)

    secrets_payload = {
        "device_uid": device_uid,
        "device_api_key": provisioned["api_key"],
        "mqtt_username": device_uid,
        "mqtt_password": mqtt_password,
        "mqtt_shared_secret": mqtt_shared_secret,
        "provisioning_access_point_password": access_point_password,
        "proof_of_possession": proof,
        "claim_url": claim_url,
        "claim_expires_at": provisioned["claim_expires_at"],
        "credential_version": provisioned["credential_version"],
    }
    secrets_path = output_dir / "device-secrets.json"
    secrets_path.write_text(json.dumps(secrets_payload, indent=2) + "\n", encoding="utf-8")
    os.chmod(secrets_path, 0o600)

    header = "\n".join(
        (
            "#pragma once",
            f'#define FEEDER_DEVICE_UID "{device_uid}"',
            '#define FEEDER_WIFI_SSID ""',
            '#define FEEDER_WIFI_PASSWORD ""',
            f'#define FEEDER_MQTT_HOST "{mqtt_host}"',
            f"#define FEEDER_MQTT_PORT {mqtt_port}",
            "#define FEEDER_MQTT_USE_TLS 1",
            "#define FEEDER_MQTT_TLS_INSECURE 0",
            f'#define FEEDER_MQTT_USERNAME "{device_uid}"',
            f'#define FEEDER_MQTT_PASSWORD "{mqtt_password}"',
            f'#define FEEDER_MQTT_SHARED_SECRET "{mqtt_shared_secret}"',
            f"#define FEEDER_MQTT_ROOT_CA \\\n{root_ca_literal}",
            "#define FEEDER_ENABLE_SOFTAP_PROVISIONING 1",
            f'#define FEEDER_PROVISIONING_AP_PASSWORD "{access_point_password}"',
            "",
        )
    )
    header_path = output_dir / "feeder_secrets.h"
    header_path.write_text(header, encoding="utf-8")
    os.chmod(header_path, 0o600)

    qr_svg = qr_path.read_text(encoding="utf-8")
    if qr_svg.startswith("<?xml"):
        qr_svg = qr_svg.split("?>", 1)[1]
    label = f"""<!doctype html>
<html lang="en"><meta charset="utf-8"><title>{html.escape(device_uid)} setup label</title>
<style>body{{font:16px system-ui;max-width:520px;margin:40px auto}}svg{{width:280px;height:280px}}
code{{overflow-wrap:anywhere}}.secret{{font:700 20px monospace}}</style>
<h1>Smart Fish Feeder</h1><p>Device: <strong>{html.escape(device_uid)}</strong></p>
{qr_svg}
<p>Scan to claim this feeder. Manual proof-of-possession:</p>
<p class="secret">{html.escape(proof)}</p>
<p>Claim before: <code>{html.escape(str(provisioned['claim_expires_at']))}</code></p>
</html>"""
    label_path = output_dir / "device-label.html"
    label_path.write_text(label, encoding="utf-8")

    deployment = {
        "device_credentials_entry": {device_uid: provisioned["api_key"]},
        "mqtt_shared_secrets_entry": {device_uid: mqtt_shared_secret},
        "mqtt_device_credentials_entry": f"{device_uid}:{mqtt_password}",
    }
    deployment_path = output_dir / "server-registration.json"
    deployment_path.write_text(json.dumps(deployment, indent=2) + "\n", encoding="utf-8")
    os.chmod(deployment_path, 0o600)
    return {
        "label": str(label_path),
        "qr": str(qr_path),
        "secrets": str(secrets_path),
        "firmware_header": str(header_path),
        "server_registration": str(deployment_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--admin-username", required=True)
    parser.add_argument("--admin-password-env", default="FISH_FEEDER_ADMIN_PASSWORD")
    parser.add_argument("--device-uid", required=True)
    parser.add_argument("--name", default="Smart Fish Feeder")
    parser.add_argument("--mqtt-host", required=True)
    parser.add_argument("--mqtt-port", type=int, default=8883)
    parser.add_argument("--mqtt-root-ca-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    password = os.environ.get(args.admin_password_env)
    if not password:
        raise SystemExit(f"Set {args.admin_password_env}; administrator passwords are never accepted as CLI arguments")
    api_url = args.api_url.rstrip("/")
    login = request_json(
        f"{api_url}/auth/token",
        method="POST",
        form_body={"username": args.admin_username, "password": password},
    )
    provisioned = request_json(
        f"{api_url}/devices",
        method="POST",
        token=str(login["access_token"]),
        json_body={"device_uid": args.device_uid, "name": args.name},
    )
    files = write_bundle(
        args.output_dir,
        provisioned,
        mqtt_host=args.mqtt_host,
        mqtt_port=args.mqtt_port,
        mqtt_root_ca=args.mqtt_root_ca_file.read_text(encoding="utf-8"),
    )
    print(json.dumps({"device_uid": args.device_uid, "files": files}, indent=2))


if __name__ == "__main__":
    main()
