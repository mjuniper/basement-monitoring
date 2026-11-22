# reporters/display.py
#
# Shows the pressure readings on the built-in TFT, plus a persistent error
# indicator and an error log page.
#
# Pages (the button cycles through these):
#   readings  the pressure differential (big), then internal and ambient pressure
#   status    battery, Wi-Fi signal, temperature, time since the last reading
#   log       one entry per failing (or recently recovered) source
# There is also a "message" page for boot status. It isn't part of the cycle.
#
# A red "!" in the top-right corner of every page means something is failing.
# The screen turns off after display_timeout seconds without a button press, but
# it stays on while anything is failing, so a problem is never hidden by a dark
# screen. The first press on a sleeping screen only wakes it.

import os
import time
import board
import displayio
import terminalio
import wifi
from adafruit_display_text import bitmap_label, wrap_text_to_pixels

CYAN = 0x00FFFF
GREEN = 0x00FA9A
RED = 0xFF0000

BRIGHTNESS = 0.4

PAGE_READINGS = 0
PAGE_STATUS = 1
PAGE_LOG = 2
PAGE_MESSAGE = 3
# How many pages the button cycles through. The message page is left out.
NUM_MODES = 3

# Vertical position of each row on the readings page, as a percent of the screen
# height (measured to the middle of the row). Nudge these if it looks cramped.
ROW_DELTA = 22
ROW_DELTA_NAME = 53
ROW_CELL_NAME = 71
ROW_CELL_VALUE = 86

# The log page is drawn at scale 1 (smallest text) so more fits. Leave room on
# the right so wrapped text doesn't run under the "!" indicator.
LOG_MARGIN = 4
LOG_WRAP_WIDTH_RESERVED = 30
LOG_MAX_LINES = 12

NS_PER_SECOND = 1000000000


def _label(text, scale, x, y, anchor=(0.5, 0.5), color=CYAN):
  label = bitmap_label.Label(terminalio.FONT, text=text, scale=scale)
  label.color = color
  label.anchor_point = anchor
  label.anchored_position = (x, y)
  return label


def _age(ns):
  # Format a nanosecond duration as a short string like 45s, 12m, 3h or 2d.
  seconds = ns // NS_PER_SECOND
  if seconds < 60:
    return f"{seconds}s"
  if seconds < 3600:
    return f"{seconds // 60}m"
  if seconds < 86400:
    return f"{seconds // 3600}h"
  return f"{seconds // 86400}d"


class DisplayReporter:
  # code.py uses this name when it logs or clears errors for this reporter.
  name = "display"

  def __init__(self, threshold):
    self.threshold = threshold

    self.display = board.DISPLAY
    self.display.brightness = BRIGHTNESS

    # Screen sleep. A timeout of 0 means never sleep.
    self.timeout_ns = int(os.getenv("display_timeout", 60)) * NS_PER_SECOND
    self.asleep = False
    self.last_activity = time.monotonic_ns()

    # The page the button has selected (0..NUM_MODES-1), and the page actually
    # showing (which can also be the message page).
    self.mode = PAGE_READINGS
    self.current = PAGE_MESSAGE

    # The latest readings, for redrawing the status page, and when they arrived.
    self.last = None
    self.last_report = None

    # One entry per error source ("sensor", "influx", "display", ...):
    #   self.errors["influx"] = {"msg": "HTTP 401", "since": <ns>, "active": True}
    # Keyed by source, so the dict can never grow beyond a handful of entries no
    # matter how long an outage lasts. "since" is when the state last changed:
    # the failure start while active, or the recovery time once active is False.
    self.errors = {}

    width, height = self.display.width, self.display.height

    # ---- readings page ----
    readings = displayio.Group()
    self.delta_value = _label("--", 4, width // 2, height * ROW_DELTA // 100)
    self.delta_name = _label("DELTA hPa", 2, width // 2, height * ROW_DELTA_NAME // 100)
    self.internal_value = _label("--", 2, width // 4, height * ROW_CELL_VALUE // 100)
    self.ambient_value = _label("--", 2, width * 3 // 4, height * ROW_CELL_VALUE // 100)
    for widget in (
      self.delta_value,
      self.delta_name,
      _label("INTERNAL", 1, width // 4, height * ROW_CELL_NAME // 100),
      _label("AMBIENT", 1, width * 3 // 4, height * ROW_CELL_NAME // 100),
      self.internal_value,
      self.ambient_value,
    ):
      readings.append(widget)

    # ---- status page ----
    status = displayio.Group()
    self.status_label = _label("", 2, 8, 8, anchor=(0, 0))
    self.status_label.line_spacing = 1.0
    status.append(self.status_label)

    # ---- log page ----
    log = displayio.Group()
    self.log_label = _label("", 1, LOG_MARGIN, LOG_MARGIN, anchor=(0, 0))
    log.append(self.log_label)

    # ---- message page ----
    # Big centered text for boot status ("Connecting to ...").
    message = displayio.Group()
    self.message = _label("", 2, width // 2, height // 2, color=GREEN)
    message.append(self.message)

    # Index in this list == the PAGE_* constants.
    self.pages = [readings, status, log, message]

    # ---- error indicator ----
    # A plain "!" label in the corner. It sits in the root group above the pages,
    # so it's drawn on top of whichever page is showing.
    self.indicator = _label("!", 2, width - 4, 2, anchor=(1, 0), color=RED)
    self.indicator.hidden = True  # shown only while errors are active

    self.root = displayio.Group()
    for page in self.pages:
      self.root.append(page)
    self.root.append(self.indicator)

    # display.show() is deprecated in newer CircuitPython in favor of root_group.
    if hasattr(self.display, "root_group"):
      self.display.root_group = self.root
    else:
      self.display.show(self.root)

    self._render_status()
    self._render_log()
    self._show(PAGE_MESSAGE)

  # -------------------------------------------------------------------------
  # Screen on/off and pages
  # -------------------------------------------------------------------------

  def wake(self):
    self.last_activity = time.monotonic_ns()
    if self.asleep:
      self.asleep = False
      self.display.brightness = BRIGHTNESS

  def tick(self):
    # Call this often from the main loop. It handles the screen timeout.
    if self.has_errors:
      self.wake()  # never let a problem hide behind a dark screen
    elif (
      self.timeout_ns > 0
      and not self.asleep
      and time.monotonic_ns() - self.last_activity > self.timeout_ns
    ):
      self.asleep = True
      self.display.brightness = 0

  def _show(self, index):
    self.current = index
    for i, page in enumerate(self.pages):
      page.hidden = i != index

  def buttonPressed(self):
    # The first press on a sleeping screen only wakes it.
    was_asleep = self.asleep
    self.wake()
    if was_asleep:
      return
    self.mode = (self.mode + 1) % NUM_MODES
    # Refresh the pages that show ages and signal strength before showing them.
    if self.mode == PAGE_STATUS:
      self._render_status()
    elif self.mode == PAGE_LOG:
      self._render_log()
    self._show(self.mode)

  def showMessage(self, msg):
    # Big centered status text. The next report() switches back to the page the
    # button selected.
    self.wake()
    self.message.text = msg
    self._show(PAGE_MESSAGE)
    print(msg)

  # -------------------------------------------------------------------------
  # Error tracking
  # -------------------------------------------------------------------------

  @property
  def has_errors(self):
    # True if any source is currently failing. code.py also uses this to drive
    # the NeoPixel.
    return any(err["active"] for err in self.errors.values())

  def logError(self, source, error):
    # Record that `source` is failing. Safe to call every loop while it keeps
    # failing; the original start time is kept.
    msg = str(error)
    print(source + " error: " + msg)

    existing = self.errors.get(source)
    if existing and existing["active"]:
      # Still failing: keep when it started, but show the latest message.
      existing["msg"] = msg
    else:
      # New failure (or a relapse after recovery): start the clock.
      self.errors[source] = {"msg": msg, "since": time.monotonic_ns(), "active": True}

    self.wake()
    self._refresh_log()

    # If a boot message is still on screen (say the very first sensor read
    # failed), it would stay there until a report() succeeds, hiding the problem.
    # Show the log page instead. self.mode is left alone, so once things recover
    # the next report() returns to the page the button had selected.
    if self.current == PAGE_MESSAGE:
      self._show(PAGE_LOG)

  def clearError(self, source):
    # Record that `source` worked. A no-op unless it was failing. The entry stays
    # in the log as "ok" so you can still see a blip that happened while you
    # weren't looking.
    err = self.errors.get(source)
    if err and err["active"]:
      err["active"] = False
      err["since"] = time.monotonic_ns()
      self._refresh_log()

  def _refresh_log(self):
    # Indicator on if anything is failing, off otherwise.
    self.indicator.hidden = not self.has_errors
    self._render_log()

  def _render_log(self):
    # Rebuild the log page text from self.errors.
    if not self.errors:
      self.log_label.color = GREEN
      self.log_label.text = "No errors"
      return

    now = time.monotonic_ns()
    wrap_width = self.display.width - LOG_MARGIN - LOG_WRAP_WIDTH_RESERVED
    lines = []

    for source, err in self.errors.items():
      age = _age(now - err["since"])
      if err["active"]:
        lines.append(f"! {source}: failing for {age}")
        # Wrap the (often long) message and indent it under the heading.
        for line in wrap_text_to_pixels(err["msg"], wrap_width, terminalio.FONT):
          lines.append("  " + line)
      else:
        lines.append(f"  {source}: ok for {age}")
        lines.append("  (last: " + err["msg"][:24] + ")")

    # Don't run off the bottom of the screen.
    self.log_label.text = "\n".join(lines[:LOG_MAX_LINES])
    # One color for the whole label: red while anything is failing.
    self.log_label.color = RED if self.has_errors else GREEN

  # -------------------------------------------------------------------------
  # Pages that show readings
  # -------------------------------------------------------------------------

  def _wifi_text(self):
    try:
      if wifi.radio.connected:
        info = wifi.radio.ap_info
        return "%d dBm" % info.rssi if info else "connected"
    except Exception:
      pass
    return "offline"

  def _render_status(self):
    if self.last is None:
      self.status_label.text = "Waiting for\nfirst reading"
      return

    battery = self.last.get("battery")
    voltage = self.last.get("battery_voltage")
    battery_text = "n/a" if battery is None else "%.0f%%" % battery
    if voltage is not None:
      battery_text += " %.2fV" % voltage
    self.status_label.text = "\n".join((
      "Battery " + battery_text,
      "Wi-Fi   " + self._wifi_text(),
      "Temp    %.1f F" % self.last["temp"],
      "Updated " + _age(time.monotonic_ns() - self.last_report) + " ago",
    ))

  def report(self, data):
    # Update the pages from a fresh set of readings.
    #
    # Exceptions are NOT caught here. code.py's report() wrapper catches them and
    # calls logError("display", e), so every reporter's failures end up in the
    # same place.
    self.last = data
    self.last_report = time.monotonic_ns()

    # The differential should be below -threshold; cyan when it is, red when not.
    color = CYAN if data["delta"] < -self.threshold else RED
    self.delta_value.text = "%.2f" % data["delta"]
    self.delta_value.color = color
    self.delta_name.color = color
    self.internal_value.text = "%.1f" % data["internal"]
    self.ambient_value.text = "%.1f" % data["ambient"]

    self._render_status()

    # Return to the page the button selected (also dismisses a boot message).
    self._show(self.mode)

    # If you're sitting on the log page, keep its ages current.
    if self.mode == PAGE_LOG:
      self._render_log()
