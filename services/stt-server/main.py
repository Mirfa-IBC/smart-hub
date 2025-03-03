import asyncio
import logging
import socket
import time
from datetime import datetime
from collections import defaultdict, deque
from dataclasses import dataclass
import numpy as np
import wave
import tempfile
import os

from wake_word.detector import WakeWordDetector
from audio_processing.vad2 import VADProcessor
from audio_processing.transcribe import WhisperProcessor
from command_processor import CommandProcessor
from zigbee_controller import Zigbee2MQTTController
from smart_home_controller import SmartHomeController

websockets_logger = logging.getLogger('websockets')
websockets_logger.setLevel(logging.INFO)

httpcore_logger = logging.getLogger('httpcore')
httpcore_logger.setLevel(logging.INFO)
open_ai_logger = logging.getLogger('openai')
open_ai_logger.setLevel(logging.INFO)

logger = logging.getLogger(__name__)

@dataclass
class AudioDevice:
    ip_address: str
    sample_width: int = 2
    channels: int = 1
    framerate: int = 32000
    
    def __post_init__(self):
        # Audio buffers
        self.audio_buffer = bytearray()
        self.silence_counter = 0
        self.vad_buffer = np.zeros(16000 * 2, dtype=np.float32)  # 2 seconds buffer at 16kHz
        self.vad_cursor = 0
        self.detection_buffer = deque(maxlen=50)  # 50 chunks for detection
        
        # Device state
        self.last_activity = time.time()
        self.state = 'DETECTING'
        self.listening = False
        
        # For device identification
        self.id = self.ip_address  # Use IP as unique identifier
        self.name = f"Device_{self.ip_address.split('.')[-1]}"  # Use last octet of IP as readable name

    def add_audio_data(self, data: bytes):
        """Add new audio data to buffers with proper synchronization"""
        try:
            audio_chunk = np.frombuffer(data, dtype=np.int16).copy()
            self.last_activity = time.time()
            
            if self.state == 'DETECTING':
                self.detection_buffer.append(audio_clip(audio_chunk))
            
            elif self.state == 'LISTENING':
                self.audio_buffer.extend(data)
                # Convert to float32 and downsample to 16kHz for VAD
                audio_32k = audio_chunk.astype(np.float32) / 32767.0
                audio_16k = audio_32k[::2]  # Downsample from 32kHz to 16kHz
                
                # Circular buffer implementation for VAD
                remaining_space = len(self.vad_buffer) - self.vad_cursor
                if len(audio_16k) > remaining_space:
                    # Reset buffer if full
                    self.vad_buffer = np.roll(self.vad_buffer, -self.vad_cursor)
                    self.vad_cursor = 0
                
                end_pos = self.vad_cursor + len(audio_16k)
                self.vad_buffer[self.vad_cursor:end_pos] = audio_16k
                self.vad_cursor = end_pos
                
        except Exception as e:
            logger.error(f"Error processing audio data: {e}")

def audio_clip(audio_chunk: np.ndarray) -> np.ndarray:
    """Clip audio values to int16 range efficiently"""
    return np.clip(audio_chunk, -32768, 32767, out=audio_chunk).astype(np.int16)

class VoiceAssistantUDPServer:
    def __init__(self, host: str = '0.0.0.0', port: int = 12345, mqtt_api_host: str = "localhost"):
        self.host = host
        self.port = port
        self.socket = None
        self._running = False
        self.devices = {}
        
        # Add timeout for forced audio save
        self.max_listening_duration = 10  # Maximum seconds to wait before forcing audio save
        
        # Initialize processors with proper error handling
        try:
            self.detector = WakeWordDetector(wake_word_models=["alexa"], model_paths=["/opt/smart-hub/models/mirfa.onnx"])
            self.transcriber = WhisperProcessor()
            self.vad = VADProcessor()
            
            # Initialize command processing components
            self.command_processor = CommandProcessor(os.getenv("OPENAI_API_KEY"))
            self.zigbee = Zigbee2MQTTController(mqtt_api_host, 8080, 'a')
            
        except Exception as e:
            logger.error(f"Failed to initialize processors: {e}")
            raise

    async def start_server(self):
        """Start UDP server with proper socket configuration"""
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 65536)  # Increased buffer
            self.socket.bind((self.host, self.port))
            self.socket.setblocking(False)
            self._running = True
            
            # Connect to Zigbee controller and initialize smart home controller
            await self.zigbee.connect()
            self.smart_home = SmartHomeController(self.command_processor, self.zigbee, self.command_processor)
            
            logger.info(f"UDP Server started on {self.host}:{self.port}")
            
            await asyncio.gather(
                self.receive_loop(),
                self.process_audio_loop()
            )
        except Exception as e:
            logger.error(f"Failed to start server: {e}")
            self.stop()
            raise

    async def receive_loop(self):
        """Asynchronous receive loop with proper error handling"""
        loop = asyncio.get_event_loop()
        
        while self._running:
            try:
                def receive():
                    return self.socket.recvfrom(1280)
                    
                data, addr = await loop.run_in_executor(None, receive)
                ip = addr[0]
                
                if ip not in self.devices:
                    self.devices[ip] = AudioDevice(ip)
                    logger.info(f"New device connected: {ip}")
                
                self.devices[ip].add_audio_data(data)
                
            except (BlockingIOError, InterruptedError):
                await asyncio.sleep(0.001)
            except Exception as e:
                logger.error(f"Receive error: {e}")
                await asyncio.sleep(0.1)  # Back off on error

    async def process_audio_loop(self):
        """Process audio with proper batch processing and error handling"""
        while self._running:
            try:
                current_time = time.time()
                
                # Process devices in batches
                for ip, device in list(self.devices.items()):
                    # Force save audio if listening has gone on too long
                    if device.state == 'LISTENING' and device.listening:
                        listening_duration = current_time - device.last_activity
                        if listening_duration >= self.max_listening_duration:
                            logger.info(f"Forcing audio save after timeout for {ip}")
                            await self.handle_speech_end(device)
                            continue
                    # Remove inactive devices
                    if current_time - device.last_activity > 30:
                        logger.info(f"Removing inactive device: {ip}")
                        del self.devices[ip]
                        continue
                    
                    # Only do wake word detection if we're in DETECTING state
                    if device.state == 'DETECTING' and not device.listening:
                        if len(device.detection_buffer) >= 25:  # At least 0.5s of audio
                            audio_data = np.concatenate(list(device.detection_buffer))
                            if self.detector.detect(audio_data[::2], ip):
                                device.state = 'LISTENING'
                                device.listening = True
                                device.vad_cursor = 0
                                device.listening_start_time = time.time()  # Track when listening started
                                logger.info(f"Wake word detected from {ip}")
                                
                                # Notify other devices in same group about wake word
                                await self.handle_wake_word(device.id)
                                
                                device.detection_buffer.clear()  # Clear detection buffer when starting to listen
                    
                    # VAD processing state
                    elif device.state == 'LISTENING':
                        # Process VAD in chunks
                        while device.vad_cursor >= self.vad.chunk_size:
                            vad_chunk = device.vad_buffer[:self.vad.chunk_size]
                            speech_prob = self.vad.process_chunk(vad_chunk)
                            
                            # Update buffer
                            device.vad_buffer = np.roll(device.vad_buffer, -self.vad.chunk_size)
                            device.vad_cursor -= self.vad.chunk_size
                            
                            # Handle silence detection
                            if speech_prob < self.vad.vad_threshold:  # Using threshold from original code
                                device.silence_counter += 1
                                if device.silence_counter >= self.vad.silence_threshold:
                                    logger.info("speech ended")
                                    await self.handle_speech_end(device)
                                    break
                            else:
                                device.silence_counter = 0
                            
                
                await asyncio.sleep(0.01)  # Reduced CPU usage
                
            except Exception as e:
                logger.error(f"Processing error: {e}")
                await asyncio.sleep(0.1)  # Back off on error

    async def handle_speech_end(self, device):
        """Handle end of speech with proper file handling and command processing"""
        try:
            audio_duration = len(device.audio_buffer) / (device.framerate * device.sample_width)
            
            if audio_duration >= self.vad.min_audio_length:
                # Create timestamp for logging
                # timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                
                # Save to temp file for processing
                with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as temp_file:
                    temp_filename = temp_file.name
                    with wave.open(temp_filename, 'wb') as wf:
                        wf.setnchannels(device.channels)
                        wf.setsampwidth(device.sample_width)
                        wf.setframerate(device.framerate)
                        wf.writeframes(device.audio_buffer)
                    
                    # Transcribe audio
                    t1 = int(time.time() * 1000)
                    logger.info(f"Processing start for {t1} {temp_filename}")
                    transcript = await self.transcriber.process_audio(temp_filename)
                
                # Delete temp file after processing
                os.unlink(temp_filename)
                
                if not transcript:
                    logger.info("No transcription received from Whisper")
                    return
                    
                logger.info(f"Transcription from {device.ip_address}: {transcript}")
                
                # Process command with smart home controller
                mic_id = device.id  # Use IP as unique ID
                result = await self.smart_home.process_voice_command(transcript, mic_id)
                
                # Log results
                # logger.info(f"Command processing results: {result}")
                
                t2 = int(time.time() * 1000)
                logger.info(f"Processing complete for audio from {device.ip_address} {t2} {t2-t1} ms")
            else:
                logger.info(f"Audio duration {audio_duration} is less than minimum {self.vad.min_audio_length}, not processing")
                
        except Exception as e:
            logger.error(f"Error handling speech end: {e}")
            import traceback
            traceback.print_exc()
        
        finally:
            # Reset device state
            device.audio_buffer.clear()
            device.vad_cursor = 0
            device.state = 'DETECTING'
            device.listening = False
            device.silence_counter = 0
            device.detection_buffer.clear()

    async def handle_wake_word(self, device_id: str):
        """Notify other devices in the same group when wake word is detected"""
        # This is a placeholder for group functionality
        # In the original code, you had device groups for multi-room awareness
        # If you want to implement this feature, you'll need to add group management
        pass

    def stop(self):
        """Clean shutdown with proper resource cleanup"""
        self._running = False
        if self.socket:
            try:
                self.socket.close()
            except Exception as e:
                logger.error(f"Error closing socket: {e}")
        logger.info("Server stopped")

async def main():
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # You can pass MQTT host as environment variable or hardcode it
    mqtt_host = os.getenv("MQTT_HOST", "localhost")
    
    server = VoiceAssistantUDPServer(mqtt_api_host=mqtt_host)
    try:
        await server.start_server()
    except KeyboardInterrupt:
        logger.info("Received shutdown signal")
    except Exception as e:
        logger.error(f"Server error: {e}")
    finally:
        server.stop()

if __name__ == "__main__":
    asyncio.run(main())