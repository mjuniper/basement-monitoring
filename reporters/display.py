import board
import terminalio
import touchio
from adafruit_display_text import bitmap_label

class DisplayReporter:

    def __init__(self, params):
        self.threshold = params['threshold']
        
        self.touch1 = touchio.TouchIn(board.A4)
        self.touch2 = touchio.TouchIn(board.A5)
        # these are supposed to self calibrate when the board starts up but it sometimes does not work
        # see: https://learn.adafruit.com/adafruit-esp32-s2-tft-feather/capacitive-touch#setting-touch-threshold-manually-3112099
        self.touch1.threshold = self.touch1.raw_value + 200
        self.touch2.threshold = self.touch2.raw_value + 200

        # self.touch_info = f"touch1:: raw value: {self.touch1.raw_value}, threshold: {self.touch1.threshold}, value: {self.touch1.value}touch2:: raw value: {self.touch2.raw_value}, threshold: {self.touch2.threshold}, value: {self.touch2.value}\n"
      
        scale = 2
        self.text_area = bitmap_label.Label(terminalio.FONT, text="", scale=scale)
        self.text_area.anchor_point = (0.5, 0.5)
        self.text_area.anchored_position = (board.DISPLAY.width // 2, board.DISPLAY.height // 2)
        self.text_area.color = 0x00FFFF
        self.text_area.line_spacing = 1.25
        board.DISPLAY.brightness = 0.4
        board.DISPLAY.show(self.text_area)

    def toggleDisplay (self):
        shouldShow = self.touch1.value or self.touch2.value

        # print(f"touch1 raw value: {self.touch1.raw_value}")
        # print(f"touch2 raw value: {self.touch2.raw_value}")

        if shouldShow:
            board.DISPLAY.brightness = 0.4
        else:
            board.DISPLAY.brightness = 0

    def showMessage (self, msg):
        self.toggleDisplay()
        self.text_area.color = 0x00FFFF
        self.text_area.text = msg
        print(msg + '\n')
        # print(self.touch_info)

    def showError (self, msg):
        self.toggleDisplay()
        self.text_area.color = 0xFF0000
        self.text_area.text = msg
        print(msg)
    
    def report(self, data):
        try:
            msg = "Internal: %.2f hPa\nAmbient: %.2f hPa\nDelta: %.2f hPa\nTemperature: %.2f F" % (data["internal"], data["ambient"], data["delta"], data["temp"])
            if data['delta'] < (self.threshold * -1):
                self.showMessage(msg)
            else:
                self.showError(msg)
        except Exception as e:
            print('DisplayReporter error: ' + str(e))
