#!/bin/sh
set -eu

repository_root="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
install -d -m 700 /var/lib/smart-fish-feeder-monitor
install -m 644 "$repository_root/deploy/monitoring/smart-fish-feeder-monitor.service" /etc/systemd/system/
install -m 644 "$repository_root/deploy/monitoring/smart-fish-feeder-monitor.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now smart-fish-feeder-monitor.timer
systemctl start smart-fish-feeder-monitor.service
