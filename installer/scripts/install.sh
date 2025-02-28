# /installer/scripts/install.sh
#!/bin/bash
set -e

INSTALL_DIR="/opt/smart-hub"
CONFIG_DIR="$INSTALL_DIR/config"
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

# Check prerequisites
check_prerequisites() {
    log "Checking prerequisites..."
    
    # Check if running as root
    if [ "$EUID" -ne 0 ]; then 
        error "Please run as root"
    fi

    # Check architecture - allow both x86_64 and ARM
    ARCH=$(uname -m)
    if [[ "$ARCH" != "aarch64" && "$ARCH" != "armv7l" && "$ARCH" != "x86_64" ]]; then
        error "Unsupported architecture: $ARCH"
    fi

    # Check operating system
    if [ ! -f /etc/os-release ]; then
        error "Unsupported operating system"
    fi
    source /etc/os-release
    if [ "$ID" != "ubuntu" ]; then
        error "This script requires Ubuntu"
    fi
}

setup_system() {
    log "Setting up system..."
    
    # Create service user
    useradd -r -s /bin/false $SERVICE_USER || true
    
    # Create directories
    mkdir -p $INSTALL_DIR/{config,services,data}
    mkdir -p $LOG_DIR
    
    # Set permissions
    chown -R $SERVICE_USER:$SERVICE_USER $INSTALL_DIR
    chown -R $SERVICE_USER:$SERVICE_USER $LOG_DIR
}
