#!/bin/bash
set -e

# Source utility functions
source scripts/install.sh
source scripts/zigbee_setup.sh   # Add this line

# Main installation steps
check_prerequisites
setup_system
install_services
configure_services
generate_admin_credentials
configure_zigbee_network    # Add this line

echo "Installation completed successfully!"