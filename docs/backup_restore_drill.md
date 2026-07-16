# Production backup restore drill

The restore drill never opens or writes the production database. It copies a SQLite backup into a verified `/tmp`
directory, upgrades that copy to the current Alembic head inside the production backend image, and validates:

- SQLite `integrity_check`
- foreign-key consistency
- Alembic version
- presence and row counts of users, devices, schedules, commands, telemetry, alerts, and executions
- a transactional write probe that is rolled back

Run on the VPS:

```bash
cd /opt/smart-fish-feeder
sh scripts/production_restore_drill.sh backups/fish_feeder-predeploy-YYYYMMDDTHHMMSSZ.db
```

Omit the path to use the newest matching pre-deployment backup. The script deletes only its validated
`/tmp/smart-fish-feeder-restore.*` directory and preserves a JSON evidence report under `backups/` with the source,
counts, schema version, and measured recovery time.

Success proves the database artifact is readable and upgradeable on the current software. It does not replace a
full disaster-recovery exercise for MQTT persistence, Traefik ACME state, or the root-owned production environment
file; those remain separate encrypted backup assets.
