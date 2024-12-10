#!/bin/bash
set -e

INSTALL_DIR="/opt/smart-hub"
CONFIG_DIR="$INSTALL_DIR/config"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

log() {
    echo -e "${GREEN}[$(date '+%Y-%m-%d %H:%M:%S')] $1${NC}"
}

error() {
    echo -e "${RED}[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $1${NC}"
    exit 1
}

install_zigbee() {
    log "Starting Zigbee coordinator installation..."

    # Install dependencies if not present
    apt-get update
    apt-get install -y python3-pip python3-zeroconf jq

    # Run discovery
    python3 "$INSTALL_DIR/services/zigbee2mqtt/discover_slzb06.py" > /tmp/zigbee_devices.json

    if [ ! -s /tmp/zigbee_devices.json ]; then
        error "No Zigbee coordinators found"
    fi

    # Configure discovered devices
    configure_zigbee_network

    # Start service
    systemctl enable zigbee2mqtt
    systemctl start zigbee2mqtt

    log "Zigbee coordinator installation completed"
}

# Can be run independently
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    install_zigbee
fi