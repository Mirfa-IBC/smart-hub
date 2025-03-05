import asyncio
import logging
import socket
import time
import uuid
import os
import backoff
import queue
from zeroconf import Zeroconf, ServiceBrowser, ServiceListener
from aioesphomeapi import APIClient
from aioesphomeapi.model import (
    VoiceAssistantAudioData, 
    VoiceAssistantAudioSettings, 
    VoiceAssistantEventType
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Default configuration
DEFAULT_PORT = 6053
DEFAULT_UDP_PORT = 12345
DEFAULT_ENCRYPTION_KEY = "B/ZTOpKW5IyL0jUv9InGeNOpVPdj4+oDO48fmwrh5Ak="

class ESP32DiscoveryListener(ServiceListener):
    def __init__(self):
        self.found_devices = {}
        # Use a standard threading Queue instead of asyncio.Queue
        self._device_queue = queue.Queue()
    
    def update_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        info = zc.get_service_info(type_, name)
        if info and info.properties and info.addresses:
            mac = info.properties.get(b'mac', b'').decode('utf-8')
            ip = socket.inet_ntoa(info.addresses[0])
            hostname = info.server.lower()
            port = info.port
            
            if "esp32s3" in hostname:
                logger.info(f"Updated ESP32-S3 at {ip}:{port}")
                
                # Create device info dictionary
                device_info = {
                    'mac': mac,
                    'ip': ip,
                    'port': port,
                    'hostname': hostname,
                    'properties': {
                        k.decode('utf-8'): v.decode('utf-8') 
                        for k, v in info.properties.items()
                    }
                }
                
                self.found_devices[mac] = device_info
                # Add to thread-safe queue
                self._device_queue.put(device_info)
    
    def remove_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        info = zc.get_service_info(type_, name)
        if info and info.properties:
            mac = info.properties.get(b'mac', b'').decode('utf-8')
            if mac in self.found_devices:
                logger.info(f"Device removed: {mac}")
                del self.found_devices[mac]
    
    def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        info = zc.get_service_info(type_, name)
        if info and info.properties and info.addresses:
            mac = info.properties.get(b'mac', b'').decode('utf-8')
            ip = socket.inet_ntoa(info.addresses[0])
            hostname = info.server.lower()
            port = info.port
            
            if "esp32s3" in hostname:
                logger.info(f"Found ESP32-S3 at {ip}:{port}")
                
                # Create device info dictionary
                device_info = {
                    'mac': mac,
                    'ip': ip,
                    'port': port,
                    'hostname': hostname,
                    'properties': {
                        k.decode('utf-8'): v.decode('utf-8') 
                        for k, v in info.properties.items()
                    }
                }
                
                self.found_devices[mac] = device_info
                # Add to thread-safe queue
                self._device_queue.put(device_info)

class VoiceAssistantClient:
    def __init__(self, host: str, encryption_key: str = None, port: int = DEFAULT_PORT, udp_port: int = DEFAULT_UDP_PORT):
        self.host = host
        self.port = port
        self.encryption_key = encryption_key
        self.client = APIClient(host, port, password="", noise_psk=encryption_key)
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 5
        self.reconnect_delay = 1
        self._request_timeout = 30
        self.udp_port = udp_port
        self._running = True

    async def handle_audio(self, data: bytes) -> None:
        pass

    async def handle_pipeline_start(
        self, 
        conversation_id: str, 
        flags: int, 
        audio_settings: VoiceAssistantAudioSettings,
        wake_word_phrase: str | None = None
    ) -> int:
        return self.udp_port  # Return the shared UDP port

    async def handle_stop(self, server_side: bool) -> None:
        logger.info(f"🛑 Voice assistant stopped streaming from {self.host} (server_side: {server_side})")
        pass

    async def handle_pipeline_finished(self):
        logger.info(f"🛑 Voice assistant finished for {self.host}")
        pass

    @backoff.on_exception(
        backoff.expo,
        Exception,
        max_tries=5,
        max_time=60
    )
    async def connect(self):
        try:
            logger.info(f"Attempting to connect to {self.host}:{self.port}...")
            await self.client.connect(login=True)
            logger.info(f"🔌 Connected to {self.host}:{self.port}")
            
            self.reconnect_attempts = 0
            self.reconnect_delay = 1
            
            device_info = await self.client.device_info()
            logger.info(f"📱 Device: {device_info.name} (ESPHome {device_info.esphome_version})")
            
            await self.subscribe_to_events()
            logger.info(f"✅ Successfully established connection to {self.host}:{self.port}")
            
        except Exception as e:
            logger.error(f"❌ Connection failed for {self.host}: {e}")
            if self.reconnect_attempts < self.max_reconnect_attempts:
                self.reconnect_attempts += 1
                self.reconnect_delay *= 2
                logger.info(f"Retrying connection to {self.host} in {self.reconnect_delay} seconds...")
                await asyncio.sleep(self.reconnect_delay)
                await self.connect()
            else:
                logger.error(f"Max reconnection attempts reached for {self.host}")
                raise RuntimeError(f"Max reconnection attempts reached for {self.host}")

    async def subscribe_to_events(self):
        try:
            logger.info(f"Subscribing to voice assistant events for {self.host}...")
            self.client.subscribe_voice_assistant(
                handle_start=self.handle_pipeline_start,
                handle_stop=self.handle_stop,
                handle_audio=self.handle_audio
            )
            logger.info(f"✅ Subscribed to voice assistant events for {self.host}")
        except Exception as e:
            logger.error(f"Failed to subscribe to events for {self.host}: {e}")
            raise

    async def run(self):
        while self._running:
            try:
                await self.connect()
                last_check_time = time.time()
                connection_ok = True
                while self._running and connection_ok:
                    # Check connection status periodically
                    current_time = time.time()
                    if current_time - last_check_time > 30:  # Check every 30 seconds
                        try:
                            # Try to get device info as a connection check
                            logger.debug(f"Performing connection check for {self.host}...")
                            try:
                                # Simply accessing an attribute that exists proves the connection
                                # works without making a network call
                                _ = self.client.address
                                logger.debug(f"Connection check passed for {self.host}")
                                last_check_time = current_time
                            except Exception:
                                # If we can't access basic attributes, consider connection broken
                                logger.warning(f"Connection check failed for {self.host} - client appears disconnected")
                                connection_ok = False
                        except Exception as e:
                            logger.warning(f"Connection check failed for {self.host}: {e}")
                            connection_ok = False
                    
                    await asyncio.sleep(1)
            except asyncio.CancelledError:
                logger.info(f"Shutting down client for {self.host}...")
                break
            except Exception as e:
                logger.error(f"Error in run loop for {self.host}: {e}")
                await asyncio.sleep(5)
            finally:
                await self.cleanup()

    async def cleanup(self):
        try:
            await self.client.disconnect()
        except Exception as e:
            logger.error(f"Error during cleanup for {self.host}: {e}")

class ESP32VoiceSystem:
    def __init__(self, encryption_key=DEFAULT_ENCRYPTION_KEY, api_port=DEFAULT_PORT, udp_port=DEFAULT_UDP_PORT):
        self.clients = {}
        self.encryption_key = encryption_key
        self.api_port = api_port
        self.udp_port = udp_port
        self.zeroconf = None
        self.browser = None
        self.discovery_listener = None
        self.discovery_task = None
        self.client_tasks = {}
        self.device_processor_task = None
        self._running = True
    
    def on_device_found(self, device_info):
        """Called when a new ESP32 device is discovered"""
        ip = device_info['ip']
        mac = device_info['mac']
        
        # Check if device already has a client or needs a new one
        if mac in self.clients:
            # Update IP if it changed
            if self.clients[mac].host != ip:
                logger.info(f"Device IP changed for {mac}: {self.clients[mac].host} -> {ip}")
                # Stop existing client
                if mac in self.client_tasks:
                    self.client_tasks[mac].cancel()
                    self.clients[mac]._running = False
                # Create new client with updated IP
                client = VoiceAssistantClient(
                    host=ip, 
                    encryption_key=self.encryption_key,
                    port=self.api_port,
                    udp_port=self.udp_port
                )
                self.clients[mac] = client
                self.client_tasks[mac] = asyncio.create_task(client.run())
                logger.info(f"Restarted voice assistant client for updated IP {ip} (MAC: {mac})")
        else:
            # Create new client for newly discovered device
            logger.info(f"Creating new voice assistant client for {ip} (MAC: {mac})")
            client = VoiceAssistantClient(
                host=ip, 
                encryption_key=self.encryption_key,
                port=self.api_port,
                udp_port=self.udp_port
            )
            self.clients[mac] = client
            
            # Start client immediately
            self.client_tasks[mac] = asyncio.create_task(client.run())
            logger.info(f"Started voice assistant client for {ip} (MAC: {mac})")
    
    async def process_discovered_devices(self):
        """Process discovered devices from the queue in the main event loop"""
        logger.info("Starting device processor task")
        while self._running:
            try:
                # Check if there are any devices in the queue
                try:
                    # Non-blocking check of queue with timeout
                    device_info = self.discovery_listener._device_queue.get(block=False)
                    
                    # Process device in main event loop
                    self.on_device_found(device_info)
                except queue.Empty:
                    # No devices in queue, wait a bit
                    await asyncio.sleep(0.1)
            except asyncio.CancelledError:
                logger.info("Device processor task cancelled")
                break
            except Exception as e:
                logger.error(f"Error processing discovered device: {e}")
                await asyncio.sleep(1)  # Wait before trying again
    
    async def start_discovery(self):
        """Start the discovery process"""
        logger.info("Starting ESP32 discovery...")
        self.zeroconf = Zeroconf()
        self.discovery_listener = ESP32DiscoveryListener()
        self.browser = ServiceBrowser(self.zeroconf, "_esphomelib._tcp.local.", self.discovery_listener)
        
        # Start the device processor task
        self.device_processor_task = asyncio.create_task(self.process_discovered_devices())
        
        # Start the discovery loop task
        self.discovery_task = asyncio.create_task(self._discovery_loop())
        logger.info("ESP32 discovery started")
    
    async def _discovery_loop(self):
        """Run discovery loop to log active devices periodically"""
        try:
            while self._running:
                await asyncio.sleep(30)  # Log device status every 30 seconds
                if self.discovery_listener.found_devices:
                    logger.info("Currently discovered devices:")
                    for mac, device_info in self.discovery_listener.found_devices.items():
                        ip = device_info['ip']
                        friendly_name = device_info['properties'].get('friendly_name', 'Unknown')
                        logger.info(f"Active device: {friendly_name} ({mac}) at {ip}")
                        
                        # Ensure device has a running client
                        if mac not in self.clients or mac not in self.client_tasks:
                            logger.info(f"Starting missing client for {friendly_name} ({mac})")
                            self.on_device_found(device_info)
                        elif mac in self.client_tasks and self.client_tasks[mac].done():
                            logger.warning(f"Client task for {mac} has ended, restarting")
                            self.on_device_found(device_info)
                else:
                    logger.info("No devices currently found")
        except asyncio.CancelledError:
            logger.info("Discovery loop cancelled")
            raise
    
    async def stop(self):
        """Stop all services"""
        logger.info("Stopping all services...")
        self._running = False
        
        # Cancel device processor task
        if self.device_processor_task:
            self.device_processor_task.cancel()
            try:
                await self.device_processor_task
            except asyncio.CancelledError:
                pass
        
        # Cancel discovery
        if self.discovery_task:
            self.discovery_task.cancel()
            try:
                await self.discovery_task
            except asyncio.CancelledError:
                pass
        
        # Close Zeroconf
        if self.zeroconf:
            self.zeroconf.close()
            self.zeroconf = None
        
        # Stop all clients
        for mac, client in self.clients.items():
            logger.info(f"Stopping client {mac}")
            client._running = False
            if mac in self.client_tasks:
                self.client_tasks[mac].cancel()
                try:
                    await self.client_tasks[mac]
                except asyncio.CancelledError:
                    pass
                del self.client_tasks[mac]
            await client.cleanup()
        
        self.clients = {}
        logger.info("All services stopped")

async def main():
    # Create the integrated system
    system = ESP32VoiceSystem(
        encryption_key=DEFAULT_ENCRYPTION_KEY,
        api_port=DEFAULT_PORT,
        udp_port=DEFAULT_UDP_PORT
    )
    
    try:
        # Start discovery
        await system.start_discovery()
        
        # Log active device connections every minute
        while True:
            await asyncio.sleep(60)
            
            # Log status of active clients
            if system.clients:
                logger.info(f"Active voice assistant clients: {len(system.clients)}")
                for mac, client in system.clients.items():
                    connection_status = "Connected" if not client.reconnect_attempts else "Reconnecting"
                    logger.info(f"Client {mac} ({client.host}): {connection_status}")
            else:
                logger.info("No active voice assistant clients")
            
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt detected")
    except Exception as e:
        logger.error(f"Error in main: {e}")
    finally:
        # Cleanup
        await system.stop()
        logger.info("System shutdown complete")

if __name__ == "__main__":
    asyncio.run(main())