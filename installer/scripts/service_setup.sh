#!/bin/bash
set -e

INSTALL_DIR="/opt/smart-hub"
LOG_DIR="/var/log/smart-hub"
SERVICE_USER="smarthub"

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

setup_service_user() {
    log "Creating service user and groups..."
    
    # Create bluetooth group if it doesn't exist
    getent group bluetooth || groupadd bluetooth

    # Create dialout group if it doesn't exist
    getent group dialout || groupadd dialout

    # Create service user if it doesn't exist
    id -u $SERVICE_USER &>/dev/null || useradd -r -s /bin/false $SERVICE_USER

    # Install bluetooth if not present
    if ! dpkg -l | grep -q bluez; then
        apt-get update
        apt-get install -y bluetooth bluez
    fi

    # Add user to groups
    usermod -a -G bluetooth,dialout $SERVICE_USER
}

setup_directories() {
    log "Creating directories..."
    
    # Create main directories
    mkdir -p $INSTALL_DIR/{services,config,data}
    mkdir -p $LOG_DIR

    # Create service-specific directories
    mkdir -p $INSTALL_DIR/services/{ttlock,dahua,update}
    mkdir -p $INSTALL_DIR/config/{ttlock,dahua,update}
    
    # Set permissions
    chown -R $SERVICE_USER:$SERVICE_USER $INSTALL_DIR
    chown -R $SERVICE_USER:$SERVICE_USER $LOG_DIR
    chmod 755 $INSTALL_DIR
    chmod 755 $LOG_DIR
}

install_system_dependencies() {
    log "Installing system dependencies..."
    
    # Update package list
    apt-get update
    
    # Install system packages
    apt-get install -y \
        python3 \
        python3-full \
        python3-venv \
        bluetooth \
        bluez \
        mosquitto \
        git \
        python3-bleak \
        python3-paho-mqtt \
        python3-aiohttp \
        python3-cryptography \
        python3-yaml

    # Create virtual environment
    if [ ! -d "/opt/smart-hub/venv" ]; then
        log "Creating virtual environment..."
        python3 -m venv /opt/smart-hub/venv
        
        # Activate virtual environment and install packages
        source /opt/smart-hub/venv/bin/activate
        /opt/smart-hub/venv/bin/pip install \
            bleak \
            paho-mqtt \
            aiohttp \
            pycryptodome \
            pyyaml \
            zeroconf

        # Set ownership
        chown -R $SERVICE_USER:$SERVICE_USER /opt/smart-hub/venv
    fi
    log "Finshed Installing dependencies..."
}


install_services() {
    log "Installing services..."
    
    # Define source and destination directories
    SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
    SOURCE_DIR="$SCRIPT_DIR/../../services"
    DEST_DIR="/opt/smart-hub/services"

    # Create destination directories if they don't exist
    mkdir -p "$DEST_DIR"/{dahua,ttlock,zigbee2mqtt,update}

    # Copy service files
    log "Copying service files..."
    
    log "Copying service files... $SOURCE_DIR/dahua/*.py $DEST_DIR/dahua/"
    # Copy Dahua service
    cp "$SOURCE_DIR/dahua/"*.py "$DEST_DIR/dahua/"
    cp "$SOURCE_DIR/dahua/config.json" "$DEST_DIR/dahua/"

    # Copy TTLock service
    cp "$SOURCE_DIR/ttlock/"*.py "$DEST_DIR/ttlock/"
    cp "$SOURCE_DIR/ttlock/config.json" "$DEST_DIR/ttlock/"

    # Copy Zigbee2MQTT config
    cp "$SOURCE_DIR/zigbee2mqtt/config.yaml" "$DEST_DIR/zigbee2mqtt/"
    cp "$SOURCE_DIR/zigbee2mqtt/discover_slzb06.py" "$DEST_DIR/zigbee2mqtt/"
    
    log "Copying service files... $SOURCE_DIR/update/service.py $DEST_DIR/update/"
    # Copy update config
    cp "$SOURCE_DIR/update/config.yaml" "$DEST_DIR/update/"
    cp "$SOURCE_DIR/update/service.py" "$DEST_DIR/update/"


    # Set correct permissions
    chown -R $SERVICE_USER:$SERVICE_USER "$DEST_DIR"
    chmod -R 755 "$DEST_DIR"
    
    # Install systemd services
    log "Installing systemd services..."
    
    # Remove old service files if they exist
    for service in ttlock dahua zigbee update; do
        if [ -f "/etc/systemd/system/$service.service" ]; then
            systemctl stop $service.service || true
            systemctl disable $service.service || true
            systemctl unmask $service.service || true
            rm -f "/etc/systemd/system/$service.service"
        fi
    done

    # Copy new service files
    cp "$SCRIPT_DIR/../systemd/"*.service /etc/systemd/system/
    
    # Reload systemd
    systemctl daemon-reload
    
    # Enable and start services
    for service in ttlock dahua zigbee2mqtt update; do
        log "Enabling and starting $service..."
        systemctl enable $service.service
        systemctl start $service.service
    done
}

verify_installation() {
    log "Verifying installation..."
    
    # Check if services are running
    services=("ttlock" "dahua" "update")
    for service in "${services[@]}"; do
        if ! systemctl is-active --quiet $service; then
            error "Service $service failed to start"
        fi
    done
}

set_up_system() {
    log "Starting service installation..."
    
    setup_service_user
    setup_directories
    install_system_dependencies
    install_services
    verify_installation
    
    log "Services installed successfully!"
}



if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    # Component-specific direct execution logic here
    main
    
fi