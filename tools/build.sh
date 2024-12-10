#!/bin/bash
set -e

VERSION=${1:-"1.0.0"}
PACKAGE_NAME="smart-hub-installer-${VERSION}.tar.gz"

# Create package directory
rm -rf build
mkdir -p build/smart-hub-installer

# Copy files
cp -r ../installer/* build/smart-hub-installer/
cp -r ../services build/smart-hub-installer/

# Create package
cd build
tar czf "${PACKAGE_NAME}" smart-hub-installer

echo "Package created: ${PACKAGE_NAME}"
