#!/usr/bin/env python3
import asyncio
import json
import logging
from datetime import datetime
import paho.mqtt.client as mqtt
import aiohttp
import base64

class DahuaService:
    def __init__(self):
        self.config_file = '/opt/smart-hub/config/dahua/config.json'
        self.logger = self._setup_logging()
        self.mqtt_client = None
        self.config = self._load_config()
        self.session = None
        
    def _setup_logging(self):
        logger = logging.getLogger('dahua_service')
        logger.setLevel(logging.INFO)
        handler = logging.FileHandler('/var/log/smart-hub/dahua.log')
        handler.setFormatter(logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s'
        ))
        logger.addHandler(handler)
        return logger

    def _load_config(self):
        try:
            with open(self.config_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            self.logger.error(f"Failed to load config: {e}")
            return {}

    def _setup_mqtt(self):
        self.mqtt_client = mqtt.Client()
        self.mqtt_client.on_connect = self._on_mqtt_connect
        self.mqtt_client.on_message = self._on_mqtt_message
        
        try:
            self.mqtt_client.connect("localhost", 1883, 60)
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

    async def _handle_command(self, topic, payload):
        """Handle commands received via MQTT"""
        try:
            device_id = topic.split('/')[1]
            command = payload.get('command')
            
            if command == 'snapshot':
                await self._take_snapshot(device_id)
            elif command == 'record':
                duration = payload.get('duration', 30)  # default 30 seconds
                await self._record_video(device_id, duration)
            else:
                self.logger.warning(f"Unknown command: {command}")
        except Exception as e:
            self.logger.error(f"Error handling command: {e}")

    async def _take_snapshot(self, device_id):
        """Take a snapshot from the camera"""
        device = self._get_device_config(device_id)
        if not device:
            return

        try:
            url = f"http://{device['ip']}/cgi-bin/snapshot.cgi"
            auth = base64.b64encode(
                f"{device['username']}:{device['password']}".encode()
            ).decode()

            async with self.session.get(
                url, 
                headers={"Authorization": f"Basic {auth}"}
            ) as response:
                if response.status == 200:
                    image_data = await response.read()
                    self._publish_snapshot(device_id, image_data)
        except Exception as e:
            self.logger.error(f"Error taking snapshot: {e}")

    def _publish_snapshot(self, device_id, image_data):
        """Publish snapshot to MQTT"""
        topic = f"dahua/{device_id}/snapshot"
        self.mqtt_client.publish(topic, image_data)

    def _get_device_config(self, device_id):
        """Get device configuration"""
        for device in self.config.get('devices', []):
            if device.get('id') == device_id:
                return device
        return None

    async def monitor_events(self):
        """Monitor doorbell events"""
        try:
            for device in self.config.get('devices', []):
                url = f"http://{device['ip']}/cgi-bin/eventManager.cgi?action=attach"
                auth = base64.b64encode(
                    f"{device['username']}:{device['password']}".encode()
                ).decode()

                async with self.session.get(
                    url,
                    headers={"Authorization": f"Basic {auth}"},
                    timeout=None
                ) as response:
                    async for line in response.content:
                        if line:
                            await self._handle_event(device['id'], line.decode())
        except Exception as e:
            self.logger.error(f"Error monitoring events: {e}")
            await asyncio.sleep(5)  # Retry delay

    async def _handle_event(self, device_id, event_data):
        """Handle events from the device"""
        try:
            # Parse event data
            event = {}
            for line in event_data.split('\r\n'):
                if ':' in line:
                    key, value = line.split(':', 1)
                    event[key.strip()] = value.strip()

            if 'Code' in event:
                topic = f"dahua/{device_id}/event"
                self.mqtt_client.publish(topic, json.dumps({
                    'timestamp': datetime.now().isoformat(),
                    'type': event.get('Code'),
                    'data': event
                }))
        except Exception as e:
            self.logger.error(f"Error handling event: {e}")

    async def run(self):
        """Main service loop"""
        self.logger.info("Starting Dahua service")
        self._setup_mqtt()
        self.mqtt_client.loop_start()

        async with aiohttp.ClientSession() as session:
            self.session = session
            while True:
                try:
                    await self.monitor_events()
                except Exception as e:
                    self.logger.error(f"Error in main loop: {e}")
                    await asyncio.sleep(5)

if __name__ == "__main__":
    service = DahuaService()
    asyncio.run(service.run())