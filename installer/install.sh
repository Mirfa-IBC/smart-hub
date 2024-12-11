#!/bin/bash
set -e

log() {
    echo -e "${GREEN}[$(date '+%Y-%m-%d %H:%M:%S')] $1${NC}"
}
# Get the directory where the script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

# Source other scripts with correct paths
log "importing $SCRIPT_DIR/scripts/install.sh"
source "$SCRIPT_DIR/scripts/install.sh"
source "$SCRIPT_DIR/scripts/install_zigbee.sh"
source "$SCRIPT_DIR/scripts/service_setup.sh"
log "importing $SCRIPT_DIR/update_setup.sh"
source "$SCRIPT_DIR/update_setup.sh"

# Main installation steps
check_prerequisites
setup_system
install_services
configure_services
generate_admin_credentials
configure_zigbee_network

echo "Installation completed successfully!"