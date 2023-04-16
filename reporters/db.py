import wifi
import ssl
import socketpool
import adafruit_requests

class InfluxDbReporter:

    def __init__(self, secrets):
        self.host = secrets['host']
        self.port = secrets['port']
        self.database = secrets['database']
        self.table = secrets['table']
        self.username = secrets['username']
        self.password = secrets['dbpassword']

        self.table = secrets['table']

        
        pool = socketpool.SocketPool(wifi.radio)
        self.session = adafruit_requests.Session(pool, ssl.create_default_context())
    
    def report(self, data):
        try:
            # influxdb "line protocol"
            # https://docs.influxdata.com/influxdb/v1.8/guides/write_data/#write-data-using-the-influxdb-api
            point = self.table + " " + ','.join(f'{k}={v}' for k,v in data.items())
            url = f"http://{self.host}:{self.port}/write?db={self.database}"
            # print(url)

            headers = {"Authorization": f"Token {self.username}:{self.password}"}
            # headers.setdefault('Content-Type', 'application/octet-stream')
            # headers.setdefault('Accept', 'application/x-msgpack')

            response = self.session.post(url, data=point, headers=headers)
        except Exception as e:
            print('InfluxDbReporter error: ' + str(e))

