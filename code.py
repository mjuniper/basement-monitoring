# code.py
#
# Radon mitigation monitor. Reads the air pressure inside the vent pipe and
# outside it, and sends the difference (the delta) to the screen, InfluxDB and
# Pushover. Settings live in settings.toml; see settings.toml.example.
#
# web workflow info: https://learn.adafruit.com/getting-started-with-web-workflow-using-the-code-editor/device-setup

import gc
import os
import time
import board
import keypad
import mdns
import microcontroller
import neopixel
import wifi
from watchdog import WatchDogMode
import adafruit_lps35hw
import adafruit_bmp280
from adafruit_lc709203f import LC709203F, PackSize
import net
from reporters.display import DisplayReporter
from reporters.db import InfluxDbReporter
from reporters.notifier import NotificationReporter

sampling_interval = int(os.getenv("sampling_interval", 2 * 60 * 1000))  # milliseconds
delta_threshold = int(os.getenv("delta_threshold", 70))
battery_notify_below = int(os.getenv("battery_notify_below", 99))
button_pin = getattr(board, os.getenv("button_pin", "D0"))

# The web workflow advertises the board as cpy-<board>-<mac>.local, and
# CIRCUITPY_WIFI_HOSTNAME only sets the name the router sees (DHCP). Set the mDNS
# name to match, so <hostname>.local works too. This resets on every reload, so it
# lives here, early.
hostname = os.getenv("CIRCUITPY_WIFI_HOSTNAME")
if hostname:
  try:
    mdns.Server(wifi.radio).hostname = hostname
  except Exception as e:
    print("mDNS hostname not set:", e)

interval_ns = sampling_interval * 1000000

# Arm the watchdog BEFORE the sensor init, so a crash during boot also ends in a
# reset. It's fed from the loop, but only while there has been a good sensor read
# recently (see feed_watchdog), so a dead sensor or an uncaught exception reboots
# the board; a Wi-Fi or InfluxDB outage does not.
#
# Once armed the watchdog keeps running across code reloads (only a hard reset
# stops it), and setting the timeout on a running one raises "IDFError: Invalid
# argument". So only arm it if it isn't already running; after a reload it just
# keeps its existing timeout.
stall_limit_s = max(60, 3 * sampling_interval // 1000)  # 6 minutes at 2 minutes
stall_limit_ns = stall_limit_s * 1000000000
wdt = microcontroller.watchdog
if wdt.mode != WatchDogMode.RESET:
  wdt.timeout = stall_limit_s
  wdt.mode = WatchDogMode.RESET

last_good_read = time.monotonic_ns()

def feed_watchdog():
  # Feed the watchdog, but only if the last good sensor read is recent. Call this
  # from anywhere that might block for a while.
  if time.monotonic_ns() - last_good_read < stall_limit_ns:
    wdt.feed()

feed_watchdog()

# keypad.Keys scans the pin in the background, debounces it, and queues press
# events. That means one event per press (nothing repeats while held) and presses
# aren't lost when the loop is busy, e.g. blocked on a slow network request.
keys = keypad.Keys((button_pin,), value_when_pressed=False, pull=True)

# #####
# setup neopixel
# #####
pixel = neopixel.NeoPixel(board.NEOPIXEL, 1)
pixel.brightness = .02

# #####
# setup reporters
# #####
display_reporter = DisplayReporter(delta_threshold)
notification_reporter = NotificationReporter(delta_threshold)
reporters = [
  display_reporter,
  InfluxDbReporter(),
  notification_reporter,
]

def report(data):
  # A failing reporter never stops the others (or the sensor loop). Its error
  # goes to the display's error log under the reporter's name, and clears itself
  # the next time that reporter succeeds.
  for reporter in reporters:
    feed_watchdog()  # a slow reporter shouldn't trip a short watchdog timeout
    try:
      reporter.report(data)
      display_reporter.clearError(reporter.name)
    except Exception as e:
      display_reporter.logError(reporter.name, e)

# #####
# did the watchdog just restart us?
# #####
# A reset wipes the in-RAM error log, so without this we'd never know it
# happened. Log it now; it clears itself after the first good sensor read and
# then shows on the log page as "watchdog: ok for ...".
print("Reset reason:", microcontroller.cpu.reset_reason)
if microcontroller.cpu.reset_reason == microcontroller.ResetReason.WATCHDOG:
  display_reporter.logError("watchdog", "restarted after stall")

# #####
# connect to the network
# #####
display_reporter.showMessage("Connecting to\n%s" % os.getenv("CIRCUITPY_WIFI_SSID"))
try:
  net.ensure()
  display_reporter.showMessage("Connected")
except Exception as e:
  # Not fatal: every report() tries again and shows the reason on the log page.
  print(e)
  display_reporter.showMessage("No Wi-Fi\n(will keep trying)")
time.sleep(2)

# #####
# setup to read sensors
# #####
def init_sensors():
  # Everything that talks to the pressure sensors at boot. Raises if they can't
  # be reached (unplugged, loose cable, not up yet), so the caller can retry.
  i2c = board.STEMMA_I2C()  # the built-in STEMMA QT connector
  internal = adafruit_lps35hw.LPS35HW(i2c)  # inside the vent pipe
  ambient = adafruit_bmp280.Adafruit_BMP280_I2C(i2c)  # outside it
  return internal, ambient

# Don't let a missing sensor crash code.py (that would leave the board sitting on
# a traceback). Show the error on screen and keep trying. The watchdog is only fed
# for the first few minutes of this (see feed_watchdog), so if the sensors still
# aren't there by then, the board reboots, which also clears a stuck I2C bus.
display_reporter.showMessage("Starting sensors")
sensors = None
while sensors is None:
  try:
    sensors = init_sensors()
  except Exception as e:
    display_reporter.logError("sensor", e)  # also switches the screen to the log page
    feed_watchdog()  # allowed for a few minutes; after that the board reboots
    time.sleep(5)
last_good_read = time.monotonic_ns()  # the sensors answered, so the first read gets a fresh window
feed_watchdog()
display_reporter.showMessage("Sensors initialized")
time.sleep(2)

# The battery fuel gauge is optional: if it's missing we log it and carry on,
# rather than losing the pressure readings. It's set up on first use, and again
# after any failure.
gauge = None
battery_alert_sent = False

# #####
# loop!
# #####
# Track when the next sample is DUE rather than when the last one happened.
# Starting it at "now" makes the first pass through the loop sample right away,
# so we don't sit on the boot message for a whole interval (and the watchdog
# gets its first feed sooner).
next_sample = time.monotonic_ns()
while True:
  event = keys.events.get()
  if event and event.pressed:
    display_reporter.buttonPressed()
  display_reporter.tick()  # turns the screen off after a while (and keeps it on while failing)
  feed_watchdog()

  if time.monotonic_ns() >= next_sample:

    pixel.fill((0, 255, 0))

    # #####
    # read the pressure sensors
    # #####
    print("Reading sensor data...")
    data = None
    try:
      if sensors is None:
        sensors = init_sensors()
      internal, ambient = sensors
      internal_pressure = internal.pressure
      ambient_pressure = ambient.pressure
      temp = ambient.temperature * 1.8 + 32  # C -> F
      # The ambient pressure sensor gets wonky sometimes, and a temperature at or
      # below 0F is the tell. Treat that as a failed read rather than reporting
      # garbage; the watchdog reboots us if it keeps happening.
      if temp <= 0:
        raise RuntimeError("ambient sensor out of range: %.1f F" % temp)
      data = {
        "internal": internal_pressure,
        "ambient": ambient_pressure,
        "delta": internal_pressure - ambient_pressure,
        "temp": temp,
      }
      display_reporter.clearError("sensor")
      display_reporter.clearError("watchdog")  # no-op unless we just restarted
      last_good_read = time.monotonic_ns()
    except Exception as e:
      sensors = None  # set the sensors up again on the next cycle
      display_reporter.logError("sensor", e)

    # #####
    # check the battery
    # #####
    # If the battery is below its max, we're probably running on it. (A worn
    # battery may never reach the max again; see battery_notify_below in
    # settings.toml.) This is separate from the pressure readings: it still runs
    # when they fail, and a failure here doesn't stop them being reported.
    battery_percent = None
    battery_voltage = None
    try:
      if gauge is None:
        gauge = LC709203F(board.STEMMA_I2C())
        gauge.pack_size = PackSize.MAH100
      battery_percent = gauge.cell_percent
      battery_voltage = gauge.cell_voltage
      display_reporter.clearError("battery")
      print("Battery: %.1f%% %.2f V" % (battery_percent, battery_voltage))
    except Exception as e:
      gauge = None  # set it up again on the next cycle
      display_reporter.logError("battery", e)

    if battery_percent is not None:
      if battery_percent < battery_notify_below:
        if not battery_alert_sent:
          try:
            notification_reporter.sendNotification("Basement monitor may be on battery power.")
            battery_alert_sent = True
            display_reporter.clearError("alert")
          except Exception as e:
            # Not marked as sent, so it's tried again next cycle.
            display_reporter.logError("alert", e)
      else:
        battery_alert_sent = False  # back to full; alert again next time

    # #####
    # send data to appropriate places (the screen, influxdb, an alert to my phone)
    # #####
    if data is not None:
      # None is left out of the InfluxDB write
      data["battery"] = battery_percent
      data["battery_voltage"] = battery_voltage
      print("Sensor data read successfully:", data)
      report(data)

    pixel.fill((255, 0, 0) if display_reporter.has_errors else (0, 0, 0))

    # Collect garbage ourselves once per cycle instead of waiting for the heap to
    # run low. Free memory falling to a few KB and then jumping back up is normal
    # CircuitPython behavior, not a leak. Collecting on our own schedule is still
    # better: it happens right after reporting instead of in the middle of the
    # next HTTP request or display update, and it limits heap fragmentation (a big
    # allocation can fail even with lots of free RAM if it's scattered in small
    # pieces).
    gc.collect()
    print("Free memory: %.1f KB" % (gc.mem_free() / 1024))
    print("Cycle complete.")
    print("")

    # Schedule from now, not from the previous due time, so a slow cycle (say a
    # network timeout) just pushes the next sample out instead of triggering a
    # burst of catch-up samples.
    next_sample = time.monotonic_ns() + interval_ns

  # Don't spin flat out between checks; saves power and heat.
  time.sleep(0.02)
