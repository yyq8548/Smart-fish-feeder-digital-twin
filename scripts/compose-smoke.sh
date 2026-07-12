#!/usr/bin/env bash
set -Eeuo pipefail

default_project="fish-feeder-smoke"
if [[ -n "${GITHUB_RUN_ID:-}" ]]; then
  default_project+="-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT:-1}"
fi

readonly project_name="${COMPOSE_PROJECT_NAME:-$default_project}"
readonly wait_timeout="${COMPOSE_SMOKE_TIMEOUT:-180}"
readonly api_url="${COMPOSE_SMOKE_API_URL:-http://127.0.0.1:8000}"
readonly dashboard_url="${COMPOSE_SMOKE_DASHBOARD_URL:-http://127.0.0.1:8080}"
readonly smoke_api_key="${FISH_FEEDER_DEVICE_API_KEY:-compose-smoke-api-key}"
readonly smoke_admin="${FISH_FEEDER_ADMIN_USERNAME:-compose-admin}"
readonly smoke_password="${FISH_FEEDER_ADMIN_PASSWORD:-compose-admin-password}"
readonly mqtt_shared_secret="${MQTT_SHARED_SECRET:-compose-smoke-mqtt-secret}"
readonly mqtt_device="feeder-001"
readonly mqtt_topic="fish-feeder/${mqtt_device}/telemetry"
readonly command_topic="fish-feeder/${mqtt_device}/commands"
readonly -a curl_timeout=(--connect-timeout 5 --max-time 20)

export FISH_FEEDER_DEVICE_API_KEY="$smoke_api_key"
export FISH_FEEDER_ADMIN_USERNAME="$smoke_admin"
export FISH_FEEDER_ADMIN_PASSWORD="$smoke_password"
export FISH_FEEDER_CREDENTIAL_PEPPER="compose-smoke-credential-pepper"
export FISH_FEEDER_JWT_SECRET="compose-smoke-jwt-secret-at-least-32-characters"
export FISH_FEEDER_OFFLINE_AFTER_SECONDS="120"
export MQTT_SHARED_SECRET="$mqtt_shared_secret"
export DEVICE_UID="$mqtt_device"
export DEVICE_CREDENTIALS_JSON=""
export MQTT_SHARED_SECRETS_JSON=""

compose=(docker compose --project-name "$project_name")
command_file=""

cleanup() {
  local exit_code=$?
  trap - EXIT
  set +e
  if (( exit_code != 0 )); then
    echo "Compose smoke test failed; collecting service state and logs." >&2
    "${compose[@]}" ps --all >&2
    "${compose[@]}" logs --no-color --timestamps >&2
  fi
  [[ -n "$command_file" ]] && rm -f "$command_file"
  "${compose[@]}" down --volumes --remove-orphans --timeout 10 >/dev/null 2>&1
  local teardown_code=$?
  if (( exit_code == 0 && teardown_code != 0 )); then
    echo "Compose smoke assertions passed, but stack teardown failed." >&2
    exit_code=$teardown_code
  fi
  exit "$exit_code"
}
trap cleanup EXIT

fail() {
  echo "Smoke test assertion failed: $*" >&2
  return 1
}

get_json() {
  curl "${curl_timeout[@]}" --fail-with-body --silent --show-error --retry 5 --retry-connrefused --retry-delay 1 "$1"
}

timestamp="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

echo "Building and starting Compose project: $project_name"
"${compose[@]}" up --build --detach --wait --wait-timeout "$wait_timeout"

echo "Verifying backend health and database connectivity"
backend_health="$(get_json "$api_url/health")"
printf '%s' "$backend_health" | python3 -c 'import json,sys; assert json.load(sys.stdin) == {"status":"healthy","database":"connected"}'

echo "Verifying operator login and per-device provisioning"
token_response="$(curl "${curl_timeout[@]}" --fail-with-body --silent --show-error --request POST "$api_url/auth/token" \
  --header 'Content-Type: application/x-www-form-urlencoded' \
  --data-urlencode "username=$smoke_admin" --data-urlencode "password=$smoke_password")"
access_token="$(printf '%s' "$token_response" | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')"
provisioned="$(curl "${curl_timeout[@]}" --fail-with-body --silent --show-error --request POST "$api_url/devices" \
  --header 'Content-Type: application/json' --header "Authorization: Bearer $access_token" \
  --data '{"device_uid":"compose-smoke-api","name":"Compose smoke device"}')"
provisioned_key="$(printf '%s' "$provisioned" | python3 -c 'import json,sys; print(json.load(sys.stdin)["api_key"])')"

echo "Verifying invalid device credentials are rejected"
invalid_payload="$(printf '{"device_uid":"compose-smoke-api","idempotency_key":"invalid-auth","sequence_number":1,"recorded_at":"%s","temperature_c":5.0,"cooling_on":false,"pump_state":"IDLE","sensor_status":"OK","event_type":"smoke"}' "$timestamp")"
unauthorized_status="$(curl "${curl_timeout[@]}" --silent --show-error --output /dev/null --write-out '%{http_code}' \
  --request POST "$api_url/telemetry" --header 'Content-Type: application/json' \
  --header 'X-Device-ID: compose-smoke-api' --header 'X-Device-Key: invalid-compose-smoke-key' \
  --data "$invalid_payload")"
[[ "$unauthorized_status" == "401" ]] || fail "expected HTTP 401 for an invalid key, received $unauthorized_status"

echo "Posting telemetry with the provisioned per-device key"
api_payload="$(printf '{"device_uid":"compose-smoke-api","idempotency_key":"authenticated-api-smoke","sequence_number":1,"recorded_at":"%s","temperature_c":5.0,"cooling_on":false,"pump_state":"IDLE","sensor_status":"OK","event_type":"api-smoke"}' "$timestamp")"
api_telemetry="$(curl "${curl_timeout[@]}" --fail-with-body --silent --show-error --request POST "$api_url/telemetry" \
  --header 'Content-Type: application/json' --header 'X-Device-ID: compose-smoke-api' \
  --header "X-Device-Key: $provisioned_key" --data "$api_payload")"
printf '%s' "$api_telemetry" | python3 -c 'import json,sys; p=json.load(sys.stdin); assert p["temperature_c"] == 5.0 and p["sequence_number"] == 1'

echo "Publishing MQTT telemetry through the bridge"
export SMOKE_TIMESTAMP="$timestamp"
mqtt_payload="$(python3 -c '
import hashlib
import hmac
import json
import os
from decimal import Decimal, ROUND_HALF_UP

payload = {
    "device_uid": "feeder-001",
    "idempotency_key": "mqtt-bridge-smoke",
    "sequence_number": 1,
    "recorded_at": os.environ["SMOKE_TIMESTAMP"],
    "temperature_c": 6.0,
    "cooling_on": True,
    "pump_state": "IDLE",
    "sensor_status": "OK",
    "event_type": "mqtt-smoke",
}

def field(label, value):
    encoded = value.encode("utf-8")
    return label.encode("ascii") + b":" + str(len(encoded)).encode("ascii") + b":" + encoded

temperature_mdeg = str(int((Decimal(str(payload["temperature_c"])) * 1000).quantize(Decimal("1"), rounding=ROUND_HALF_UP)))
values = (
    ("device_uid", str(payload["device_uid"])),
    ("sequence_number", str(payload["sequence_number"])),
    ("idempotency_key", str(payload["idempotency_key"])),
    ("recorded_at", str(payload["recorded_at"])),
    ("temperature_mdeg", temperature_mdeg),
    ("cooling_on", "1" if payload["cooling_on"] else "0"),
    ("pump_state", str(payload["pump_state"])),
    ("sensor_status", str(payload["sensor_status"])),
    ("event_type", "null" if payload.get("event_type") is None else str(payload["event_type"])),
    ("schedule_id", "null" if payload.get("schedule_id") is None else str(payload["schedule_id"])),
)
canonical = b"\n".join([b"fish-feeder-telemetry-v1", *(field(label, value) for label, value in values)])
payload["signature"] = hmac.new(os.environ["MQTT_SHARED_SECRET"].encode(), canonical, hashlib.sha256).hexdigest()
print(json.dumps(payload, separators=(",", ":")))
')"
"${compose[@]}" exec -T mqtt mosquitto_pub --host 127.0.0.1 --topic "$mqtt_topic" --qos 1 --retain --message "$mqtt_payload"

echo "Waiting for MQTT telemetry to reach the API"
mqtt_status=""
mqtt_delivered=false
for _ in {1..30}; do
  mqtt_status="$(curl "${curl_timeout[@]}" --fail-with-body --silent --show-error --retry 5 \
    --retry-connrefused --retry-delay 1 --header "Authorization: Bearer $access_token" \
    "$api_url/device-status?device_uid=$mqtt_device")"
  if printf '%s' "$mqtt_status" | python3 -c 'import json,sys; p=json.load(sys.stdin); assert p["online"] and p["temperature_c"] == 6.0 and p["last_sequence_number"] == 1' 2>/dev/null; then
    mqtt_delivered=true
    break
  fi
  sleep 1
done
[[ "$mqtt_delivered" == "true" ]] || fail "MQTT telemetry was not visible through the API; last response: $mqtt_status"

echo "Verifying signed backend-to-device command delivery and completion"
command_file="$(mktemp)"
"${compose[@]}" exec -T mqtt mosquitto_pub \
  --host 127.0.0.1 --topic "$command_topic" --qos 1 --retain --message '{"smoke_probe":true}'
"${compose[@]}" exec -T mqtt mosquitto_sub \
  --host 127.0.0.1 --topic "$command_topic" --qos 1 -C 2 -W 30 \
  >"$command_file" &
subscriber_pid=$!
subscriber_ready=false
for _ in {1..50}; do
  if [[ -s "$command_file" ]]; then
    subscriber_ready=true
    break
  fi
  kill -0 "$subscriber_pid" 2>/dev/null || break
  sleep 0.1
done
[[ "$subscriber_ready" == "true" ]] || fail "MQTT command subscriber did not become ready"
created_command="$(curl "${curl_timeout[@]}" --fail-with-body --silent --show-error --request POST \
  "$api_url/devices/feeder-001/commands" --header 'Content-Type: application/json' \
  --header "Authorization: Bearer $access_token" \
  --data '{"idempotency_key":"compose-feed-now","command_type":"FEED_NOW","payload":{}}')"
command_id="$(printf '%s' "$created_command" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')"
wait "$subscriber_pid" || fail "bridge did not publish a claimed command"
command_message="$(tail -n 1 "$command_file")"
"${compose[@]}" exec -T mqtt mosquitto_pub \
  --host 127.0.0.1 --topic "$command_topic" --qos 1 --retain --null-message
export EXPECTED_COMMAND_ID="$command_id" COMMAND_MESSAGE="$command_message"
python3 -c '
import hashlib
import hmac
import json
import os

message = json.loads(os.environ["COMMAND_MESSAGE"])
assert str(message["command_id"]) == os.environ["EXPECTED_COMMAND_ID"], message
canonical = f"{message['"'"'command_id'"'"']}|{message['"'"'command_type'"'"']}|{message['"'"'payload_json'"'"']}"
expires_at = message.get("expires_at")
assert isinstance(expires_at, str) and expires_at.endswith("Z"), message
canonical += f"|{expires_at}"
expected = hmac.new(os.environ["MQTT_SHARED_SECRET"].encode(), canonical.encode(), hashlib.sha256).hexdigest()
assert hmac.compare_digest(message["signature"], expected), message
'
export COMMAND_RESULT="smoke-complete"
command_result="$(python3 -c '
import hashlib
import hmac
import json
import os

command_id = int(os.environ["EXPECTED_COMMAND_ID"])
status = "COMPLETED"
result = os.environ["COMMAND_RESULT"]
signature = hmac.new(
    os.environ["MQTT_SHARED_SECRET"].encode(),
    f"{command_id}|{status}|{result}".encode(),
    hashlib.sha256,
).hexdigest()
print(json.dumps({"command_id": command_id, "status": status, "result": result, "signature": signature}, separators=(",", ":")))
')"
"${compose[@]}" exec -T mqtt mosquitto_pub --host 127.0.0.1 \
  --topic 'fish-feeder/feeder-001/command-results' --qos 1 --message "$command_result"
command_completed=false
for _ in {1..20}; do
  command_list="$(curl "${curl_timeout[@]}" --fail-with-body --silent --show-error \
    "$api_url/devices/feeder-001/commands" --header "Authorization: Bearer $access_token")"
  if printf '%s' "$command_list" | python3 -c 'import json,sys; p=json.load(sys.stdin); assert p[0]["status"] == "COMPLETED" and p[0]["result"] == "smoke-complete"' 2>/dev/null; then
    command_completed=true
    break
  fi
  sleep 1
done
[[ "$command_completed" == "true" ]] || fail "signed command result did not complete the backend command"

echo "Verifying dashboard and its backend proxy"
dashboard_health="$(curl "${curl_timeout[@]}" --fail-with-body --silent --show-error "$dashboard_url/health")"
[[ "$dashboard_health" == *"healthy"* ]] || fail "dashboard health endpoint did not report healthy"
dashboard_html="$(curl "${curl_timeout[@]}" --fail-with-body --silent --show-error "$dashboard_url/")"
[[ "$dashboard_html" == *"Smart Fish Feeder Operations"* ]] || fail "dashboard HTML did not contain the expected title"
dashboard_chart="$(curl "${curl_timeout[@]}" --fail-with-body --silent --show-error "$dashboard_url/chart.js")"
[[ "$dashboard_chart" == *"TelemetryLineChart"* ]] || fail "dashboard chart module was not served"
proxy_health="$(get_json "$dashboard_url/api/health")"
printf '%s' "$proxy_health" | python3 -c 'import json,sys; assert json.load(sys.stdin) == {"status":"healthy","database":"connected"}'

echo "Compose smoke test passed: migrations, login, per-device auth, MQTT, API, and dashboard are operational."
