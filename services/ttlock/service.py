#!/usr/bin/env python3
import asyncio
import json
import logging
from datetime import datetime
import paho.mqtt.client as mqtt
from typing import Dict, List
from bleak import BleakScanner
from ttlock_client import TTLockClient

class TTLockService:
    def __init__(self):
        self.config_file = '/opt/smart-hub/config/ttlock/config.json'
        self.logger = self._setup_logging()
        self.mqtt_client = None
        self.config = self._load_config()
        self.locks: Dict[str, TTLockClient] = {}

    def _setup_logging(self):
        logger = logging.getLogger('ttlock_service')
        logger.setLevel(logging.INFO)
        handler = logging.FileHandler('/var/log/smart-hub/ttlock.log')
        handler.setFormatter(logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s'
        ))
        logger.addHandler(handler)
        return logger

    def _load_config(self) -> Dict:
        try:
            with open(self.config_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            self.logger.error(f"Failed to load config: {e}")
            return {
                'locks': [],
                'mqtt': {
                    'host': 'localhost',
                    'port': 1883,
                    'topic_prefix': 'ttlock'
                }
            }

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
        client.subscribe("ttlock/+/command")

    def _on_mqtt_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode())
            self.logger.info(f"Received message: {payload}")
            asyncio.create_task(self._handle_command(msg.topic, payload))
        except Exception as e:
            self.logger.error(f"Error processing message: {e}")

    async def _handle_command(self, topic: str, payload: Dict):
        """Handle MQTT commands"""
        try:
            lock_id = topic.split('/')[1]
            command = payload.get('command')
            
            if lock_id not in self.locks:
                self.logger.error(f"Unknown lock: {lock_id}")
                return

            lock = self.locks[lock_id]
            
            if command == 'unlock':
                result = await lock.unlock()
            elif command == 'lock':
                result = await lock.lock()
            elif command == 'status':
                result = await lock.get_battery_level()
            else:
                self.logger.warning(f"Unknown command: {command}")
                return

            # Publish result
            self.mqtt_client.publish(
                f"ttlock/{lock_id}/status",
                json.dumps(result)
            )

        except Exception as e:
            self.logger.error(f"Error handling command: {e}")

    async def scan_for_locks(self):
        """Scan for TTLock devices"""
        try:
            scanner = BleakScanner()
            devices = await scanner.discover()
            
            for device in devices:
                if self._is_ttlock_device(device):
                    await self._connect_lock(device)

        except Exception as e:
            self.logger.error(f"Scan error: {e}")

    def _is_ttlock_device(self, device) -> bool:
        """Check if device is a TTLock"""
        if not device.name:
            return False
        return device.name.startswith("TTLock")

    async def _connect_lock(self, device):
        """Connect to a TTLock device"""
        try:
            # Check if lock is in config
            lock_config = self._find_lock_config(device.address)
            if not lock_config:
                self.logger.info(f"New lock found: {device.address}")
                return

            # Create client
            client = TTLockClient()
            if await client.connect(device.address, lock_config):
                self.locks[lock_config['id']] = client
                self.logger.info(f"Connected to lock: {lock_config['id']}")

        except Exception as e:
            self.logger.error(f"Connection error: {e}")

    def _find_lock_config(self, address: str) -> Dict:
        """Find lock configuration by address"""
        for lock in self.config.get('locks', []):
            if lock.get('address') == address:
                return lock
        return None

    async def run(self):
        """Main service loop"""
        self.logger.info("Starting TTLock service")
        self._setup_mqtt()
        self.mqtt_client.loop_start()

        while True:
            try:
                await self.scan_for_locks()
                await asyncio.sleep(30)  # Scan every 30 seconds
                
            except Exception as e:
                self.logger.error(f"Error in main loop: {e}")
                await asyncio.sleep(5)

if __name__ == "__main__":
    service = TTLockService()
    asyncio.run(service.run())