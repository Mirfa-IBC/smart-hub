#!/bin/bash
set -e

INSTALL_DIR="/opt/smart-hub"
LOG_DIR="/var/log/smart-hub"
SERVICE_USER="mirfa"

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

    # Create service user if it doesn't exist with home directory in /opt/smarthub
    if ! id -u $SERVICE_USER &>/dev/null; then
        useradd -r -m -d "$INSTALL_DIR" -s /bin/bash $SERVICE_USER
        # Set up git config for the user
        runuser -l $SERVICE_USER -c 'git config --global user.email "smarthub@localhost"'
        runuser -l $SERVICE_USER -c 'git config --global user.name "Smart Hub System"'
    fi

    # Ensure proper home directory and shell even if user exists
    usermod -d "$INSTALL_DIR" -s /bin/bash $SERVICE_USER 2>/dev/null || true
    
    # Add user to groups
    usermod -a -G bluetooth,dialout $SERVICE_USER

    # Ensure home directory has correct permissions
    mkdir -p "$INSTALL_DIR"
    chown -R $SERVICE_USER:$SERVICE_USER "$INSTALL_DIR"
    chmod 750 "$INSTALL_DIR"
}

setup_directories() {
    log "Creating directories..."
    
    # Create main directories with proper permissions
    ensure_directory_permissions "$INSTALL_DIR" "755"
    ensure_directory_permissions "$LOG_DIR" "755"
    
    # Create and set permissions for service directories
    for dir in "services" "config" "data"; do
        ensure_directory_permissions "$INSTALL_DIR/$dir" "755"
    done
    
    # Create and set permissions for service-specific directories
    for service in "ttlock" "dahua" "update" "zigbee2mqtt" "stt-server"; do
        ensure_directory_permissions "$INSTALL_DIR/services/$service" "755"
        ensure_directory_permissions "$INSTALL_DIR/config/$service" "755"
    done

    ensure_directory_permissions "$INSTALL_DIR/services/stt-server/models" "755"
    ensure_directory_permissions "$INSTALL_DIR/services/stt-server/models/torch_cache" "755"
    ensure_directory_permissions "$INSTALL_DIR/services/stt-server/audio_files" "755"

    touch "$LOG_DIR/update.log" "$LOG_DIR/update.error.log"
    chown $SERVICE_USER:$SERVICE_USER "$LOG_DIR/update.log" "$LOG_DIR/update.error.log"
    chmod 664 "$LOG_DIR/update.log" "$LOG_DIR/update.error.log"
    # Special cases for data directories that need write permissions
    ensure_directory_permissions "$INSTALL_DIR/zigbee" "755"
    ensure_directory_permissions "$INSTALL_DIR/zigbee/data" "775"
    ensure_directory_permissions "$INSTALL_DIR/.npm" "775"  # For npm cache
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
        /opt/smart-hub/venv/bin/pip3 install torch torchaudio --index-url https://download.pytorch.org/whl/cu126 --no-cache-dir
        # Set ownership
        chown -R $SERVICE_USER:$SERVICE_USER /opt/smart-hub/venv
        chmod -R 777 /opt/smart-hub/venv
    fi
    log "Finshed Installing dependencies..."
}
install_python_packages(){
    log "Finshed install_python_packages ..."
    source /opt/smart-hub/venv/bin/activate
    /opt/smart-hub/venv/bin/pip install -r /opt/smart-hub/requirements.txt --no-cache-dir
    log "Finshed install_python_packages ..."
    
}


install_services() {
    log "Installing services..."
    
    # Define source and destination directories
    SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
    SOURCE_DIR="$SCRIPT_DIR/../.."
    DEST_DIR="/opt/smart-hub"
    
    log "Source directory: $SOURCE_DIR"
    log "Destination directory: $DEST_DIR"

    # Create destination directory if it doesn't exist
    mkdir -p "$DEST_DIR"

    # Copy all files and directories from source to destination
    log "Copying all files from $SOURCE_DIR to $DEST_DIR..."
    cp -r "$SOURCE_DIR/"* "$DEST_DIR/"

    # Set correct permissions
    log "Setting permissions..."
    chown -R $SERVICE_USER:$SERVICE_USER "$DEST_DIR"
    chmod -R 755 "$DEST_DIR"
    
    log "Service installation complete."
}

install_custom_service(){
        # Install systemd services
    log "Installing systemd services..."
    
    SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
    SOURCE_DIR="$SCRIPT_DIR/../../services"
    DEST_DIR="/opt/smart-hub/services"
    # Remove old service files if they exist
    for service in ttlock dahua zigbee update "stt-server"; do
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
    for service in ttlock dahua zigbee2mqtt update "stt-server" ; do
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
    install_python_packages
    install_services
    verify_installation
    
    log "Services installed successfully!"
}



if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    # Component-specific direct execution logic here
    main
    
fi