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

# i had this at every 5 seconds - that is a little silly
# increasing to 5 minutes -the downside is that, the way i have it coded,
# it will be hard to get the display to show anything because you have to be 
# holding the button when it does the pass through the loop
# there are ways around that
interval = 2 * 60 # 2 minites

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
    # the ambient pressure sensor gets wonky sometimes...
    if data["temp"] > 0:
        for reporter in reporters:
            reporter.report(data)
    else:
        print("Data out of range....")
        print(f"  - Ambient temp: {data["temp"]}F")
        print(f"  - Ambient pressure: {data["ambient"]}")
        print(f"  - Internal pressure: {data["internal"]}")
        print(f"  - Delta: {data["delta"]}\n")

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

time.sleep(5)

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

    # i think i have a memory leak... or maybe that is just the way python works???
    # free memory continuously falls with every iteration of the loop until it gets down to a few k
    # then it goes back up - presumably because garbage collection happened
    # if i manually do garbage collection as below, it stays high
    # but i think we will let garbage collection happen on its own
    # gc.collect()

    time.sleep(interval)