"""Run production checks and send transition-based alert emails."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import smtplib
import socket
import ssl
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str


def load_environment(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key.strip()] = value
    return values


def run_command(arguments: list[str], *, cwd: Path, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        arguments,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def check_http(name: str, url: str) -> CheckResult:
    try:
        request = Request(url, headers={"User-Agent": "smart-fish-feeder-monitor/1"})
        with urlopen(request, timeout=10) as response:
            status = response.status
        return CheckResult(name, 200 <= status < 300, f"HTTP {status}")
    except Exception as exc:
        return CheckResult(name, False, f"{type(exc).__name__}: {exc}")


def check_mqtt_tls(host: str, port: int) -> CheckResult:
    try:
        context = ssl.create_default_context()
        with socket.create_connection((host, port), timeout=10) as raw_socket:
            with context.wrap_socket(raw_socket, server_hostname=host) as tls_socket:
                certificate = tls_socket.getpeercert()
                expires = certificate.get("notAfter", "unknown")
        return CheckResult("mqtt_tls", True, f"verified certificate; expires {expires}")
    except Exception as exc:
        return CheckResult("mqtt_tls", False, f"{type(exc).__name__}: {exc}")


def check_resend(environment: dict[str, str]) -> CheckResult:
    try:
        host = environment["FISH_FEEDER_SMTP_HOST"]
        port = int(environment.get("FISH_FEEDER_SMTP_PORT", "587"))
        username = environment["FISH_FEEDER_SMTP_USERNAME"]
        password = environment["FISH_FEEDER_SMTP_PASSWORD"]
        with smtplib.SMTP(host, port, timeout=15) as client:
            client.ehlo()
            if environment.get("FISH_FEEDER_SMTP_STARTTLS", "true").lower() == "true":
                client.starttls(context=ssl.create_default_context())
                client.ehlo()
            client.login(username, password)
        return CheckResult("resend_smtp", True, f"authenticated to {host}:{port}")
    except Exception as exc:
        return CheckResult("resend_smtp", False, f"{type(exc).__name__}: {exc}")


def compose_command(repo_root: Path, env_file: Path, *arguments: str) -> list[str]:
    return [
        "docker",
        "compose",
        "--env-file",
        str(env_file),
        "-f",
        str(repo_root / "docker-compose.production.yml"),
        *arguments,
    ]


def check_compose_services(repo_root: Path, env_file: Path) -> CheckResult:
    process = run_command(compose_command(repo_root, env_file, "ps", "--format", "json"), cwd=repo_root)
    if process.returncode != 0:
        return CheckResult("compose_services", False, process.stderr.strip() or "docker compose ps failed")
    expected = {"backend", "dashboard", "mqtt", "mqtt-bridge", "traefik"}
    services: dict[str, dict[str, Any]] = {}
    try:
        for line in process.stdout.splitlines():
            if line.strip():
                record = json.loads(line)
                services[str(record["Service"])] = record
    except (KeyError, json.JSONDecodeError) as exc:
        return CheckResult("compose_services", False, f"invalid compose output: {exc}")
    failures: list[str] = []
    for service in sorted(expected):
        record = services.get(service)
        if record is None:
            failures.append(f"{service}=missing")
            continue
        state = str(record.get("State", "unknown"))
        health = str(record.get("Health", "unknown"))
        if state != "running" or health != "healthy":
            failures.append(f"{service}={state}/{health}")
    if failures:
        return CheckResult("compose_services", False, ", ".join(failures))
    return CheckResult("compose_services", True, "5 long-running services healthy")


def classify_backend_logs(logs: str) -> dict[str, int]:
    lowered = logs.lower()
    return {
        "http_5xx": len(re.findall(r'"status_code"\s*:\s*5\d\d', lowered)),
        "database_locked": lowered.count("database is locked") + lowered.count("database table is locked"),
        "email_delivery_failed": lowered.count("email_delivery_failed"),
    }


def check_backend_logs(repo_root: Path, env_file: Path, lookback_minutes: int) -> CheckResult:
    process = run_command(
        compose_command(
            repo_root,
            env_file,
            "logs",
            "--no-color",
            "--since",
            f"{lookback_minutes}m",
            "backend",
        ),
        cwd=repo_root,
    )
    if process.returncode != 0:
        return CheckResult("backend_logs", False, process.stderr.strip() or "backend log query failed")
    counts = classify_backend_logs(process.stdout)
    if any(counts.values()):
        return CheckResult("backend_logs", False, ", ".join(f"{key}={value}" for key, value in counts.items()))
    return CheckResult("backend_logs", True, f"no monitored errors in {lookback_minutes} minutes")


def check_customer_device_offline_alerts(repo_root: Path, env_file: Path) -> CheckResult:
    query = (
        "from app.database import SessionLocal; from app.models import Alert,Device; "
        "from sqlalchemy import func,select; "
        "db=SessionLocal(); count=db.scalar(select(func.count(Alert.id)).join(Device,Alert.device_id==Device.id)"
        ".where(Alert.category=='DEVICE_OFFLINE',Alert.resolved_at.is_(None),Device.active.is_(True),"
        "Device.owner_user_id.is_not(None))); db.close(); print(int(count or 0))"
    )
    process = run_command(
        compose_command(repo_root, env_file, "exec", "-T", "backend", "python", "-c", query),
        cwd=repo_root,
    )
    if process.returncode != 0:
        return CheckResult("customer_devices", False, process.stderr.strip() or "offline query failed")
    try:
        count = int(process.stdout.strip())
    except ValueError:
        return CheckResult("customer_devices", False, f"unexpected offline query output: {process.stdout!r}")
    return CheckResult(
        "customer_devices",
        count == 0,
        "no unresolved customer-device offline alerts" if count == 0 else f"{count} unresolved offline alerts",
    )


def failure_fingerprint(results: list[CheckResult]) -> str:
    failures = sorted(f"{result.name}:{result.detail}" for result in results if not result.ok)
    return hashlib.sha256("\n".join(failures).encode()).hexdigest() if failures else "healthy"


def send_notification(environment: dict[str, str], subject: str, body: str) -> None:
    recipient = environment.get("FISH_FEEDER_MONITOR_ALERT_EMAIL", "")
    if not recipient:
        raise RuntimeError("FISH_FEEDER_MONITOR_ALERT_EMAIL is not configured")
    message = EmailMessage()
    message["From"] = environment["FISH_FEEDER_SMTP_FROM_EMAIL"]
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)
    with smtplib.SMTP(
        environment["FISH_FEEDER_SMTP_HOST"],
        int(environment.get("FISH_FEEDER_SMTP_PORT", "587")),
        timeout=15,
    ) as client:
        client.ehlo()
        if environment.get("FISH_FEEDER_SMTP_STARTTLS", "true").lower() == "true":
            client.starttls(context=ssl.create_default_context())
            client.ehlo()
        client.login(
            environment["FISH_FEEDER_SMTP_USERNAME"],
            environment["FISH_FEEDER_SMTP_PASSWORD"],
        )
        client.send_message(message)


def load_state(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_state(path: Path, state: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)


def should_notify(state: dict[str, str], fingerprint: str, now: datetime, repeat_minutes: int) -> bool:
    if not state and fingerprint == "healthy":
        return False
    if state.get("fingerprint") != fingerprint:
        return True
    previous = state.get("last_notification_at")
    if not previous or fingerprint == "healthy":
        return False
    try:
        previous_at = datetime.fromisoformat(previous)
    except ValueError:
        return True
    return now - previous_at >= timedelta(minutes=repeat_minutes)


def collect_checks(repo_root: Path, env_file: Path, environment: dict[str, str], lookback: int) -> list[CheckResult]:
    dashboard_domain = environment["DASHBOARD_DOMAIN"]
    mqtt_domain = environment["MQTT_DOMAIN"]
    return [
        check_http("website", f"https://{dashboard_domain}/health"),
        check_http("api", f"https://{dashboard_domain}/api/health"),
        check_mqtt_tls(mqtt_domain, 8883),
        check_resend(environment),
        check_compose_services(repo_root, env_file),
        check_backend_logs(repo_root, env_file, lookback),
        check_customer_device_offline_alerts(repo_root, env_file),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path("/opt/smart-fish-feeder"))
    parser.add_argument("--env-file", type=Path)
    parser.add_argument(
        "--state-file",
        type=Path,
        default=Path("/var/lib/smart-fish-feeder-monitor/state.json"),
    )
    parser.add_argument("--lookback-minutes", type=int, default=10)
    parser.add_argument("--repeat-minutes", type=int, default=60)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    env_file = (args.env_file or repo_root / ".env.production").resolve()
    environment = load_environment(env_file)
    now = datetime.now(UTC)
    results = collect_checks(repo_root, env_file, environment, args.lookback_minutes)
    fingerprint = failure_fingerprint(results)
    state = load_state(args.state_file)
    notification_due = should_notify(state, fingerprint, now, args.repeat_minutes)
    payload = {
        "timestamp": now.isoformat(),
        "healthy": fingerprint == "healthy",
        "notification_due": notification_due,
        "checks": [asdict(result) for result in results],
    }
    print(json.dumps(payload, indent=2))
    if notification_due and not args.dry_run:
        lines = [f"{result.name}: {'OK' if result.ok else 'FAIL'} - {result.detail}" for result in results]
        recovered = fingerprint == "healthy"
        send_notification(
            environment,
            "Smart Fish Feeder recovered" if recovered else "Smart Fish Feeder production alert",
            "\n".join(lines),
        )
        state = {"fingerprint": fingerprint, "last_notification_at": now.isoformat()}
        save_state(args.state_file, state)
    elif not args.dry_run and state.get("fingerprint") != fingerprint:
        save_state(args.state_file, {"fingerprint": fingerprint, "last_notification_at": ""})
    return 0 if fingerprint == "healthy" else 1


if __name__ == "__main__":
    sys.exit(main())
