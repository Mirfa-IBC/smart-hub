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


configure_zigbee_network() {
    log "Configuring Zigbee network..."
    
    # Run discovery script
    devices=$(python3 $INSTALL_DIR/services/zigbee2mqtt/discover_slzb06.py)
    if [ $? -ne 0 ]; then
        error "Failed to discover SLZB-06 devices"
    fi

    # Get number of devices
    device_count=$(echo $devices | jq length)
    
    if [ $device_count -eq 0 ]; then
        error "No SLZB-06 devices found"
    fi

    # Configure primary coordinator
    primary_address=$(echo $devices | jq -r '.[0].address')
    primary_port=$(echo $devices | jq -r '.[0].port')
    
    # Create base config
    cat > $ZIGBEE_CONFIG << EOF
mqtt:
  base_topic: zigbee2mqtt
  server: mqtt://localhost:1883

serial:
  adapter: ezsp
  port: tcp://${primary_address}:${primary_port}

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

availability:
  active: true
  timeout: 10
EOF

    # Add repeaters if more devices exist
    if [ $device_count -gt 1 ]; then
        log "Configuring ${device_count} additional repeaters..."
        
        # Add repeater section to config
        echo "external_converters:" >> $ZIGBEE_CONFIG
        
        # Start from second device (index 1)
        for i in $(seq 1 $((device_count-1))); do
            address=$(echo $devices | jq -r ".[$i].address")
            port=$(echo $devices | jq -r ".[$i].port")
            
            cat >> $ZIGBEE_CONFIG << EOF
  - repeater$i:
      serial:
        adapter: ezsp
        port: tcp://${address}:${port}
      advanced:
        channel: 15
EOF
        done
    fi

    log "Zigbee network configuration completed"
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