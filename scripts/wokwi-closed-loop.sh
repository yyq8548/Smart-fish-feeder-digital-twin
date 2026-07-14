#!/usr/bin/env bash
set -Eeuo pipefail

readonly root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root_dir"

for command in arduino-cli docker pnpm python3 wokwi-cli; do
  command -v "$command" >/dev/null 2>&1 || {
    echo "Required command is unavailable: $command" >&2
    exit 1
  }
done

random_hex() {
  python3 -c 'import secrets; print(secrets.token_hex(32))'
}

run_suffix="${GITHUB_RUN_ID:-local}-${GITHUB_RUN_ATTEMPT:-1}-$(random_hex | cut -c1-8)"
export DEVICE_UID="${DEVICE_UID:-feeder-e2e-${run_suffix}}"
export MQTT_SHARED_SECRET="${MQTT_SHARED_SECRET:-$(random_hex)}"
export FISH_FEEDER_DEVICE_API_KEY="${FISH_FEEDER_DEVICE_API_KEY:-$(random_hex)}"
export FISH_FEEDER_CREDENTIAL_PEPPER="${FISH_FEEDER_CREDENTIAL_PEPPER:-$(random_hex)}"
export FISH_FEEDER_JWT_SECRET="${FISH_FEEDER_JWT_SECRET:-$(random_hex)}"
export FISH_FEEDER_ADMIN_USERNAME="${FISH_FEEDER_ADMIN_USERNAME:-wokwi-operator}"
export FISH_FEEDER_ADMIN_PASSWORD="${FISH_FEEDER_ADMIN_PASSWORD:-$(random_hex)}"
export MQTT_CLIENT_ID="fish-feeder-e2e-bridge-${run_suffix}"
export E2E_ADMIN_USERNAME="$FISH_FEEDER_ADMIN_USERNAME"
export E2E_ADMIN_PASSWORD="$FISH_FEEDER_ADMIN_PASSWORD"
export E2E_DEVICE_UID="$DEVICE_UID"
export E2E_DASHBOARD_URL="${E2E_DASHBOARD_URL:-http://127.0.0.1:8080}"

readonly project_name="${COMPOSE_PROJECT_NAME:-fish-feeder-wokwi-e2e-${run_suffix}}"
readonly build_dir="$root_dir/build/wokwi"
readonly firmware_header="$root_dir/firmware/esp32_mqtt/feeder_secrets.h"
readonly wokwi_log="$build_dir/closed-loop-wokwi.log"
readonly serial_log="$build_dir/closed-loop-serial.log"
readonly -a compose=(docker compose --project-name "$project_name" -f docker-compose.yml -f docker-compose.wokwi-e2e.yml)
wokwi_pid=""

cleanup() {
  local exit_code=$?
  trap - EXIT
  set +e
  if [[ -n "$wokwi_pid" ]] && kill -0 "$wokwi_pid" 2>/dev/null; then
    kill "$wokwi_pid" 2>/dev/null
    wait "$wokwi_pid" 2>/dev/null
  fi
  if (( exit_code != 0 )); then
    echo "Closed-loop test failed; collecting Wokwi and Compose diagnostics." >&2
    [[ -f "$wokwi_log" ]] && tail -n 200 "$wokwi_log" >&2
    "${compose[@]}" ps --all >&2
    "${compose[@]}" logs --no-color --timestamps >&2
  fi
  "${compose[@]}" down --volumes --remove-orphans --timeout 10 >/dev/null 2>&1
  rm -f "$firmware_header"
  exit "$exit_code"
}
trap cleanup EXIT

mkdir -p "$build_dir"
python3 scripts/generate_wokwi_e2e_header.py

echo "Compiling certificate-verified MQTT firmware for $DEVICE_UID"
arduino-cli compile \
  --fqbn esp32:esp32:esp32 \
  --build-path "$build_dir" \
  firmware/esp32_mqtt

echo "Starting the complete application stack with the verified-TLS MQTT bridge"
"${compose[@]}" up --build --detach --wait --wait-timeout 180

echo "Starting the Wokwi ESP32 and closed-loop GPIO scenario"
wokwi-cli simulation/esp32-mqtt \
  --scenario verify_closed_loop.yaml \
  --timeout 90000 \
  --serial-log-file "$serial_log" \
  >"$wokwi_log" 2>&1 &
wokwi_pid=$!

echo "Submitting FEED_NOW from the real dashboard in Chromium"
pnpm --dir dashboard test:e2e

echo "Waiting for Wokwi GPIO and firmware lifecycle assertions"
wait "$wokwi_pid"
wokwi_pid=""
grep -q "Scenario completed successfully" "$wokwi_log"
grep -q "started: FEED_NOW" "$serial_log"
grep -q "completed: feeding_and_cleaning_completed" "$serial_log"

bridge_log="$("${compose[@]}" logs --no-color mqtt-bridge)"
grep -q "Accepted signed command result for $DEVICE_UID" <<<"$bridge_log"

echo "Closed loop passed: dashboard PENDING -> MQTT -> ESP32 GPIO -> signed result -> dashboard COMPLETED."
