# Smart Fish Feeder Digital Twin v4 architecture

```text
ESP32/Wokwi --MQTT--> Mosquitto --> bridge --HTTP--> FastAPI
Mock client ----------------------------------------HTTP--> |
                                                         |
                    +------------------------------------+------------------+
                    |                                    |                  |
              identity/security                    domain services    reliability worker
                    |                                    |                  |
          users + device credentials       schedules/executions/alerts/commands
                    +------------------------------------+------------------+
                                                         |
                                                SQLAlchemy + Alembic
                                                         |
                                                  persistent SQLite
                                                         |
                                               Nginx dashboard / API
```

## Design choices

- A modular monolith keeps the portfolio system reproducible while still separating configuration, schemas, persistence, security, rate limiting, logging, and reliability logic.
- MQTT decouples device connectivity from API/database concerns; the bridge translates device messages into the authenticated ingestion contract.
- Database uniqueness constraints and idempotency keys protect HTTP retry behavior.
- Sequence numbers and event-time validation make ordering failures explicit.
- Durable alerts and feeding executions allow acknowledgement, auditing, and missed-operation detection.
- Alembic owns schema evolution; Docker runs migrations before serving traffic.
