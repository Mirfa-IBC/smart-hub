#!/usr/bin/env python3
import socket
import time
import json
from zeroconf import ServiceBrowser, Zeroconf

class SLZB06Listener:
    def __init__(self):
        self.devices = []

    def remove_service(self, zeroconf, type, name):
        pass

    def update_service(self, zeroconf, type, name):
        # Add empty update method to handle future warning
        pass

    def add_service(self, zeroconf, type, name):
        try:
            info = zeroconf.get_service_info(type, name)
            if info and info.addresses:
                address = socket.inet_ntoa(info.addresses[0])
                port = info.port
                device = {
                    'name': name.split('.')[0],
                    'address': address,
                    'port': port
                }
                if device not in self.devices:
                    self.devices.append(device)
        except Exception as e:
            print(f"Error adding service: {e}", file=sys.stderr)

def discover_slzb06():
    zeroconf = Zeroconf()
    listener = SLZB06Listener()
    
    # Try multiple service types that SLZB-06 might use
    service_types = [
        "_ezsp._tcp.local.",
        "_zigbee._tcp.local.",
        "_slzb-06._tcp.local."
    ]
    
    browsers = [ServiceBrowser(zeroconf, service_type, listener) 
               for service_type in service_types]
    
    # Wait longer for discovery
    time.sleep(15)
    
    zeroconf.close()
    return listener.devices

if __name__ == "__main__":
    try:
        devices = discover_slzb06()
        if not devices:
            print("No SLZB-06 devices found", file=sys.stderr)
        print(json.dumps(devices, indent=2))
    except Exception as e:
        print(f"Discovery error: {e}", file=sys.stderr)
        print(json.dumps([], indent=2))