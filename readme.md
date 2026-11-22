## Summary

Monitors the radon mitigation system with an Adafruit ESP32-S3 TFT Feather. One
pressure sensor (LPS35HW) is inside the vent pipe and one (BMP280) is outside it;
the difference between them (the delta) should stay below a minimum. A LC709203F
fuel gauge watches the backup battery. Readings go to the built-in screen,
InfluxDB, and Pushover (when the delta is out of range, or the battery says we may
be off wall power).

Circuitpython web workflow: http://esp-radon.local/code/

### What it does

- Reads both sensors every 2 minutes (`sampling_interval` in `settings.toml`) and
  hands each reading to every reporter. A failing reporter never stops the others
  or the sensor loop.
  - **Display** (`reporters/display.py`): see below.
  - **InfluxDB** (`reporters/db.py`): line protocol over HTTP to InfluxDB 1.x.
    Fields: `internal`, `ambient`, `delta` (hPa), `temp` (F), `battery` (%) and
    `battery_voltage` (V).
  - **Notifications** (`reporters/notifier.py`, Pushover): once a day at most while
    the delta is out of range. The once-a-day timer starts only after Pushover
    accepts the message, so a failed send is retried.
- **Battery alert** (`code.py`): one Pushover notification when the fuel gauge
  drops below `battery_notify_below` percent, re-armed when it recovers. Set it to
  0 to turn it off (a worn battery may never read full again).
- A reading with an ambient temperature at or below 0F is treated as the ambient
  sensor misbehaving: it's logged as a sensor error and not reported.

### Display

The screen turns off after `display_timeout` seconds (60 by default; 0 = never) and
stays on while anything is failing. The button (D0, the BOOT button) wakes it; the
first press only wakes it, later presses cycle the pages:

1. **Readings**: the delta in big text (cyan when OK, red when not), then internal
   and ambient pressure.
2. **Status**: battery percent and voltage, Wi-Fi signal, temperature, time since the last reading.
3. **Error log**: each source that has failed (sensor, battery, influx, notify,
   alert, display, watchdog) with how long it has been failing and the latest
   message. Recovered sources stay listed as "ok for ..." so a blip you missed is
   still visible.

While any source is failing, a red `!` shows in the top-right corner of every page
and the NeoPixel stays red between samples (it flashes green while sampling and is
off when all is well).

### Reliability

- **Watchdog:** resets the board if the main loop stalls. The loop feeds it, but
  only while there has been a good pressure sensor read within 3x the sampling
  interval (60 second minimum), so a dead sensor or an uncaught exception reboots
  the board, but a Wi-Fi or InfluxDB outage does not. The hardware timeout is that
  same limit. Once armed, the watchdog keeps running across code reloads (only a
  hard reset stops it), so a reload keeps the existing timeout. After a watchdog
  reset the error log shows "watchdog: restarted after stall" until the first good
  read.
- **Wi-Fi:** `net.py` reconnects whenever the connection is down and builds a new
  HTTP session after a reconnect or a failed request. Requests time out (5 seconds
  for InfluxDB, 10 for Pushover) and failures show up in the error log. After 12
  failed reconnects in a row the board reboots. Readings that fail to send are not
  queued.
- **Sensors:** if they can't be reached at boot, the error is shown and setup is
  retried every 5 seconds instead of crashing (the watchdog reboots the board if
  that goes on). After a failed read they're set up again on the next cycle. The
  battery gauge is optional: a missing gauge is logged but doesn't stop the
  pressure readings.
- **Memory:** `gc.collect()` runs once per cycle.

### Configuration and files

- `settings.toml` (gitignored; copy `settings.toml.example`): Wi-Fi
  (`CIRCUITPY_WIFI_SSID`, `CIRCUITPY_WIFI_PASSWORD`), the board's name
  (`CIRCUITPY_WIFI_HOSTNAME`; `code.py` also advertises it as `<hostname>.local`,
  which the scripts use), web workflow
  (`CIRCUITPY_WEB_API_PASSWORD`), `sampling_interval` (ms), `delta_threshold`,
  `battery_notify_below`, `button_pin`, `display_timeout`, InfluxDB (`db_host`,
  `db_port`, `db_database`, `db_table`, `db_username`, `db_password`), and Pushover
  (`pushover_user`, `pushover_token`). It replaces the old `secrets.py`.
- `boot.py`: hides the USB drive unless the button is held (see below).
- `code.py`: setup and the main loop.
- `net.py`: Wi-Fi reconnect and the shared HTTP session.
- `adafruit_bmp280.py`: our patched copy of the BMP280 library. The sensor reports
  chip ID 0x40 and the stock library only accepts 0x58, so this copy accepts 0x40.
  It's deployed to the board's root, which Python searches before `lib/`, so
  circup installs and updates can't overwrite it.
- `reporters/`: `display.py`, `db.py`, `notifier.py`, and `log.py` (empty).
- `scripts/`: Node scripts behind the npm commands below.
- `snippets/`: scratch code that isn't deployed.

## Development workflow

The board is hard to reach, so USB mass storage is disabled and everything goes
over Wi-Fi with web workflow. Run `npm install` once. All of these are also VS
Code tasks (**Terminal > Run Task**, [.vscode/tasks.json](.vscode/tasks.json)):

- **deploy** (`npm run deploy`): copy `settings.toml`, `net.py`,
  `adafruit_bmp280.py`, `boot.py`, `reporters/*.py` and `code.py` to the board. The password comes from your local
  `settings.toml`. CircuitPython reloads as files land (so you may see it restart
  a few times); `code.py` is copied last. `boot.py` only takes effect after a reset.
- **fetch_from_board** (`npm run fetch-from-board`): copy files from the board to
  this directory, for when you edited with the web workflow code editor. Skips
  `lib/`. Then use normal git to commit and push.
- **add_deps** / **install_deps**: circup over web workflow (`pipx install circup`
  first). `add_deps` installs the libraries `code.py`, `net.py` and the reporters
  import, then writes `requirements.txt`; `install_deps` installs from it onto a
  fresh board.
- **deploy_usb**, **add_deps_usb**, **install_deps_usb**: the same, over a mounted
  `/Volumes/CIRCUITPY`, for when you have the board on your desk in recovery mode.

### Recovery mode (USB mass storage)

Tap RESET, then press and hold the button (D0/BOOT) while the NeoPixel is blue
(about 3 seconds). It turns green and the `CIRCUITPY` drive shows up. Don't hold the
button *through* the reset: that puts the chip in its ROM bootloader instead. While
the drive is mounted on a computer, web workflow can't write files (deploy reports
a 409).

If `button_pin` in `settings.toml` is wrong, `boot.py` leaves USB enabled rather
than locking you out.

TODO:

- [ ] Better way of detecting battery power - switch to using battery voltage (see claude convo)
- [ ] Require 2 or 3 successive measurements out of threshold before sending notification
  - i'm not sure this is necessary, we don't get false alarms...
- [ ] use bmp580
