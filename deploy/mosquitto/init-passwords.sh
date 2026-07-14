#!/bin/sh
set -eu

umask 077

: "${DASHBOARD_DOMAIN:?DASHBOARD_DOMAIN is required}"
: "${MQTT_DOMAIN:?MQTT_DOMAIN is required}"
: "${ACME_EMAIL:?ACME_EMAIL is required}"
: "${DEVICE_UID:?DEVICE_UID is required}"
: "${MQTT_BRIDGE_USERNAME:?MQTT_BRIDGE_USERNAME is required}"
: "${MQTT_BRIDGE_PASSWORD:?MQTT_BRIDGE_PASSWORD is required}"
: "${MQTT_DEVICE_USERNAME:?MQTT_DEVICE_USERNAME is required}"
: "${MQTT_DEVICE_PASSWORD:?MQTT_DEVICE_PASSWORD is required}"
: "${FISH_FEEDER_DEVICE_API_KEY:?FISH_FEEDER_DEVICE_API_KEY is required}"
: "${FISH_FEEDER_CREDENTIAL_PEPPER:?FISH_FEEDER_CREDENTIAL_PEPPER is required}"
: "${FISH_FEEDER_ADMIN_PASSWORD:?FISH_FEEDER_ADMIN_PASSWORD is required}"
: "${FISH_FEEDER_JWT_SECRET:?FISH_FEEDER_JWT_SECRET is required}"
: "${MQTT_SHARED_SECRET:?MQTT_SHARED_SECRET is required}"

validate_secret() {
  secret_name="$1"
  secret_value="$2"
  minimum_length="$3"
  if [ "${#secret_value}" -lt "$minimum_length" ]; then
    echo "${secret_name} must contain at least ${minimum_length} characters" >&2
    exit 1
  fi
  case "$secret_value" in
    *replace-with*|*local-development*|*example*|*changeme*|*change-me*)
      echo "Refusing placeholder value for ${secret_name}" >&2
      exit 1
      ;;
  esac
}

validate_hostname() {
  hostname_name="$1"
  hostname_value="$2"
  case "$hostname_value" in
    *://*|*/*|*:*|*" "*|example.com|*.example.com|localhost|*localhost)
      echo "Refusing placeholder or invalid hostname for ${hostname_name}" >&2
      exit 1
      ;;
    *[!A-Za-z0-9.-]*|.*|*.|-*|*-.)
      echo "${hostname_name} is not a valid DNS hostname" >&2
      exit 1
      ;;
    *.*)
      ;;
    *)
      echo "${hostname_name} must be a fully qualified DNS hostname" >&2
      exit 1
      ;;
  esac
}

validate_email() {
  case "$1" in
    *@*.*)
      ;;
    *)
      echo "ACME_EMAIL must be a valid email address" >&2
      exit 1
      ;;
  esac
  case "$1" in
    *@example.com)
      echo "Refusing placeholder ACME_EMAIL" >&2
      exit 1
      ;;
  esac
}

ensure_unique() {
  while [ "$#" -gt 1 ]; do
    first="$1"
    shift
    for other in "$@"; do
      if [ "$first" = "$other" ]; then
        echo "Production secrets must not be reused" >&2
        exit 1
      fi
    done
  done
}

if [ "$MQTT_BRIDGE_USERNAME" != "bridge" ]; then
  echo "MQTT_BRIDGE_USERNAME must be 'bridge' to match deploy/mosquitto/acl" >&2
  exit 1
fi

if [ "$MQTT_DEVICE_USERNAME" != "$DEVICE_UID" ]; then
  echo "MQTT_DEVICE_USERNAME must exactly match DEVICE_UID" >&2
  exit 1
fi

if [ "$MQTT_DEVICE_USERNAME" = "$MQTT_BRIDGE_USERNAME" ]; then
  echo "The device UID must not use the reserved bridge broker username" >&2
  exit 1
fi

validate_hostname "DASHBOARD_DOMAIN" "$DASHBOARD_DOMAIN"
validate_hostname "MQTT_DOMAIN" "$MQTT_DOMAIN"
validate_email "$ACME_EMAIL"

case "$MQTT_DEVICE_USERNAME" in
  *[!A-Za-z0-9._-]*)
    echo "DEVICE_UID may contain only letters, digits, dot, underscore, and hyphen" >&2
    exit 1
    ;;
esac

validate_secret "MQTT_BRIDGE_PASSWORD" "$MQTT_BRIDGE_PASSWORD" 24
validate_secret "MQTT_DEVICE_PASSWORD" "$MQTT_DEVICE_PASSWORD" 24
validate_secret "FISH_FEEDER_DEVICE_API_KEY" "$FISH_FEEDER_DEVICE_API_KEY" 32
validate_secret "FISH_FEEDER_CREDENTIAL_PEPPER" "$FISH_FEEDER_CREDENTIAL_PEPPER" 32
validate_secret "FISH_FEEDER_ADMIN_PASSWORD" "$FISH_FEEDER_ADMIN_PASSWORD" 32
validate_secret "FISH_FEEDER_JWT_SECRET" "$FISH_FEEDER_JWT_SECRET" 32
validate_secret "MQTT_SHARED_SECRET" "$MQTT_SHARED_SECRET" 32

ensure_unique \
  "$MQTT_BRIDGE_PASSWORD" \
  "$MQTT_DEVICE_PASSWORD" \
  "$FISH_FEEDER_DEVICE_API_KEY" \
  "$FISH_FEEDER_CREDENTIAL_PEPPER" \
  "$FISH_FEEDER_ADMIN_PASSWORD" \
  "$FISH_FEEDER_JWT_SECRET" \
  "$MQTT_SHARED_SECRET"

temporary_directory="$(mktemp -d /mosquitto/secrets/passwords.XXXXXX)"
temporary_file="$temporary_directory/passwords"
trap 'rm -f "$temporary_file"; rmdir "$temporary_directory" 2>/dev/null || true' EXIT INT TERM

mosquitto_passwd -b -c "$temporary_file" "$MQTT_BRIDGE_USERNAME" "$MQTT_BRIDGE_PASSWORD"
mosquitto_passwd -b "$temporary_file" "$MQTT_DEVICE_USERNAME" "$MQTT_DEVICE_PASSWORD"
chmod 600 "$temporary_file"
chown 1883:1883 "$temporary_file"
mv -f "$temporary_file" /mosquitto/secrets/passwords
rmdir "$temporary_directory"
trap - EXIT INT TERM

echo "Mosquitto password file initialized for bridge and ${MQTT_DEVICE_USERNAME}."
