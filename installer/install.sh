#!/bin/bash
set -e

# Get the directory where the script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

# Source common definitions first
source "$SCRIPT_DIR/scripts/common.sh"

# Source other scripts
source "$SCRIPT_DIR/scripts/install.sh"
source "$SCRIPT_DIR/scripts/service_setup.sh"
source "$SCRIPT_DIR/scripts/install_zigbee.sh"
source "$SCRIPT_DIR/scripts/update_setup.sh"

# Main installation steps
check_prerequisites
setup_system
setup_service_user
setup_directories
install_services
install_system_dependencies
install_custom_packages
install_python_packages
install_custom_service
install_zigbee
configure_zigbee_network
setup_systemd_service

log "Installation completed successfully!"