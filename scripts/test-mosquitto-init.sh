#!/bin/sh
set -eu

repository_root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"

docker run --rm \
  --entrypoint /bin/sh \
  -v "$repository_root/deploy/mosquitto/init-passwords.sh:/init/init-passwords.sh:ro" \
  -v /mosquitto/secrets \
  -e DASHBOARD_DOMAIN=feeder.test.invalid \
  -e MQTT_DOMAIN=mqtt.test.invalid \
  -e ACME_EMAIL=operator@test.invalid \
  -e DEVICE_UID=feeder-test \
  -e MQTT_BRIDGE_USERNAME=bridge \
  -e MQTT_BRIDGE_PASSWORD=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb \
  -e MQTT_DEVICE_USERNAME=feeder-test \
  -e MQTT_DEVICE_PASSWORD=dddddddddddddddddddddddddddddddddddddddd \
  -e MQTT_DEVICE_CREDENTIALS='feeder-extra:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee' \
  -e FISH_FEEDER_DEVICE_API_KEY=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa \
  -e FISH_FEEDER_CREDENTIAL_PEPPER=pppppppppppppppppppppppppppppppppppppppp \
  -e FISH_FEEDER_ADMIN_PASSWORD=mmmmmmmmmmmmmmmmmmmmmmmmmmmmmmmmmmmmmmmm \
  -e FISH_FEEDER_JWT_SECRET=jjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjj \
  -e MQTT_SHARED_SECRET=ssssssssssssssssssssssssssssssssssssssss \
  eclipse-mosquitto:2.1.2-alpine \
  -c 'sh /init/init-passwords.sh && grep -q "^feeder-test:" /mosquitto/secrets/passwords && grep -q "^feeder-extra:" /mosquitto/secrets/passwords'
