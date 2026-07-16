from datetime import UTC, datetime, timedelta
from pathlib import Path

from scripts.production_monitor import (
    CheckResult,
    classify_backend_logs,
    failure_fingerprint,
    load_environment,
    should_notify,
)


def test_monitor_environment_parser_does_not_evaluate_values(tmp_path: Path) -> None:
    environment_file = tmp_path / ".env.production"
    environment_file.write_text(
        "# comment\nPLAIN=value\nQUOTED='kept value'\nCOMMAND=$(never-run)\n",
        encoding="utf-8",
    )
    assert load_environment(environment_file) == {
        "PLAIN": "value",
        "QUOTED": "kept value",
        "COMMAND": "$(never-run)",
    }


def test_monitor_classifies_actionable_backend_failures() -> None:
    logs = "\n".join(
        (
            '{"status_code":503}',
            "sqlite3.OperationalError: database is locked",
            '{"message":"verification_email_delivery_failed"}',
        )
    )
    assert classify_backend_logs(logs) == {
        "http_5xx": 1,
        "database_locked": 1,
        "email_delivery_failed": 1,
    }


def test_monitor_notifications_are_transition_based_and_repeat_failures() -> None:
    now = datetime.now(UTC)
    assert should_notify({}, "healthy", now, 60) is False
    failed = [CheckResult("api", False, "HTTP 503")]
    fingerprint = failure_fingerprint(failed)
    assert should_notify({}, fingerprint, now, 60) is True
    recent = {"fingerprint": fingerprint, "last_notification_at": now.isoformat()}
    assert should_notify(recent, fingerprint, now + timedelta(minutes=5), 60) is False
    assert should_notify(recent, fingerprint, now + timedelta(minutes=61), 60) is True
    assert should_notify(recent, "healthy", now + timedelta(minutes=5), 60) is True
