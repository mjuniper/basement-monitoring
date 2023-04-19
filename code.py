import board
import terminalio
import neopixel
from adafruit_display_text import bitmap_label
import time
import displayio
import adafruit_lps35hw
import adafruit_bmp280
from secrets import secrets
import wifi
from reporters.display import DisplayReporter
from reporters.db import InfluxDbReporter
from reporters.notifier import NotificationReporter
from adafruit_lc709203f import LC709203F, PackSize
import gc

# web workflow info: https://learn.adafruit.com/getting-started-with-web-workflow-using-the-code-editor/device-setup

# #####
# setup neopixel
# #####
pixel = neopixel.NeoPixel(board.NEOPIXEL, 1)
pixel.brightness = .02

# #####
# setup reporters
# #####
reporters = []
def report(data):
    for reporter in reporters:
        reporter.report(data)

display_reporter = DisplayReporter(secrets)
reporters.append(display_reporter)
reporters.append(InfluxDbReporter(secrets))
notification_reporter = NotificationReporter(secrets)
reporters.append(notification_reporter)

# #####
# connect to the network
# #####
display_reporter.showMessage("Connecting to\n%s" % secrets["ssid"])
try:
    wifi.radio.connect(secrets["ssid"], secrets["password"])
except Exception as e:
    display_reporter.showMessage("Error connecting\nto network: " + str(e))

display_reporter.showMessage("Connected to\n%s!" % secrets["ssid"])

time.sleep(5)

# #####
# setup to read sensors
# #####
stemma_i2c = board.STEMMA_I2C()  # For using the built-in STEMMA QT connector on a microcontroller
internal = adafruit_lps35hw.LPS35HW(stemma_i2c)
ambient = adafruit_bmp280.Adafruit_BMP280_I2C(stemma_i2c)

lc709203 = LC709203F(stemma_i2c)
lc709203.pack_size = PackSize.MAH100
hasSentBatteryNotification = False

# #####
# loop!
# #####
while True:
    pixel.fill((0, 255, 0))

    # #####
    # check the network?
    # todo: if we don't have network, print that info to screen and make sure it stays there...
    # #####

    # #####
    # read the sensors
    # #####
    data = {
        "internal": internal.pressure,
        "ambient": ambient.pressure,
        "delta": internal.pressure - ambient.pressure,
        "temp": ambient.temperature * 1.8 + 32
    }

    # #####
    # send data to appropriate places (influxdb, the screen, a log file, an alert to my phone)
    report(data)
    # #####

    # #####
    # check if the battery voltage / % is below max - that means we are on battery power
    try:
        batt = lc709203.cell_percent
        print(f"Battery percentage: {batt:.1f}%")
        print(f"Free memory: {gc.mem_free() / 1024}Kb\n")
        if batt < 99 and not hasSentBatteryNotification:
            notification_reporter.sendNotification("Basement monitor may be on battery power.")
            hasSentBatteryNotification = True
        elif batt > 99:
            hasSentBatteryNotification = False
    except Exception as e:
        print('Battery check error: ' + str(e) + '\n')
    # #####

    pixel.fill((0, 0, 0))

    time.sleep(5)