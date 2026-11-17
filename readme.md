
Circuitpython web workflow:
http://cpy-5970ec.local/code/

To sync this directory with the board:
  - edit code in the browser with "web workflow"
  - run `npm run fetch-from-board`
Then use normal git workflow to commit and push upstream

- [ ]  Hold a button while booting to enable usb mass storage
- [ ]  Reconnect if we lose wifi
- [ ]  Implement watchdog to reboot if anything goes wrong
- [ ]  Better button handling
- [ ]  Better error handling
- [ ]  Upgrade circuitpython and libs
- [ ]  Get rid of secrets.py and put stuff in settings.toml