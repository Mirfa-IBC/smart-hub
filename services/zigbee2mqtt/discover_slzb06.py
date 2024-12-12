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

    def add_service(self, zeroconf, type, name):
        try:
            info = zeroconf.get_service_info(type, name)
            if info and info.addresses:
                address = socket.inet_ntoa(info.addresses[0])
                port = info.port
                self.devices.append({
                    'name': name.split('.')[0],
                    'address': address,
                    'port': port
                })
        except Exception as e:
            pass  # Skip problematic services

def discover_slzb06():
    zeroconf = Zeroconf()
    listener = SLZB06Listener()
    # Changed to correct service type for EZSP devices
    browser = ServiceBrowser(zeroconf, "_ezsp._tcp.local.", listener)
    
    # Wait for discovery
    time.sleep(10)  # Reduced wait time to 10 seconds
    
    zeroconf.close()
    return listener.devices

if __name__ == "__main__":
    try:
        devices = discover_slzb06()
        print(json.dumps(devices, indent=2))
    except Exception as e:
        print(json.dumps([], indent=2))  # Return empty list on error