#!/usr/bin/env python3
import asyncio
import aiohttp
import socket
import logging
from typing import List, Dict
import xml.etree.ElementTree as ET

class DahuaDiscovery:
    def __init__(self):
        self.logger = logging.getLogger('dahua_discovery')
        self.default_creds = {
            'username': 'admin',
            'password': 'admin'
        }

    async def discover_devices(self) -> List[Dict]:
        """Discover Dahua devices on the network"""
        devices = []
        try:
            # Use multicast discovery
            MCAST_GRP = '239.255.255.250'
            MCAST_PORT = 37810

            # Create discovery message
            search_msg = (
                'M-SEARCH * HTTP/1.1\r\n'
                'HOST: 239.255.255.250:37810\r\n'
                'ST: dh.device\r\n'
                'MX: 3\r\n'
                'MAN: "ssdp:discover"\r\n'
                '\r\n'
            )

            # Send discovery packet
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            sock.settimeout(5)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.sendto(search_msg.encode(), (MCAST_GRP, MCAST_PORT))

            # Collect responses
            while True:
                try:
                    data, addr = sock.recvfrom(1024)
                    device = await self._verify_device(addr[0])
                    if device:
                        devices.append(device)
                except socket.timeout:
                    break

        except Exception as e:
            self.logger.error(f"Discovery error: {e}")

        return devices

    async def _verify_device(self, ip: str) -> Dict:
        """Verify device and get its details"""
        try:
            async with aiohttp.ClientSession() as session:
                # Try with default credentials first
                device_info = await self._get_device_info(session, ip, self.default_creds)
                
                if device_info:
                    return {
                        'ip': ip,
                        'model': device_info.get('model', 'Unknown'),
                        'serial': device_info.get('serial', 'Unknown'),
                        'needs_password_change': True,
                        'username': self.default_creds['username'],
                        'password': self.default_creds['password']
                    }
        except Exception as e:
            self.logger.error(f"Device verification error for {ip}: {e}")
        return None

    async def _get_device_info(self, session: aiohttp.ClientSession, ip: str, creds: Dict) -> Dict:
        """Get device information using device API"""
        try:
            url = f"http://{ip}/cgi-bin/deviceInfo"
            auth = aiohttp.BasicAuth(creds['username'], creds['password'])
            
            async with session.get(url, auth=auth, timeout=5) as response:
                if response.status == 200:
                    text = await response.text()
                    return self._parse_device_info(text)
        except Exception as e:
            self.logger.debug(f"Could not get device info from {ip}: {e}")
        return None

    def _parse_device_info(self, info_text: str) -> Dict:
        """Parse device information response"""
        info = {}
        try:
            for line in info_text.splitlines():
                if '=' in line:
                    key, value = line.split('=', 1)
                    info[key.strip()] = value.strip()
        except Exception as e:
            self.logger.error(f"Error parsing device info: {e}")
        return info