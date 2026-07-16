# Production monitoring

The VPS monitor runs every five minutes as a systemd timer. It checks the public website and API, MQTT certificate
verification, Resend SMTP authentication, all five long-running Compose services, recent backend 5xx/database-lock/
email-delivery errors, and unresolved offline alerts for active customer-owned devices.

Alerts are transition-based: a new failure fingerprint sends immediately, an unchanged failure repeats after one
hour, and recovery sends once. State is stored at `/var/lib/smart-fish-feeder-monitor/state.json` with mode `0600`.

Configure the recipient in `.env.production`:

```text
FISH_FEEDER_MONITOR_ALERT_EMAIL=operator@example.com
```

Install or update the timer from the production checkout:

```bash
cd /opt/smart-fish-feeder
sh deploy/monitoring/install.sh
```

Inspect it with:

```bash
systemctl status smart-fish-feeder-monitor.timer
systemctl status smart-fish-feeder-monitor.service
journalctl -u smart-fish-feeder-monitor.service --since today
```

Run without sending notifications or changing monitor state:

```bash
python3 scripts/production_monitor.py --dry-run
```

This monitor is deliberately host-level so it can inspect Compose service health and bounded recent logs without
mounting the Docker socket into an internet-connected application container.
