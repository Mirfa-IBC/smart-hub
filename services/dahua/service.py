#!/usr/bin/env python3
import asyncio
import json
import logging
from datetime import datetime
import aiohttp
import base64
import os
import hashlib
import paho.mqtt.client as mqtt
from typing import Dict, Optional
from .discovery import DahuaDiscovery

class DahuaService:
    def __init__(self):
        self.config_file = '/opt/smart-hub/config/dahua/config.json'
        self.logger = self._setup_logging()
        self.mqtt_client = None
        self.session = None
        self.discovery = DahuaDiscovery()
        self.config = self._load_config()
        self.device_states = {}

    def _setup_logging(self):
        logger = logging.getLogger('dahua_service')
        logger.setLevel(logging.INFO)
        handler = logging.FileHandler('/var/log/smart-hub/dahua.log')
        handler.setFormatter(logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s'
        ))
        logger.addHandler(handler)
        return logger

    def _load_config(self) -> Dict:
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r') as f:
                    return json.load(f)
            return {
                'devices': [],
                'mqtt': {
                    'host': 'localhost',
                    'port': 1883,
                    'topic_prefix': 'dahua'
                }
            }
        except Exception as e:
            self.logger.error(f"Failed to load config: {e}")
            return {}

    def _save_config(self):
        """Save current configuration"""
        try:
            os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
            with open(self.config_file, 'w') as f:
                json.dump(self.config, f, indent=2)
        except Exception as e:
            self.logger.error(f"Failed to save config: {e}")

    def _setup_mqtt(self):
        self.mqtt_client = mqtt.Client()
        self.mqtt_client.on_connect = self._on_mqtt_connect
        self.mqtt_client.on_message = self._on_mqtt_message
        
        try:
            mqtt_config = self.config.get('mqtt', {})
            self.mqtt_client.connect(
                mqtt_config.get('host', 'localhost'),
                mqtt_config.get('port', 1883),
                60
            )
        except Exception as e:
            self.logger.error(f"Failed to connect to MQTT: {e}")

    def _on_mqtt_connect(self, client, userdata, flags, rc):
        self.logger.info("Connected to MQTT broker")
        client.subscribe("dahua/+/command")

    def _on_mqtt_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode())
            self.logger.info(f"Received message: {payload}")
            asyncio.create_task(self._handle_command(msg.topic, payload))
        except Exception as e:
            self.logger.error(f"Error processing message: {e}")

    async def _handle_command(self, topic: str, payload: Dict):
        """Handle commands received via MQTT"""
        try:
            device_id = topic.split('/')[1]
            command = payload.get('command')
            
            if command == 'snapshot':
                await self._take_snapshot(device_id)
            elif command == 'record':
                duration = payload.get('duration', 30)
                await self._record_video(device_id, duration)
            else:
                self.logger.warning(f"Unknown command: {command}")
        except Exception as e:
            self.logger.error(f"Error handling command: {e}")

    def _get_device_config(self, device_id: str) -> Optional[Dict]:
        """Get device configuration"""
        for device in self.config.get('devices', []):
            if device.get('id') == device_id:
                return device
        return None

    async def discover_and_update_devices(self):
        """Discover and update device configurations"""
        try:
            discovered_devices = await self.discovery.discover_devices()
            config_changed = False

            # Update existing devices and add new ones
            current_devices = self.config.get('devices', [])
            current_ips = {d['ip'] for d in current_devices}

            for device in discovered_devices:
                if device['ip'] not in current_ips:
                    # New device found
                    device_id = f"doorbell_{len(current_devices) + 1}"
                    device.update({
                        'id': device_id,
                        'name': f"Doorbell {len(current_devices) + 1}"
                    })
                    current_devices.append(device)
                    config_changed = True

            # Update configuration if changed
            if config_changed:
                self.config['devices'] = current_devices
                self._save_config()
                self.logger.info("Device configuration updated")

            # Check for devices needing password change
            for device in current_devices:
                if device.get('needs_password_change', False):
                    await self._secure_device(device)

        except Exception as e:
            self.logger.error(f"Error in device discovery: {e}")

    async def _secure_device(self, device: Dict):
        """Change default password on device"""
        try:
            # Generate secure password
            new_password = self._generate_secure_password()
            
            # Change password via device API
            async with aiohttp.ClientSession() as session:
                url = f"http://{device['ip']}/cgi-bin/userManager"
                auth = aiohttp.BasicAuth(device['username'], device['password'])
                
                params = {
                    'action': 'modifyPassword',
                    'userName': device['username'],
                    'oldPassword': device['password'],
                    'newPassword': new_password
                }
                
                async with session.get(url, auth=auth, params=params) as response:
                    if response.status == 200:
                        # Update configuration with new password
                        device['password'] = new_password
                        device['needs_password_change'] = False
                        self._save_config()
                        self.logger.info(f"Password updated for device {device['ip']}")

        except Exception as e:
            self.logger.error(f"Failed to secure device {device['ip']}: {e}")

    def _generate_secure_password(self) -> str:
        """Generate a secure random password"""
        return hashlib.sha256(os.urandom(32)).hexdigest()[:16]

    async def monitor_events(s