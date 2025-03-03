import asyncio
import logging
from aioesphomeapi import APIClient
import socket
import time
import backoff  # Add this dependency
from aioesphomeapi.model import (
    VoiceAssistantAudioData, 
    VoiceAssistantAudioSettings, 
    VoiceAssistantEventType
)
import os
import uuid
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# class VoiceAssistantUDPServer:
#     def __init__(self, host: str = '0.0.0.0', port: int = 12345, max_retries: int = 3):
#         self.host = host
#         self.port = port
#         self.base_port = port  # Store original port for retry attempts
#         self.socket = None
#         self._running = False
#         self.last_packet_time = None
#         self.packets_received = 0
#         self.audio_callback = None
#         self.max_retries = max_retries
#         self.connection_attempts = 0
#         self.last_error_time = 0
#         self.error_threshold = 5  # Max errors per minute
#         self.error_count = 0
#         self.last_error_reset = time.time()

#     async def start_server(self):
#         while self.connection_attempts < self.max_retries:
#             try:
#                 # Try with current port
#                 current_port = self.base_port + self.connection_attempts
#                 logger.info(f"Attempting to start UDP server on {self.host}:{current_port}")
                
#                 self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
#                 self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                
#                 # Add keep-alive for TCP connections
#                 self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                
#                 # Set larger buffer sizes
#                 self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 65536)
#                 self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 65536)
                
#                 self.socket.bind((self.host, current_port))
#                 self.socket.setblocking(False)
#                 self._running = True
#                 self.port = current_port  # Update with successful port
                
#                 logger.info(f"UDP Server started successfully on {self.host}:{self.port}")
#                 asyncio.create_task(self.monitor_connection())
#                 asyncio.create_task(self.receive_loop())
#                 return self.port

#             except OSError as e:
#                 logger.error(f"Failed to bind to port {current_port}: {e}")
#                 self.connection_attempts += 1
#                 if self.connection_attempts >= self.max_retries:
#                     raise RuntimeError(f"Failed to start UDP server after {self.max_retries} attempts")
#                 await asyncio.sleep(1)  # Wait before retry

#     async def monitor_connection(self):
#         """Monitor connection health and attempt recovery if needed"""
#         while self._running:
#             current_time = time.time()
            
#             # Reset error count every minute
#             if current_time - self.last_error_reset >= 60:
#                 self.error_count = 0
#                 self.last_error_reset = current_time

#             # Check for connection timeout
#             if self.last_packet_time and \
#                current_time - self.last_packet_time > 10:  # 10 second timeout
#                 logger.warning("Connection timeout detected, attempting recovery")
#                 await self.attempt_recovery()

#             await asyncio.sleep(1)

#     async def attempt_recovery(self):
#         """Attempt to recover from connection issues"""
#         if self.error_count < self.error_threshold:
#             self.error_count += 1
#             logger.info("Attempting connection recovery")
            
#             # Close existing socket
#             if self.socket:
#                 self.socket.close()
                
#             # Attempt to recreate socket
#             try:
#                 self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
#                 self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
#                 self.socket.bind((self.host, self.port))
#                 self.socket.setblocking(False)
#                 logger.info("Successfully recovered connection")
#             except Exception as e:
#                 logger.error(f"Recovery attempt failed: {e}")

#     @backoff.on_exception(
#         backoff.expo,
#         (ConnectionError, socket.error),
#         max_tries=5,
#         max_time=30
#     )
#     async def receive_loop(self):
#         """Continuously receive UDP packets with exponential backoff retry"""
#         logger.info("Starting UDP receive loop")
#         buffer_size = 4096  # Increased buffer size
        
#         while self._running and self.socket:
#             try:
#                 loop = asyncio.get_event_loop()
#                 data, addr = await loop.sock_recvfrom(self.socket, buffer_size)
                
#                 # Update connection monitoring
#                 self.last_packet_time = time.time()
#                 self.packets_received += 1
#                 # print("UDP data received",addr)

#             except (BlockingIOError, InterruptedError):
#                 await asyncio.sleep(0.001)
#             except ConnectionError as e:
#                 logger.error(f"Connection error in receive loop: {e}")
#                 await self.attempt_recovery()
#                 raise  # Allow backoff to handle retry
#             except Exception as e:
#                 logger.error(f"Unexpected error in receive loop: {e}")
#                 await asyncio.sleep(0.1)

#     def stop(self):
#         """Stop the UDP server gracefully"""
#         logger.info("Stopping UDP server")
#         self._running = False
#         if self.socket:
#             try:
#                 self.socket.shutdown(socket.SHUT_RDWR)
#                 self.socket.close()
#             except Exception as e:
#                 logger.error(f"Error closing UDP socket: {e}")
#             self.socket = None
#         logger.info("UDP Server stopped")

class VoiceAssistantClient:
    def __init__(self, host: str, encryption_key: str = None, port: int = 6053, udp_port: int = 12345):
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
            await self.client.connect(login=True)
            logger.info(f"🔌 Connected to {self.host}:{self.port}")
            
            self.reconnect_attempts = 0
            self.reconnect_delay = 1
            
            device_info = await self.client.device_info()
            logger.info(f"📱 Device: {device_info.name} (ESPHome {device_info.esphome_version})")
            
            await self.subscribe_to_events()
            
        except Exception as e:
            logger.error(f"❌ Connection failed for {self.host}: {e}")
            if self.reconnect_attempts < self.max_reconnect_attempts:
                self.reconnect_attempts += 1
                self.reconnect_delay *= 2
                logger.info(f"Retrying connection to {self.host} in {self.reconnect_delay} seconds...")
                await asyncio.sleep(self.reconnect_delay)
                await self.connect()
            else:
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
                while self._running:
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
async def main():
    # Configuration
    ENCRYPTION_KEY = "B/ZTOpKW5IyL0jUv9InGeNOpVPdj4+oDO48fmwrh5Ak="
    PORT = 6053
    
    # List of ESP devices
    ESP_DEVICES = [
        {
            "host": "192.168.11.110",
            "encryption_key": ENCRYPTION_KEY,
            "port": PORT
        }
    ]

    while True:
        try:
            # Start UDP server first
            # voice_assistant_udp_server = VoiceAssistantUDPServer()
            # udp_port = await voice_assistant_udp_server.start_server()

            # Create all clients
            clients = [
                VoiceAssistantClient(
                    host=device["host"],
                    encryption_key=device["encryption_key"],
                    port=device["port"],
                    udp_port=12345
                )
                for device in ESP_DEVICES
            ]

            # Run all clients concurrently using gather
            try:
                await asyncio.gather(*(client.run() for client in clients))
            except Exception as e:
                logger.error(f"Error in client execution: {e}")
            finally:
                # Cleanup clients
                for client in clients:
                    client._running = False
                    await client.cleanup()
                # Stop UDP server
                

        except Exception as e:
            logger.error(f"Critical error in main loop: {e}")
            await asyncio.sleep(5)  # Wait before restarting everything

if __name__ == "__main__":
    asyncio.run(main())
