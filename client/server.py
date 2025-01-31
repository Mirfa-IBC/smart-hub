import asyncio
import logging
from aioesphomeapi import APIClient
import socket
import time
import numpy as np
from wake_word.detector import WakeWordDetector
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

class VoiceAssistantUDPServer:
    def __init__(self, host: str = '0.0.0.0', port: int = 12345, max_retries: int = 3):
        self.host = host
        self.port = port
        self.base_port = port  # Store original port for retry attempts
        self.socket = None
        self._running = False
        self.last_packet_time = None
        self.packets_received = 0
        self.audio_callback = None
        self.max_retries = max_retries
        self.connection_attempts = 0
        self.last_error_time = 0
        self.error_threshold = 5  # Max errors per minute
        self.error_count = 0
        self.last_error_reset = time.time()

    def set_audio_callback(self, callback):
        self.audio_callback = callback

    async def start_server(self):
        while self.connection_attempts < self.max_retries:
            try:
                # Try with current port
                current_port = self.base_port + self.connection_attempts
                logger.info(f"Attempting to start UDP server on {self.host}:{current_port}")
                
                self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                
                # Add keep-alive for TCP connections
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                
                # Set larger buffer sizes
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 65536)
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 65536)
                
                self.socket.bind((self.host, current_port))
                self.socket.setblocking(False)
                self._running = True
                self.port = current_port  # Update with successful port
                
                logger.info(f"UDP Server started successfully on {self.host}:{self.port}")
                asyncio.create_task(self.monitor_connection())
                asyncio.create_task(self.receive_loop())
                return self.port

            except OSError as e:
                logger.error(f"Failed to bind to port {current_port}: {e}")
                self.connection_attempts += 1
                if self.connection_attempts >= self.max_retries:
                    raise RuntimeError(f"Failed to start UDP server after {self.max_retries} attempts")
                await asyncio.sleep(1)  # Wait before retry

    async def monitor_connection(self):
        """Monitor connection health and attempt recovery if needed"""
        while self._running:
            current_time = time.time()
            
            # Reset error count every minute
            if current_time - self.last_error_reset >= 60:
                self.error_count = 0
                self.last_error_reset = current_time

            # Check for connection timeout
            if self.last_packet_time and \
               current_time - self.last_packet_time > 10:  # 10 second timeout
                logger.warning("Connection timeout detected, attempting recovery")
                await self.attempt_recovery()

            await asyncio.sleep(1)

    async def attempt_recovery(self):
        """Attempt to recover from connection issues"""
        if self.error_count < self.error_threshold:
            self.error_count += 1
            logger.info("Attempting connection recovery")
            
            # Close existing socket
            if self.socket:
                self.socket.close()
                
            # Attempt to recreate socket
            try:
                self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                self.socket.bind((self.host, self.port))
                self.socket.setblocking(False)
                logger.info("Successfully recovered connection")
            except Exception as e:
                logger.error(f"Recovery attempt failed: {e}")

    @backoff.on_exception(
        backoff.expo,
        (ConnectionError, socket.error),
        max_tries=5,
        max_time=30
    )
    async def receive_loop(self):
        """Continuously receive UDP packets with exponential backoff retry"""
        logger.info("Starting UDP receive loop")
        buffer_size = 4096  # Increased buffer size
        
        while self._running and self.socket:
            try:
                loop = asyncio.get_event_loop()
                data, addr = await loop.sock_recvfrom(self.socket, buffer_size)
                
                # Update connection monitoring
                self.last_packet_time = time.time()
                self.packets_received += 1

                # Process received data
                if self.audio_callback and len(data) > 0:
                    try:
                        await self.audio_callback(data)
                    except Exception as e:
                        logger.error(f"Error in audio callback: {e}")

            except (BlockingIOError, InterruptedError):
                await asyncio.sleep(0.001)
            except ConnectionError as e:
                logger.error(f"Connection error in receive loop: {e}")
                await self.attempt_recovery()
                raise  # Allow backoff to handle retry
            except Exception as e:
                logger.error(f"Unexpected error in receive loop: {e}")
                await asyncio.sleep(0.1)

    def stop(self):
        """Stop the UDP server gracefully"""
        logger.info("Stopping UDP server")
        self._running = False
        if self.socket:
            try:
                self.socket.shutdown(socket.SHUT_RDWR)
                self.socket.close()
            except Exception as e:
                logger.error(f"Error closing UDP socket: {e}")
            self.socket = None
        logger.info("UDP Server stopped")

class VoiceAssistantClient:
    def __init__(self, host: str, encryption_key: str = None, port: int = 6053):
        self.host = host
        self.port = port
        self.encryption_key = encryption_key
        self.client = APIClient(host, port, password="", noise_psk=encryption_key)
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 5
        self.reconnect_delay = 1  # Start with 1 second delay
        self.voice_assistant_udp_server = None

        self.buffer_position = 0
        self.buffer_size = 8000  # 0.5 seconds at 16kHz
        self.audio_buffer = np.zeros(self.buffer_size, dtype=np.int16)
        self.buffer_filled = False
        
        # Add detection state management
        self.last_detection_time = 0
        self.detection_cooldown = 0.5  
        self.detector = WakeWordDetector(model_path="/home/abc/smart-hub/models/mirfa.onnx");
        
        # Ensure recordings directory exists
        os.makedirs('recordings', exist_ok=True)
        
        # Configure reconnection settings
        self._request_timeout = 30  # Used in connect method
    async def handle_audio(self, data: bytes) -> None:
        try:
            # Convert and downsample from 32kHz to 16kHz
            audio_data = np.frombuffer(data, dtype=np.int16)[::2]
            
            # Process in fixed-size chunks
            chunk_size = len(audio_data)
            
            # Update ring buffer
            if self.buffer_position + chunk_size > self.buffer_size:
                # Split the chunk
                first_part = self.buffer_size - self.buffer_position
                second_part = chunk_size - first_part
                
                self.audio_buffer[self.buffer_position:] = audio_data[:first_part]
                self.audio_buffer[:second_part] = audio_data[first_part:]
                self.buffer_position = second_part
            else:
                self.audio_buffer[self.buffer_position:self.buffer_position + chunk_size] = audio_data
                self.buffer_position += chunk_size
                
            if self.buffer_position >= self.buffer_size:
                self.buffer_position = 0
                self.buffer_filled = True
            
            # Only detect if buffer is filled and cooldown has passed
            current_time = time.time()
            if self.buffer_filled and current_time - self.last_detection_time > self.detection_cooldown:
                if self.detector.detect(self.audio_buffer):
                    logger.info("Wake word detected!")
                    self.last_detection_time = current_time
                    
        except Exception as e:
            logger.error(f"Error handling audio data: {e}", exc_info=True)

    async def handle_pipeline_start(
        self, 
        conversation_id: str, 
        flags: int, 
        audio_settings: VoiceAssistantAudioSettings,
        wake_word_phrase: str | None = None
    ) -> int:
        """Handle the start of a voice assistant pipeline"""
        logger.info("=== Pipeline Start ===")
        logger.info(f"Conversation ID: {conversation_id}")
        logger.info(f"Flags: {flags}")
        logger.info(f"Audio Settings: {audio_settings}")
        
        # Clean up any existing UDP server
        if self.voice_assistant_udp_server is not None:
            logger.warning("Cleaning up existing UDP server")
            self.voice_assistant_udp_server.stop()
            self.voice_assistant_udp_server = None

        # Create a new UDP server
        self.voice_assistant_udp_server = VoiceAssistantUDPServer()
        self.voice_assistant_udp_server.set_audio_callback(self.handle_audio)
        
        try:
            port = await self.voice_assistant_udp_server.start_server()
            self.server_port = port
            
            # Store conversation details
            self.conversation_id = conversation_id or str(uuid.uuid4())
            self.is_running = True
            
            logger.info(f"Pipeline started - Port: {port}")
            return port
            
        except Exception as e:
            logger.error(f"Failed to start pipeline: {e}")
            if self.voice_assistant_udp_server:
                self.voice_assistant_udp_server.stop()
            return self.server_port

    async def handle_stop(self, server_side: bool) -> None:
        """Handle the stop of audio streaming"""
        logger.info(f"🛑 Voice assistant stopped streaming (server_side: {server_side})")
        await self.handle_pipeline_finished()

    async def handle_pipeline_finished(self):
        """Handle the completion of a voice assistant pipeline"""
        logger.info("Voice assistant pipeline finished")
        
        # Save the recording
        await self.save_recording()
        
        # Clean up UDP server
        if self.voice_assistant_udp_server:
            self.voice_assistant_udp_server.stop()
            self.voice_assistant_udp_server = None
        
        # Reset state
        self.conversation_id = None
        self.is_running = False

    @backoff.on_exception(
        backoff.expo,
        Exception,
        max_tries=5,
        max_time=60
    )
    async def connect(self):
        """Connect to the ESPHome device with retry logic"""
        try:
            await self.client.connect(login=True)
            logger.info(f"🔌 Connected to {self.host}:{self.port}")
            
            # Reset reconnection counters on successful connection
            self.reconnect_attempts = 0
            self.reconnect_delay = 1
            
            device_info = await self.client.device_info()
            logger.info(f"📱 Device: {device_info.name} (ESPHome {device_info.esphome_version})")
            
            # Subscribe to voice assistant events
            await self.subscribe_to_events()
            
        except Exception as e:
            logger.error(f"❌ Connection failed: {e}")
            if self.reconnect_attempts < self.max_reconnect_attempts:
                self.reconnect_attempts += 1
                self.reconnect_delay *= 2  # Exponential backoff
                logger.info(f"Retrying connection in {self.reconnect_delay} seconds...")
                await asyncio.sleep(self.reconnect_delay)
                await self.connect()
            else:
                raise RuntimeError("Max reconnection attempts reached")

    async def subscribe_to_events(self):
        """Subscribe to voice assistant events with error handling"""
        try:
            logger.info("Subscribing to voice assistant events...")
            self.client.subscribe_voice_assistant(
                handle_start=self.handle_pipeline_start,
                handle_stop=self.handle_stop,
                handle_audio=self.handle_audio
            )
            logger.info("✅ Subscribed to voice assistant events")
        except Exception as e:
            logger.error(f"Failed to subscribe to events: {e}")
            raise

    async def run(self):
        """Main run loop with improved error handling"""
        while True:
            try:
                await self.connect()
                while True:
                    await asyncio.sleep(1)
                    # Add periodic connection check
                    # logger.info(f"{dir(self.client)}")
                    # if not self.client.connected:
                    #     logger.warning("Connection lost, attempting to reconnect...")
                    #     break
                    
            except asyncio.CancelledError:
                logger.info("Shutting down...")
                break
            except Exception as e:
                logger.error(f"Error in run loop: {e}")
                await asyncio.sleep(5)  # Wait before retry
            finally:
                await self.cleanup()

    async def cleanup(self):
        """Clean up resources"""
        if self.voice_assistant_udp_server:
            self.voice_assistant_udp_server.stop()
        try:
            await self.client.disconnect()
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")

async def main():
    # Configuration
    HOST = "192.168.1.199"
    ENCRYPTION_KEY = "B/ZTOpKW5IyL0jUv9InGeNOpVPdj4+oDO48fmwrh5Ak="
    PORT = 6053
    
    # Create and run client with automatic retry
    while True:
        try:
            client = VoiceAssistantClient(
                host=HOST,
                encryption_key=ENCRYPTION_KEY,
                port=PORT
            )
            await client.run()
        except Exception as e:
            logger.error(f"Critical error, restarting client: {e}")
            await asyncio.sleep(5)  # Wait before restarting

if __name__ == "__main__":
    asyncio.run(main())