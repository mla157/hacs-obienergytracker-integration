"""Constants for the obienergytracker integration."""

from __future__ import annotations

DOMAIN = "obi_energy_tracker"

# Config constants
CONF_COUNTRY = "country"
CONF_BRIDGE_ID = "bridge_id"
CONF_DEVICE_ID = "device_id"
# Entries created with multi-sensor support suffix entity unique IDs with the
# sensor ID, so several sensors (bridges) of one account can coexist. Entries
# created before keep their unsuffixed IDs and therefore their history.
CONF_SCOPED_IDS = "scoped_unique_ids"

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

# OAuth2 Authentication via auth.obi.com (Keycloak with PKCE)
OAUTH2_CLIENT_ID = "home-assistant-user"
OAUTH2_SCOPES = "openid email profile offline_access"

_OPENID_CONNECT = (
    "https://auth.obi.com/auth/realms/energy-tracker-clients/protocol/openid-connect"
)

OAUTH2_AUTHORIZE_URL = f"{_OPENID_CONNECT}/auth"
OAUTH2_TOKEN_URL = f"{_OPENID_CONNECT}/token"
OAUTH2_LOGOUT_URL = f"{_OPENID_CONNECT}/logout"
