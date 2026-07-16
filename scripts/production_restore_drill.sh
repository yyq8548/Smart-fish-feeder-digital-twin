#!/bin/sh
set -eu

repository_root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$repository_root"
environment_file="${ENVIRONMENT_FILE:-.env.production}"
compose_file="docker-compose.production.yml"
backup_path="${1:-}"
if [ -z "$backup_path" ]; then
  backup_path="$(find backups -maxdepth 1 -type f -name 'fish_feeder-predeploy-*.db' -print | sort | tail -n 1)"
fi
if [ -z "$backup_path" ] || [ ! -s "$backup_path" ]; then
  echo "A non-empty SQLite backup path is required" >&2
  exit 1
fi

temporary_directory="$(mktemp -d /tmp/smart-fish-feeder-restore.XXXXXX)"
case "$temporary_directory" in
  /tmp/smart-fish-feeder-restore.*) ;;
  *) echo "Unexpected temporary path: $temporary_directory" >&2; exit 1 ;;
esac
cleanup() {
  rm -rf -- "$temporary_directory"
}
trap cleanup EXIT INT TERM

started_at="$(date +%s)"
cp -- "$backup_path" "$temporary_directory/restored.db"
backend_image="$(docker compose --env-file "$environment_file" -f "$compose_file" images -q backend | head -n 1)"
if [ -z "$backend_image" ]; then
  echo "The production backend image is not available" >&2
  exit 1
fi
docker run --rm --user 0:0 \
  -e FISH_FEEDER_DATABASE_URL=sqlite:////restore/restored.db \
  -v "$temporary_directory:/restore" \
  "$backend_image" \
  alembic upgrade head

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
report="backups/restore-drill-$stamp.json"
python3 scripts/verify_sqlite_restore.py "$temporary_directory/restored.db" --output "$report"
finished_at="$(date +%s)"
duration="$((finished_at - started_at))"
python3 - "$report" "$backup_path" "$duration" <<'PY'
import json
import sys
from pathlib import Path

report_path = Path(sys.argv[1])
payload = json.loads(report_path.read_text(encoding="utf-8"))
payload["source_backup"] = sys.argv[2]
payload["duration_seconds"] = int(sys.argv[3])
report_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
print(f"restore_report={report_path}")
print(f"restore_duration_seconds={payload['duration_seconds']}")
PY
