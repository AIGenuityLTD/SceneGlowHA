"""Constants for the SceneGlow integration."""

from datetime import timedelta
from typing import Final

from homeassistant.const import Platform

DOMAIN: Final = "sceneglow"
MANUFACTURER: Final = "AIGenuity LTD"
MODEL: Final = "SceneGlow"

PROTOCOL_VERSION: Final = 1
DEFAULT_PORT: Final = 47_990
DEFAULT_REQUEST_TIMEOUT: Final = 10.0
RECONCILE_INTERVAL: Final = timedelta(seconds=60)

CONF_INSTALLATION_ID: Final = "installation_id"
CONF_CLIENT_ID: Final = "client_id"
CONF_CLIENT_CREDENTIAL: Final = "client_credential"
CONF_SERVER_IDENTITY: Final = "server_identity"
CONF_PROTOCOL_VERSION: Final = "protocol_version"
CONF_USE_TLS: Final = "use_tls"
CONF_PAIRING_CODE: Final = "pairing_code"

PLATFORMS: Final = (
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.TEXT,
)
