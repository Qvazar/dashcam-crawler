import subprocess
from .logging import getLogger

logger = getLogger(__name__)

def get_current_ssid():
    """Retrieves the SSID of the WiFi network the Pi is currently connected to."""

    # Ask Linux network tools for the active SSID
    result = subprocess.run(
        ["iwgetid", "-r"], capture_output=True, text=True, check=False
    )

    if result.returncode != 0:
        logger.debug("iwgetid command failed with return code %d", result.returncode)
        return None
    else:
        return result.stdout.strip()


def get_network_gateway():
    """Retrieves the gateway IP address of the current network."""

    result = subprocess.run(
        ["ip", "route", "show", "default"], capture_output=True, text=True, check=True
    )
    for line in result.stdout.splitlines():
        if line.startswith("default"):
            parts = line.split()
            gateway_index = parts.index("via") + 1
            return parts[gateway_index]
    return None
