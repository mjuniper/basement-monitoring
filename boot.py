# boot.py
#
# Runs once at power-up or hard reset (not on a code reload).
#
# Normal boot: hide the CIRCUITPY USB drive. The board lives somewhere hard to
# reach and is edited over Wi-Fi (web workflow), which can only write to the
# filesystem while a computer isn't mounting it over USB.
#
# Recovery boot: tap RESET, then press and hold the button while the NeoPixel is
# blue (about 3 seconds). The NeoPixel turns green and the USB drive stays on.
#
# Why press AFTER reset: the BOOT button is GPIO0. Holding it *through* a reset
# drops the chip into its ROM bootloader (the TFTS3BOOT drive) instead of
# starting CircuitPython. Pressing it once CircuitPython is running is harmless,
# so this waits a few seconds for you instead of checking only once.
#
# If anything goes wrong checking the button (say a typo in button_pin), the USB
# drive is left enabled so a bad setting can't lock you out.

import os
import time
import board
import digitalio
import neopixel
import storage

WINDOW_SECONDS = 3

try:
  pixel = neopixel.NeoPixel(board.NEOPIXEL, 1, brightness=0.2)
  button = digitalio.DigitalInOut(getattr(board, os.getenv("button_pin", "D0")))
  button.switch_to_input(pull=digitalio.Pull.UP)  # active low

  pixel[0] = (0, 0, 255)  # blue: press and hold the button now to keep USB storage
  held = False
  deadline = time.monotonic() + WINDOW_SECONDS
  while time.monotonic() < deadline:
    if not button.value:
      held = True
      break
    time.sleep(0.02)
  button.deinit()

  if held:
    pixel[0] = (0, 255, 0)  # green: USB mass storage stays enabled
    time.sleep(1)
  else:
    storage.disable_usb_drive()
    pixel[0] = (0, 0, 0)
except Exception as e:
  print("boot.py: " + type(e).__name__ + ": " + str(e) + " (leaving USB drive enabled)")
