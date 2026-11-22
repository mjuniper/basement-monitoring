# reporters/notifier.py
#
# Sends Pushover notifications. As a reporter it alerts when the pressure
# differential is outside the expected range; code.py also calls
# sendNotification() directly for the battery alert.

import os
import time
import net

ONE_DAY_NS = 24 * 60 * 60 * 1000000000


class NotificationReporter:
  name = "notify"

  def __init__(self, threshold):
    self.threshold = threshold
    self.user = os.getenv("pushover_user")
    self.token = os.getenv("pushover_token")
    # When Pushover last accepted a differential alert (time.monotonic_ns), or
    # None if it hasn't yet. It's only set after a successful send, so a failed
    # send is retried on the next cycle instead of being silenced for a day.
    self.last_alert = None

  def sendNotification(self, msg):
    # Raises if the notification didn't go through, so the caller can log it.
    session = net.ensure()
    data = {
      "token": self.token,
      "user": self.user,
      "message": msg,
    }
    try:
      response = session.post(
        "https://api.pushover.net:443/1/messages.json", json=data, timeout=10
      )
      try:
        if response.status_code != 200:
          raise RuntimeError("Pushover HTTP " + str(response.status_code))
        if response.json().get("status") != 1:
          raise RuntimeError("Pushover did not accept the notification")
      finally:
        response.close()
    except Exception:
      net.drop_session()
      raise

  def shouldSendAlert(self):
    # Only alert about the differential once a day.
    return self.last_alert is None or time.monotonic_ns() - self.last_alert > ONE_DAY_NS

  def report(self, data):
    delta = data["delta"]
    if delta >= -self.threshold and self.shouldSendAlert():
      self.sendNotification(
        "Radon mitigation system is outside expected pressure differential %.2f." % delta
      )
      self.last_alert = time.monotonic_ns()
