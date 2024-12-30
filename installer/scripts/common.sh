#!/bin/bash

# Base directories
INSTALL_DIR="/opt/smart-hub"
SERVICE_USER="smarthub"

# Derived directories
CONFIG_DIR="$INSTALL_DIR/config"
LOG_DIR="/var/log/smart-hub"
ZIGBEE_DIR="$INSTALL_DIR/zigbee"
UPDATE_DIR="$INSTALL_DIR/services/update"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Common functions
log() {
    echo -e "${GREEN}[$(date '+%Y-%m-%d %H:%M:%S')] $1${NC}"
}

warn() {
    echo -e "${YELLOW}[$(date '+%Y-%m-%d %H:%M:%S')] WARNING: $1${NC}"
}

error() {
    echo -e "${RED}[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $1${NC}"
    exit 1
}