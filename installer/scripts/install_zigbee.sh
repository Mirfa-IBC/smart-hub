#!/bin/bash
set -e
SERVICE_USER="smarthub"
INSTALL_DIR="/opt/smart-hub"
CONFIG_DIR="$INSTALL_DIR/config"
ZIGBEE_DIR="/opt/smart-hub/zigbee"
ZIGBEE_CONFIG="$ZIGBEE_DIR/data/configuration.yaml"
ZIGBEE_CONFIG_BACKUP="$ZIGBEE_DIR/data/configuration.yaml.backup"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

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

check_zigbee_installation() {
    if [ -d "$ZIGBEE_DIR" ]; then
        if [ -f "$ZIGBEE_DIR/package.json" ] && [ -d "$ZIGBEE_DIR/node_modules" ]; then
            return 0  # Already installed
        fi
    fi
    return 1  # Not installed
}

check_nodejs_installation() {
    if command -v node >/dev/null 2>&1; then
        current_version=$(node -v | cut -d'v' -f2)
        required_version="20.0.0"
        if [ "$(printf '%s\n' "$required_version" "$current_version" | sort -V | head -n1)" = "$required_version" ]; then
            return 0  # Node.js already installed with correct version
        fi
    fi
    return 1  # Node.js not installed or version too low
}

install_dependencies() {
    log "Installing zigbee system dependencies..."
    apt-get update
    apt-get install -y curl make g++ gcc jq || error "Failed to install system dependencies"
    
    if ! check_nodejs_installation; then
        log "Installing Node.js..."
        curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
        apt-get install -y nodejs || error "Failed to install Node.js"
    else
        log "Node.js already installed with correct version"
    fi

    # Verify installations
    node_version=$(node --version)
    npm_version=$(npm --version)
    log "Node.js version: $node_version"
    log "NPM version: $npm_version"
}

install_zigbee2mqtt() {
    local npm_cache_dir="$INSTALL_DIR/.npm"
    
    # Ensure proper directory structure and permissions
    ensure_directory_permissions "$ZIGBEE_DIR" "755"
    ensure_directory_permissions "$ZIGBEE_DIR/data" "775"
    ensure_directory_permissions "$npm_cache_dir" "775"

    if check_zigbee_installation; then
        log "Zigbee2MQTT already installed. Checking for updates..."
        runuser -u $SERVICE_USER -- bash -c "cd $ZIGBEE_DIR && git reset --hard HEAD && git pull && HOME=$INSTALL_DIR npm install --cache $npm_cache_dir && npm ci"        # Check for package-lock.json and use appropriate npm command
        # if [ -f "$ZIGBEE_DIR/package-lock.json" ]; then
        #     runuser -u $SERVICE_USER -- bash -c "cd $ZIGBEE_DIR && HOME=$INSTALL_DIR npm ci --cache $npm_cache_dir"
        # else
        #     runuser -u $SERVICE_USER -- bash -c "cd $ZIGBEE_DIR && HOME=$INSTALL_DIR npm install --cache $npm_cache_dir"
        # fi
        return 0
    fi

    log "Installing Zigbee2MQTT..."
    
    # If directory exists but not properly initialized, remove it
    if [ -d "$ZIGBEE_DIR" ]; then
        log "Removing existing incomplete installation..."
        rm -rf "$ZIGBEE_DIR"
        ensure_directory_permissions "$ZIGBEE_DIR" "755"
    fi
    
    runuser -u $SERVICE_USER -- bash -c "git clone https://github.com/Koenkk/zigbee2mqtt.git $ZIGBEE_DIR"
    runuser -u $SERVICE_USER -- bash -c "HOME=$INSTALL_DIR npm ci --prefix $ZIGBEE_DIR --cache $npm_cache_dir"
    
    # Ensure permissions are correct after installation
    ensure_directory_permissions "$ZIGBEE_DIR/data" "775"
}
check_zigbee_installation() {
    if [ -d "$ZIGBEE_DIR" ]; then
        if [ -d "$ZIGBEE_DIR/.git" ] && [ -f "$ZIGBEE_DIR/package.json" ]; then
            return 0  # Properly installed
        fi
    fi
    return 1  # Not installed or incomplete
}

configure_zigbee_network() {
    log "Configuring Zigbee network..."

    ensure_directory_permissions "$(dirname $ZIGBEE_CONFIG)" "775"

    
    # Run discovery
    log "Running SLZB-06 discovery..."
    /opt/smart-hub/venv/bin/python "$INSTALL_DIR/services/zigbee2mqtt/discover_slzb06.py" > /tmp/zigbee_devices.json

    if [ ! -s /tmp/zigbee_devices.json ]; then
        error "No Zigbee coordinators found"
    fi

    # Read discovery results
    devices=$(cat /tmp/zigbee_devices.json)
    device_count=$(echo $devices | jq length)
    
    if [ $device_count -eq 0 ]; then
        error "No SLZB-06 devices found"
    fi

    # Backup existing configuration if it exists
    if [ -f "$ZIGBEE_CONFIG" ]; then
        log "Backing up existing configuration..."
        cp "$ZIGBEE_CONFIG" "$ZIGBEE_CONFIG_BACKUP"
    fi

    # Create config directory if it doesn't exist
    mkdir -p $(dirname $ZIGBEE_CONFIG)

    # Configure primary coordinator
    primary_address=$(echo $devices | jq -r '.[0].address')
    primary_port=$(echo $devices | jq -r '.[0].port')
    
    if [ -f "$ZIGBEE_CONFIG" ] && [ -s "$ZIGBEE_CONFIG" ]; then
        log "Existing configuration detected. Skipping creation of new configuration..."
        return 0
    fi
    # Check if we should create new configuration
    if [ ! -f "$ZIGBEE_CONFIG" ] || [ ! -s "$ZIGBEE_CONFIG" ]; then
        log "Creating new configuration..."
        # Create base config
        cat > $ZIGBEE_CONFIG << EOF
mqtt:
  base_topic: zigbee2mqtt
  server: mqtt://localhost:1883

serial:
  port: mdns://slzb-06

advanced:
  network_key: GENERATE
  pan_id: GENERATE
  channel: 15
  adapter_concurrent: 16
  adapter_delay: 100
  transmit_power: 20

frontend:
  port: 8080
  host: 0.0.0.0
  auth_token: GENERATE

availability:true
EOF
    else
        log "Updating existing configuration with new coordinator address..."
        # Only update the coordinator address in existing config
        sed -i "s|port: tcp://.*|port: tcp://${primary_address}:${primary_port}|" "$ZIGBEE_CONFIG"
    fi

    # Configure repeaters
    if [ $device_count -gt 1 ]; then
        log "Configuring ${device_count} additional repeaters..."
        
        # Check if external_converters section exists
        if ! grep -q "external_converters:" "$ZIGBEE_CONFIG"; then
            echo -e "\nexternal_converters:" >> "$ZIGBEE_CONFIG"
        fi
        
        # Add/update repeater configurations
        for i in $(seq 1 $((device_count-1))); do
            address=$(echo $devices | jq -r ".[$i].address")
            port=$(echo $devices | jq -r ".[$i].port")
            
            # Remove existing repeater config if it exists
            sed -i "/repeater$i:/,+5d" "$ZIGBEE_CONFIG"
            
            # Add new repeater config
            cat >> "$ZIGBEE_CONFIG" << EOF
  - repeater$i:
      serial:
        adapter: ezsp
        port: tcp://${address}:${port}
      advanced:
        channel: 15
EOF
        done
    fi

    log "Setting correct permissions for configuration files..."
    chown -R $SERVICE_USER:$SERVICE_USER "$ZIGBEE_DIR/data"
    find "$ZIGBEE_DIR/data" -type f -exec chmod 664 {} \;
    find "$ZIGBEE_DIR/data" -type d -exec chmod 775 {} \;
    log "Zigbee network configuration completed"
}

setup_systemd_service() {
    systemctl daemon-reload
    systemctl enable zigbee2mqtt.service
    systemctl restart zigbee2mqtt.service
}

install_zigbee() {
    log "Starting Zigbee coordinator installation..."
    
    install_dependencies
    install_zigbee2mqtt
    
    
    log "Zigbee coordinator installation completed"
}

# Can be run independently
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    install_zigbee
fi