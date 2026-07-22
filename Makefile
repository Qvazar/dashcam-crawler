# NOTE: This Makefile targets Debian/Ubuntu systems (uses dpkg for dependency
#       checks and apt-compatible package names). Adjust DEPS and check-deps
#       for other distributions.

PROJECT_ROOT := $(shell pwd)
VENV_DIR     := $(PROJECT_ROOT)/.venv
SERVICE_NAME := dashcam-crawler.service
SERVICE_DIR  := /etc/systemd/system
SERVICE_FILE := $(SERVICE_DIR)/$(SERVICE_NAME)
CONFIG_FILE := /etc/dashcam-crawler.conf
USER         := dashcam-crawler
DATA_DIR     := /var/dashcam-crawler
PYTHON       := $(shell command -v python3)
DEPS         := wireless-tools iproute2 sqlite3 python3 python3-pip python3-venv

.PHONY: install uninstall check-deps venv

install: check-deps venv
	@echo "### Setting up user and directories..."
	# Exit code 9 means the user already exists, which is acceptable.
	sudo useradd -d "$(DATA_DIR)" -m "$(USER)" 2>/dev/null || true
	sudo install -d -m 755 -o "$(USER)" -g "$(USER)" "$(DATA_DIR)"

	@echo "### Setting up configuration..."
	if [ ! -f "$(CONFIG_FILE)" ]; then \
		sudo install -m 644 "$(PROJECT_ROOT)/dashcam-crawler.conf" "$(CONFIG_FILE)"; \
	fi

	@echo "### Setting up systemd service..."
	# Disable any running instance before overwriting; errors are ignored if not installed yet.
	sudo systemctl disable --now "$(SERVICE_NAME)" 2>/dev/null || true
	PROJECT_ROOT="$(PROJECT_ROOT)" VENV_DIR="$(VENV_DIR)" USER="$(USER)" DATA_DIR="$(DATA_DIR)" \
		envsubst < "$(PROJECT_ROOT)/$(SERVICE_NAME)" | sudo tee "$(SERVICE_FILE)" >/dev/null
	sudo systemctl daemon-reload
	sudo systemctl enable "$(SERVICE_NAME)"
	sudo systemctl start "$(SERVICE_NAME)"

	@echo "### Installation complete."
	@echo "The service '$(SERVICE_NAME)' has been started and enabled."
	@echo "Configuration file is located at $(CONFIG_FILE). Please edit it as needed and restart the service with: systemctl restart $(SERVICE_NAME)"
	@echo "Logs can be viewed using: journalctl -u $(SERVICE_NAME) -f"

uninstall:
	@echo "### Stopping and disabling systemd service..."
	sudo systemctl disable --now "$(SERVICE_NAME)" 2>/dev/null || true
	sudo rm -f "$(SERVICE_FILE)"
	sudo systemctl daemon-reload

	@echo "### Keeping configuration file at $(CONFIG_FILE)"

	@echo "### Removing user and data directory..."
	# userdel may fail if the user doesn't exist or has running processes; errors are ignored.
	sudo userdel -r "$(USER)" 2>/dev/null || true
	sudo rm -rf "$(DATA_DIR)"

	@echo "### Removing virtual environment..."
	rm -rf "$(VENV_DIR)"

	@echo "### Uninstallation complete."

check-deps:
	@echo "### Verifying dependencies..."
	@missing=""; \
	for dep in $(DEPS); do \
		if ! dpkg -l "$$dep" 2>/dev/null | grep -q '^ii'; then \
			missing="$$missing $$dep"; \
		fi; \
	done; \
	if [ -n "$$missing" ]; then \
		echo "### Installing missing dependencies:$$missing"; \
		sudo apt-get update; \
		sudo apt-get install -y $$missing; \
	fi

venv:
	@echo "### Setting up virtual environment and installing Python dependencies..."
	if [ ! -d "$(VENV_DIR)" ]; then \
		"$(PYTHON)" -m venv "$(VENV_DIR)"; \
	fi
	@echo "### Upgrading pip and installing requirements..."
	"$(VENV_DIR)/bin/pip" install --upgrade pip
	if [ -f "$(PROJECT_ROOT)/requirements.txt" ]; then \
		"$(VENV_DIR)/bin/pip" install -r "$(PROJECT_ROOT)/requirements.txt"; \
	fi
