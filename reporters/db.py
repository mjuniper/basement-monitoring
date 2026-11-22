# reporters/db.py
#
# Sends sensor readings to InfluxDB 1.x over HTTP using line protocol.
# Reads connection info from settings.toml via os.getenv().

import os
import net


class InfluxDbReporter:
  name = "influx"

  def __init__(self):
    self.host = os.getenv("db_host")
    self.port = os.getenv("db_port")
    self.database = os.getenv("db_database")
    self.table = os.getenv("db_table")
    self.username = os.getenv("db_username")
    self.password = os.getenv("db_password")

  def report(self, data):
    session = net.ensure()  # raises, with the reason, if we can't get online
    try:
      # Influx line protocol: "<measurement> field=value,field=value"
      # https://docs.influxdata.com/influxdb/v1.8/guides/write_data/#write-data-using-the-influxdb-api
      #
      # Skip None (and NaN, which is the only value not equal to itself).
      # A single bad value makes Influx reject the whole line.
      fields = ",".join(
        f"{k}={v}" for k, v in data.items() if v is not None and v == v
      )
      if not fields:
        print("InfluxDbReporter: no valid fields to report.")
        return

      point = self.table + " " + fields
      url = f"http://{self.host}:{self.port}/write?db={self.database}"
      headers = {"Authorization": f"Token {self.username}:{self.password}"}

      response = session.post(url, data=point, headers=headers, timeout=5)
      try:
        if not 200 <= response.status_code < 300:
          raise RuntimeError("HTTP " + str(response.status_code))
      finally:
        response.close()
    except Exception:
      net.drop_session()  # rebuild next time
      raise
