import asyncio
import logging
from aioesphomeapi import APIClient
import socket
import time
import numpy as np
from wake_word.detector import WakeWordDetector
from dataclasses import dataclass
from typing import Dict, Optional, List
import whisper
import torch
from collections import deque
import webrtcvad
import struct

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@dataclass
class ESPDeviceState:
    device_name: str
    last_seen: float
    client: Optional[APIClient] = None
    is_connected: bool = False
    udp_port: Optional[int] = None
    buffer_position: int = 0
    buffer_size: int = 4000  # 0.5 seconds at 16kHz
    audio_buffer: np.ndarray = None
    buffer_filled: bool = False
    detector: Optional[WakeWordDetector] = None
    last_detection_time: float = 0
    detection_cooldown: float = 0.3
    is_listening: bool = False
    main_buffer: Optional[List[float]] = None
    vad_buffer: Optional[bytes] = None
    last_voice_activity: float = 0
    voice_timeout: float = 1.0  # Time to wait for more speech before processing
    min_voice_length: int = 16000  # Minimum 1 second of speech before processing

    def __post_init__(self):
        self.audio_buffer = np.zeros(self.buffer_size, dtype=np.int16)
        self.detector = WakeWordDetector(model_path="/Users/naveenjain/Documents/code/mirfa/custom_wake_word/my_model/mirfa.onnx")
        self.main_buffer = []
        self.vad_buffer = b''

class ESP32UDPBridge:
    def __init__(
        self,
        udp_host: str = '0.0.0.0',
        udp_port: int = 12345,
        buffer_size: int = 65536
    ):
        self.udp_host = udp_host
        self.udp_port = udp_port
        self.buffer_size = buffer_size
        self.udp_socket = None
        self._running = False
        self.esp_devices: Dict[str, ESPDeviceState] = {}
        
        # Initialize Whisper model with optimizations
        self.whisper_model = whisper.load_model("tiny.en")
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        if self.device == "cuda":
            self.whisper_model = self.whisper_model.to(self.device)
        logger.info(f"Loaded Whisper model on {self.device}")
        
        # Initialize VAD
        self.vad = webrtcvad.Vad(3)  # Aggressiveness level 3
        
        # Initialize UDP server
        self.init_udp_server()

    def init_udp_server(self):
        """Initialize UDP server"""
        try:
            self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, self.buffer_size)
            self.udp_socket.bind((self.udp_host, self.udp_port))
            self.udp_socket.setblocking(False)
            self._running = True
            logger.info(f"UDP Server initialized on {self.udp_host}:{self.udp_port}")
        except Exception as e:
            logger.error(f"Failed to initialize UDP server: {e}")
            raise

    def frame_generator(self, audio: bytes, sample_rate: int, frame_duration: int):
        """Generate frames of specific duration from audio data"""
        n = int(sample_rate * (frame_duration / 1000.0) * 2)  # 2 bytes per sample
        offset = 0
        while offset + n <= len(audio):
            yield audio[offset:offset + n]
            offset += n

    def is_speech(self, audio_chunk: bytes, sample_rate: int = 16000) -> bool:
        """Detect if audio chunk contains speech using WebRTC VAD"""
        try:
            return self.vad.is_speech(audio_chunk, sample_rate)
        except:
            return False

    async def transcribe_audio(self, device: ESPDeviceState):
        """Transcribe audio when appropriate conditions are met"""
        current_time = time.time()
        
        # Check if we have enough silence after speech
        if (len(device.main_buffer) >= device.min_voice_length and 
            current_time - device.last_voice_activity > device.voice_timeout):
            
            try:
                # Convert buffer to numpy array
                audio_data = np.array(device.main_buffer, dtype=np.float32)
                
                # Normalize audio
                if len(audio_data) > 0:
                    audio_data = audio_data / np.max(np.abs(audio_data))
                    
                    # Transcribe using Whisper
                    result = self.whisper_model.transcribe(
                        audio_data,
                        language='en',
                        fp16=torch.cuda.is_available(),
                        temperature=0.0,
                        without_timestamps=True,
                        condition_on_previous_text=True,
                        initial_prompt="Transcribing real-time speech:"
                    )
                    
                    transcribed_text = result["text"].strip()
                    if transcribed_text:
                        logger.info(f"🗣️ {device.device_name}: {transcribed_text}")
                    
                    # Clear the main buffer after processing
                    device.main_buffer = []
                    
            except Exception as e:
                logger.error(f"Error transcribing audio from {device.device_name}: {e}")

    async def add_esp_device(self, host: str, encryption_key: str = None, port: int = 6053):
        """Add and connect to an ESP device"""
        try:
            client = APIClient(host, port, password="", noise_psk=encryption_key)
            
            # Connect to device
            await client.connect(login=True)
            
            # Get device info
            device_info = await client.device_info()
            
            # Initialize device state
            self.esp_devices[host] = ESPDeviceState(
                device_name=device_info.name,
                last_seen=time.time(),
                client=client,
                is_connected=True
            )
            
            # Subscribe to voice assistant events
            client.subscribe_voice_assistant(
                handle_start=lambda *args: self.handle_pipeline_start(host, *args),
                handle_stop=lambda *args: self.handle_pipeline_stop(host, *args),
                handle_audio=lambda data: self.handle_audio(host, data)
            )
            
            logger.info(f"Successfully connected to {device_info.name} at {host}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to connect to ESP device at {host}: {e}")
            return False

    async def handle_pipeline_start(self, host, conversation_id, flags, audio_settings, wake_word_phrase=None):
        """Handle start of audio pipeline"""
        logger.info(f"Pipeline start from {host}")
        device = self.esp_devices.get(host)
        if device:
            device.udp_port = self.udp_port
            device.buffer_position = 0
            device.buffer_filled = False
            device.last_detection_time = 0
            device.main_buffer = []
            device.vad_buffer = b''
        return self.udp_port

    async def handle_pipeline_stop(self, host, server_side):
        """Handle stop of audio pipeline"""
        logger.info(f"Pipeline stop from {host}")
        device = self.esp_devices.get(host)
        if device:
            device.udp_port = None
            device.buffer_filled = False
            device.is_listening = False
            device.main_buffer = []
            device.vad_buffer = b''

    async def handle_audio(self, host, data: bytes):
        """Process audio data with wake word detection and transcription"""
        device = self.esp_devices.get(host)
        if not device:
            return

        try:
            # Convert and downsample from 32kHz to 16kHz
            audio_data = np.frombuffer(data, dtype=np.int16)[::2]
            
            # Process in fixed-size chunks
            chunk_size = len(audio_data)
            
            # If we're actively listening, process audio for transcription
            if device.is_listening:
                # Convert audio to proper format for VAD
                raw_audio = struct.pack("<%dh" % len(audio_data), *audio_data)
                device.vad_buffer += raw_audio
                
                # Process VAD in 30ms frames
                frames = list(self.frame_generator(device.vad_buffer, 16000, 30))
                
                # If we have enough frames for VAD
                while len(frames) > 0:
                    frame = frames.pop(0)
                    if len(frame) == 960:  # 30ms at 16kHz
                        if self.is_speech(frame):
                            device.last_voice_activity = time.time()
                            
                        # Add normalized audio to main buffer
                        float_data = np.frombuffer(frame, dtype=np.int16).astype(np.float32) / 32768.0
                        device.main_buffer.extend(float_data)
                        
                        # Remove processed frame from VAD buffer
                        device.vad_buffer = device.vad_buffer[len(frame):]
                
                # Try to transcribe if we have enough audio
                await self.transcribe_audio(device)
                
                # Check for extended silence to stop listening
                if time.time() - device.last_voice_activity > device.voice_timeout * 2:
                    device.is_listening = False
                    device.main_buffer = []
                    device.vad_buffer = b''
                    logger.info(f"Stopped listening to {device.device_name} due to silence")
            
            # Wake word detection logic
            if device.buffer_position + chunk_size > device.buffer_size:
                first_part = device.buffer_size - device.buffer_position
                second_part = chunk_size - first_part
                
                device.audio_buffer[device.buffer_position:] = audio_data[:first_part]
                device.audio_buffer[:second_part] = audio_data[first_part:]
                device.buffer_position = second_part
                
                if (not device.is_listening and 
                    time.time() - device.last_detection_time > device.detection_cooldown):
                    if device.detector.detect(device.audio_buffer.copy()):
                        logger.info(f"🎤 Wake word detected from {device.device_name}!")
                        device.last_detection_time = time.time()
                        device.is_listening = True
                        device.main_buffer = []
                        device.vad_buffer = b''
            else:
                device.audio_buffer[
                    device.buffer_position:device.buffer_position + chunk_size
                ] = audio_data
                device.buffer_position += chunk_size
                
                if (not device.is_listening and 
                    device.buffer_position >= device.buffer_size * 0.75):
                    if time.time() - device.last_detection_time > device.detection_cooldown:
                        if device.detector.detect(device.audio_buffer[:device.buffer_position].copy()):
                            logger.info(f"🎤 Wake word detected from {device.device_name}!")
                            device.last_detection_time = time.time()
                            device.is_listening = True
                            device.main_buffer = []
                            device.vad_buffer = b''
            
            # Reset buffer position if needed
            if device.buffer_position >= device.buffer_size:
                device.buffer_position = 0
                        
        except Exception as e:
            logger.error(f"Error handling audio data for {device.device_name}: {e}", exc_info=True)

    async def run(self):
        """Main run loop"""
        logger.info("Starting ESP32 UDP Bridge")
        
        while self._running:
            try:
                loop = asyncio.get_event_loop()
                data, addr = await loop.sock_recvfrom(self.udp_socket, self.buffer_size)
                
                if len(data) > 0:
                    host = addr[0]
                    if host in self.esp_devices:
                        await self.handle_audio(host, data)
                    
            except (BlockingIOError, InterruptedError):
                await asyncio.sleep(0.001)
            except Exception as e:
                logger.error(f"Error in main loop: {e}")
                await asyncio.sleep(0.1)

    async def stop(self):
        """Stop the bridge"""
        self._running = False
        
        # Disconnect all devices
        for host, device in self.esp_devices.items():
            if device.client:
                try:
                    await device.client.disconnect()
                except Exception as e:
                    logger.error(f"Error disconnecting {device.device_name}: {e}")
        
        # Close UDP socket
        if self.udp_socket:
            self.udp_socket.close()

async def main():
    # Configuration
    ESP_DEVICES = [
        {
            "host": "192.168.1.11",
            "encryption_key": "B/ZTOpKW5IyL0jUv9InGeNOpVPdj4+oDO48fmwrh5Ak=",
            "port": 6053
        }
    ]
    
    bridge = ESP32UDPBridge(udp_host='0.0.0.0', udp_port=12345)
    
    try:
        # Connect to ESP devices
        for device in ESP_DEVICES:
            success = await bridge.add_esp_device(
                host=device["host"],
                encryption_key=device["encryption_key"],
                port=device["port"]
            )
            if not success:
                logger.error(f"Failed to connect to device {device['host']}")
                continue
        
        # Run the bridge
        await bridge.run()
        
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        await bridge.stop()

if __name__ == "__main__":
    asyncio.run(main())