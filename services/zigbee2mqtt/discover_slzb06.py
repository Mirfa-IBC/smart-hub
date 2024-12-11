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
        info = zeroconf.get_service_info(type, name)
        if info:
            address = socket.inet_ntoa(info.addresses[0])
            port = info.port
            self.devices.append({
                'name': name.replace('._ezsp._tcp.local.', ''),
                'address': address,
                'port': port
            })

def discover_slzb06():
    zeroconf = Zeroconf()
    listener = SLZB06Listener()
    browser = ServiceBrowser(zeroconf, "_services._dns-sd._udp.local.", listener)
    
    # Wait for discovery
    time.sleep(60)
    
    zeroconf.close()
    return listener.devices

if __name__ == "__main__":
    devices = discover_slzb06()
    print(json.dumps(devices, indent=2))