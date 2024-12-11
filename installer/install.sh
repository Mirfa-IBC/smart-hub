#!/bin/bash
set -e

# Get the directory where the script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

# Source other scripts with correct paths
source "$SCRIPT_DIR/scripts/install.sh"
source "$SCRIPT_DIR/scripts/install_zigbee.sh"

# Main installation steps
check_prerequisites
setup_system
install_services
configure_services
generate_admin_credentials
configure_zigbee_network

echo "Installation completed successfully!"