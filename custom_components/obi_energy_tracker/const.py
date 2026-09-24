"""Constants for the obienergytracker integration."""

DOMAIN = "obi_energy_tracker"

# Config constants
CONF_COUNTRY = "country"
CONF_BRIDGE_ID = "bridge_id"
CONF_DEVICE_ID = "device_id"

# Default values
DEFAULT_COUNTRY = "DE"
DEFAULT_SCAN_INTERVAL = 300  # 5 minutes

# Live mode. The app switches the sensor's upload interval between these two
# values and the backend accepts no others: anything else gives HTTP 400.
LIVE_UPLOAD_INTERVAL = 2
IDLE_UPLOAD_INTERVAL = 300

# The sensor is battery powered and uploads every two seconds while live mode
# runs, so it switches itself off again after this many seconds.
LIVE_TIMEOUT = 600

# Data attributes
ATTR_BRIDGE_ID = "bridge_id"
ATTR_DEVICE_ID = "device_id"
