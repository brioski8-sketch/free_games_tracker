# Smoke-test checklist (second device on the LAN)

Run the automated checks first from any machine:

```bash
bash scripts/smoke_test.sh http://<host-ip>:8080
```

Then verify visually from a **different device** on the LAN (phone, laptop):

- [ ] `http://<host-ip>:8080` loads the dark dashboard page
- [ ] **Glucose** widget shows a reading, trend arrow, and a 24 h chart
      (not "Not configured", not "Waiting for data")
- [ ] **RESP Balance** widget shows a dollar balance, sparkline, and entry list;
      the **Add** form is visible and adding a test entry updates the balance
      (delete the test row from the CSV afterwards if desired)
- [ ] **News Beat** widget lists headlines from your configured feeds
- [ ] **Upcoming Events** widget lists events within the configured window
- [ ] The clock in the header ticks; "refreshed HH:MM" updates about once a minute
- [ ] Leave the page open ~10 minutes: no widget greys out (stale), no
      "API unreachable" in the header
- [ ] On the host, logs are clean: `journalctl -u jarvis-lite -f`
      (or the console / `docker compose logs -f`) — no repeating tracebacks
- [ ] `curl http://<host-ip>:8080/api/status` shows `source_ok: true` for all
      four widgets

If a widget shows "Not configured": its section is missing from `config.yaml`
(see README §2). If a widget greys out: check `last_error` in `/api/status`.
