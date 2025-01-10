import asyncio
import logging
from aioesphomeapi import APIClient
from aioesphomeapi.model import (
    VoiceAssistantAudioData, 
    VoiceAssistantAudioSettings, 
    VoiceAssistantEventType
)
import wave
from datetime import datetime
import os
import io
import socket
import uuid
import time
import numpy as np
import struct

# Set up logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class VoiceAssistantUDPServer:
    """UDP server to handle voice assistant communication"""
    def __init__(self, host: str = '0.0.0.0', port: int = 12345):
        self.host = host
        self.port = port
        self.socket = None
        self._running = False
        self.last_packet_time = None
        self.packets_received = 0
        self.audio_callback = None

    def set_audio_callback(self, callback):
        """Set callback for audio data processing"""
        self.audio_callback = callback

    async def start_server(self):
        """Start UDP server and return the port"""
        try:
            logger.info(f"Creating UDP socket on {self.host}:{self.port}")
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            logger.info(f"Binding UDP socket to {self.host}:{self.port}")
            self.socket.bind((self.host, self.port))
            self.socket.setblocking(False)
            self._running = True
            logger.info(f"UDP Server started successfully on {self.host}:{self.port}")
            
            # Start the receive loop
            asyncio.create_task(self.receive_loop())
            return self.port
        except Exception as e:
            logger.error(f"Failed to start UDP server: {e}")
            raise

    async def receive_loop(self):
        """Continuously receive UDP packets"""
        logger.info("Starting UDP receive loop")
        while self._running and self.socket:
            try:
                data, addr = await asyncio.get_event_loop().sock_recvfrom(self.socket, 2048)
                
                # Send data to callback if registered
                if self.audio_callback and len(data) > 0:
                    await self.audio_callback(data)
                
                # Stats logging
                current_time = time.time()
                if self.last_packet_time is None:
                    self.last_packet_time = current_time
                
                self.packets_received += 1
                if current_time - self.last_packet_time >= 1.0:
                    logger.info(f"UDP Stats - Packets/sec: {self.packets_received}, Last packet size: {len(data)}")
                    self.packets_received = 0
                    self.last_packet_time = current_time
                
            except BlockingIOError:
                await asyncio.sleep(0.001)
            except Exception as e:
                logger.error(f"Error in UDP receive loop: {e}")
                await asyncio.sleep(0.1)

    def stop(self):
        """Stop the UDP server"""
        logger.info("Stopping UDP server")
        self._running = False
        if self.socket:
            try:
                self.socket.close()
            except Exception as e:
                logger.error(f"Error closing UDP socket: {e}")
            self.socket = None
        logger.info("UDP Server stopped")

    def close(self):
        """Close the UDP server"""
        self.stop()

class VoiceAssistantClient:
    def __init__(self, host: str, encryption_key: str = None, port: int = 6053):
        self.host = host
        self.port = port
        self.encryption_key = encryption_key
        self.client = APIClient(host, port, encryption_key, noise_psk=encryption_key)
        
        # Pipeline management
        self.conversation_id = None
        self.voice_assistant_udp_server = None
        
        # Recording management
        self.is_running = False
        self.server_port = 12345
        self.wav_file = None
        self.recording_started = False
        self.last_audio_time = None
        self.audio_chunks = 0
        
        # Audio settings
        self.sample_rate = 16000
        self.sample_width = 2
        self.channels = 1
        
        # Ensure recordings directory exists
        os.makedirs('recordings', exist_ok=True)

    async def handle_audio(self, data: bytes) -> None:
        """Handle incoming audio data with direct processing for optimal quality"""
        try:
            if not self.recording_started:
                self.recording_started = True
                logger.info("First audio chunk received, starting recording")
                
                if not self.wav_file:
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    filename = os.path.join('recordings', f"recording_{timestamp}.wav")
                    
                    self.wav_file = wave.open(filename, 'wb')
                    self.wav_file.setnchannels(1)  # Mono
                    self.wav_file.setsampwidth(2)  # 16-bit
                    self.wav_file.setframerate(16000)  # 16kHz
                    logger.info(f"Created new WAV file: {filename}")

            # Convert to float32 for processing
            audio_data = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32767.0
            
            # Apply clipping in float domain
            audio_data = np.clip(audio_data, -1.0, 1.0)
            
            # Optional: Apply gain if needed
            gain = 1.2  # Adjust this value based on your needs
            audio_data = audio_data * gain
            
            # Clip again after gain to prevent distortion
            audio_data = np.clip(audio_data, -1.0, 1.0)
            
            # Convert back to int16 for WAV file
            audio_int16 = (audio_data * 32767).astype(np.int16)
            
            # Log audio levels periodically (every 100 chunks)
            if self.audio_chunks % 100 == 0:
                peak_level = np.max(np.abs(audio_int16))
                rms_level = np.sqrt(np.mean(audio_int16.astype(np.float32)**2))
                logger.debug(f"Audio Levels - Peak: {peak_level}, RMS: {rms_level}")
            
            if self.wav_file:
                self.wav_file.writeframes(audio_int16.tobytes())
                self.audio_chunks += 1
                
        except Exception as e:
            logger.error(f"Error handling audio data: {e}")
            await self.save_recording()

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

    async def save_recording(self):
        """Save the recorded audio to file"""
        if self.wav_file:
            try:
                # Close the WAV file
                wav_filename = self.wav_file.name
                self.wav_file.close()
                
                # Get file size
                file_size = os.path.getsize(wav_filename)
                logger.info(f"Saved WAV file: {wav_filename}")
                logger.info(f"WAV file size: {file_size} bytes")
                
            except Exception as e:
                logger.error(f"Error saving audio file: {e}")
            finally:
                # Reset recording state
                self.wav_file = None
                self.recording_started = False

    async def connect(self):
        """Connect to the ESPHome device"""
        try:
            await self.client.connect(login=True)
            logger.info(f"🔌 Connected to {self.host}:{self.port}")

            # Get and log device info
            device_info = await self.client.device_info()
            logger.info(f"📱 Device: {device_info.name} (ESPHome {device_info.esphome_version})")

            # Subscribe to voice assistant events
            logger.info("Subscribing to voice assistant events...")
            self.client.subscribe_voice_assistant(
                handle_start=self.handle_pipeline_start,
                handle_stop=self.handle_stop,
                handle_audio=self.handle_audio
            )
            logger.info("✅ Subscribed to voice assistant events")

        except Exception as e:
            logger.error(f"❌ Connection failed: {e}")
            raise

    async def disconnect(self):
        """Disconnect from the device"""
        await self.save_recording()
        if self.voice_assistant_udp_server:
            self.voice_assistant_udp_server.stop()
        await self.client.disconnect()
        logger.info("Disconnected from device")

    async def run(self):
        """Main run loop"""
        try:
            await self.connect()
            while True:
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            logger.info("Shutting down...")
        except Exception as e:
            logger.error(f"Error in run loop: {e}")
        finally:
            await self.disconnect()

async def main():
    # Configuration
    HOST = "192.168.1.200"  # Replace with your ESPHome device's IP
    ENCRYPTION_KEY = None    # Replace with encryption key if required
    PORT = 6053             # Default ESPHome API port
    
    # Create and run client
    client = VoiceAssistantClient(
        host=HOST,
        encryption_key=ENCRYPTION_KEY,
        port=PORT
    )
    
    try:
        await client.run()
    except KeyboardInterrupt:
        logger.info("Stopping server...")
    except Exception as e:
        logger.error(f"Unhandled error: {e}")

if __name__ == "__main__":
    asyncio.run(main())