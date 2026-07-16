# No-hardware device acceptance drill

This drill proves the cloud ownership and command lifecycle without claiming that Wi-Fi radio, TLS on a physical
ESP32, or GPIO loads were tested.

Run:

```bash
pytest backend/tests/test_virtual_onboarding_drill.py -q --no-cov
```

The drill creates only temporary test data and artifacts. It:

1. Provisions a virtual factory device.
2. Generates its one-time claim QR, printable label, private manufacturing secrets, firmware header, and server
   registration file.
3. Registers and verifies two new customers.
4. Parses the QR claim URL and claims the device.
5. Rejects replay of the consumed proof-of-possession.
6. Accepts a simulated heartbeat and marks the device online.
7. Sends `FEED_NOW`, lets the simulated device claim it, returns a terminal completion, and verifies history.
8. Unpairs and reclaims the device with a new one-time proof.
9. Transfers ownership to the second customer and removes the first customer's access.
10. Revokes the device credential, rejects the revoked key, reactivates the device, and accepts the replacement key.

The test's temporary directory is deleted by pytest. No production device, customer, broker credential, or database
row is created.
