import logging
import os

class CustomLogger(logging.getLoggerClass()):
    def __init__(self, name):
        super().__init__(name)
        self._setLoggerSpecificLevel()

    def _setLoggerSpecificLevel(self):
        """Set the logger-specific log level from environment variable."""
        env_var_name = f"LOGLEVEL_{self.name.upper()}"
        level = os.environ.get(env_var_name, None)
        if level:
            self.setLevel(level)

    def isDebugEnabled(self):
        """Check if the logger is enabled for DEBUG level."""
        return self.isEnabledFor(logging.DEBUG)


LOGLEVEL = os.environ.get("LOGLEVEL", "INFO").upper()
logging.basicConfig(level=LOGLEVEL, format='%(asctime)s %(levelname)s %(name)s %(message)s')
logging.setLoggerClass(CustomLogger)

getLogger = logging.getLogger
