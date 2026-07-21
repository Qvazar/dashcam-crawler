import logging
import subprocess

logger = logging.getLogger(__name__)

def get_current_ssid():
    """Retrieves the SSID of the WiFi network the Pi is currently connected to."""
    try:
        # Ask Linux network tools for the active SSID
        result = subprocess.run(
            ["iwgetid", "-r"], capture_output=True, text=True, check=True
        )
        return result.stdout.strip()
    except Exception as e:
        logger.debug("Unable to retrieve current SSID: %s", e)
        return None


def get_network_gateway():
    """Retrieves the gateway IP address of the current network."""
    try:
        result = subprocess.run(
            ["ip", "route", "show", "default"], capture_output=True, text=True, check=True
        )
        for line in result.stdout.splitlines():
            if line.startswith("default"):
                parts = line.split()
                gateway_index = parts.index("via") + 1
                return parts[gateway_index]
        return None
    except Exception as e:
        logger.exception("Unable to retrieve network gateway: %s", e)
        return None
