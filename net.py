# net.py
#
# Wi-Fi and HTTP session handling shared by the reporters that use the network.
# ensure() is the one place that (re)connects, so every reporter gets the same
# behavior when the connection drops.

import os
import ssl
import microcontroller
import socketpool
import wifi
import adafruit_requests

# Failed connection attempts in a row before we reboot. Each reporter calls
# ensure() once per cycle, so at the default 2 minute interval this is roughly
# 25 minutes without Wi-Fi.
MAX_CONNECT_FAILURES = 12

_session = None
_failures = 0


def ensure():
  # Make sure we're on Wi-Fi and return a live HTTP session. If we can't get
  # online, raise a RuntimeError that says why (for example "Wi-Fi:
  # ConnectionError: No network with that ssid") so the reason reaches the error
  # log instead of being lost.
  global _session, _failures
  try:
    if not wifi.radio.connected:
      wifi.radio.connect(
        os.getenv("CIRCUITPY_WIFI_SSID"),
        os.getenv("CIRCUITPY_WIFI_PASSWORD"),
      )
      # We just (re)connected, so any old session is tied to a dead connection.
      _session = None

    # Also covers first boot, when CircuitPython may have connected from
    # settings.toml before we ran.
    if _session is None:
      pool = socketpool.SocketPool(wifi.radio)
      _session = adafruit_requests.Session(pool, ssl.create_default_context())

    _failures = 0
    return _session
  except Exception as e:
    _session = None
    _failures += 1
    if _failures > MAX_CONNECT_FAILURES:
      # Reconnecting isn't working; a reboot also clears a wedged Wi-Fi stack.
      microcontroller.reset()
    # Include the exception type too, since some have an empty message.
    raise RuntimeError("Wi-Fi: " + type(e).__name__ + ": " + str(e))


def drop_session():
  # Call after a failed request: a session tied to a broken connection can't be
  # trusted, so the next ensure() builds a fresh one.
  global _session
  _session = None
