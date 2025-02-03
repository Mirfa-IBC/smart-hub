import asyncio
import logging
import socket
import time
import backoff
import wave
from datetime import datetime
from collections import defaultdict, deque
from dataclasses import dataclass,field
import numpy as np
from wake_word.detector import WakeWordDetector
from audio_processing.vad import VADProcessor
from audio_processing.transcribe import WhisperProcessor

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class AudioDevice:
    def __init__(self, ip_address: str, sample_width: int = 2, channels: int = 1, framerate: int = 32000):
        self.ip_address = ip_address
        self.sample_width = sample_width
        self.channels = channels
        self.framerate = framerate
        
        # Audio buffers
        self.audio_buffer: bytearray = bytearray()
        self.silence_counter: int = 0
        self.vad_buffer = []  # Changed from deque to list

        self.detection_buffer = deque(maxlen=50)  # 50 chunks for detection
        
        # Device state
        self.last_activity = time.time()
        self.is_active = True
        self.listening = False
        self.listening_start_time = None

    def add_audio_data(self, data: bytes):
        """Add new audio data to both buffers"""
        if self.listening:
            self.audio_buffer.extend(data)
            audio_np = np.frombuffer(data, dtype=np.int16)
            # Resample to 16kHz by taking every other sample
            audio_resampled = audio_np[::2].astype(np.float32) / 32767.0
            self.vad_buffer.extend(audio_resampled)
        audio_chunk = np.frombuffer(data, dtype=np.int16)
        audio_chunk = np.clip(audio_chunk, -32768, 32767).astype(np.int16)
        self.detection_buffer.append(audio_chunk)
        self.last_activity = time.time()

    def get_detection_audio(self) -> np.ndarray:
        """Get concatenated audio data for detection"""
        if len(self.detection_buffer) > 0:
            return np.concatenate(list(self.detection_buffer))
        return np.array([], dtype=np.int16)

    def clear_detection_buffer(self):
        """Clear the detection buffer"""
        self.detection_buffer.clear()

    def save_audio(self, timestamp: str) -> str:
        """Save accumulated audio to WAV file"""
        if len(self.audio_buffer) == 0:
            return ""
            
        filename = f"captured_audio_{self.ip_address}_{timestamp}.wav"
        try:
            with wave.open(filename, 'wb') as wave_file:
                wave_file.setnchannels(self.channels)
                wave_file.setsampwidth(self.sample_width)
                wave_file.setframerate(self.framerate)
                wave_file.writeframes(self.audio_buffer)
            return filename
        except Exception as e:
            logger.error(f"Error saving audio for device {self.ip_address}: {e}")
            return ""

class VoiceAssistantUDPServer:
    def __init__(self, host: str = '0.0.0.0', port: int = 12345, max_retries: int = 3):
        self.host = host
        self.port = port
        self.base_port = port
        self.socket = None
        self._running = False
        self.max_retries = max_retries
        self.connection_attempts = 0
        self.last_error_time = 0
        self.error_threshold = 5
        self.error_count = 0
        self.last_error_reset = time.time()
        self.monitor_task = None
        self.receive_task = None
        self.process_task = None

        # Device management
        self.devices = {}  # ip_address -> AudioDevice

        # Initialize detector
        self.detector = WakeWordDetector(wake_word_model="alexa")
        self.vad =  VADProcessor()
        self.detector.download_models()

    async def start_server(self):
        while self.connection_attempts < self.max_retries:
            try:
                current_port = self.base_port + self.connection_attempts
                logger.info(f"Attempting to start UDP server on {self.host}:{current_port}")
                
                self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 65536 * 4)
                
                self.socket.bind((self.host, current_port))
                self.socket.setblocking(False)
                self._running = True
                self.port = current_port
                
                logger.info(f"UDP Server started successfully on {self.host}:{self.port}")
                self.receive_task = asyncio.create_task(self.receive_loop())
                self.process_task = asyncio.create_task(self.process_audio_loop())
                return self.port

            except OSError as e:
                logger.error(f"Failed to bind to port {current_port}: {e}")
                self.connection_attempts += 1
                if self.connection_attempts >= self.max_retries:
                    raise RuntimeError(f"Failed to start UDP server after {self.max_retries} attempts")
                await asyncio.sleep(1)

    @backoff.on_exception(
        backoff.expo,
        (ConnectionError, socket.error),
        max_tries=5,
        max_time=30
    )
    async def receive_loop(self):
        """Continuously receive UDP packets and store audio data per device"""
        logger.info("Starting UDP receive loop")
        
        while self._running and self.socket:
            try:
                loop = asyncio.get_event_loop()
                data, addr = await loop.sock_recvfrom(self.socket, 1280)  # Using standard buffer size
                
                ip_address = addr[0]
                if ip_address not in self.devices:
                    self.devices[ip_address] = AudioDevice(ip_address)
                
                self.devices[ip_address].add_audio_data(data)

            except (BlockingIOError, InterruptedError):
                await asyncio.sleep(0.001)
            except ConnectionError as e:
                logger.error(f"Connection error in receive loop: {e}")
                raise
            except Exception as e:
                import traceback
                traceback.print_exc()
                logger.error(f"Unexpected error in receive loop: {e}")
                await asyncio.sleep(0.1)

    async def process_audio_loop(self):
        """Process audio chunks for wake word detection"""
        logger.info("Starting audio processing loop")
        
        while self._running:
            try:
                for device in self.devices.values():
                    audio_data = device.get_detection_audio()
                    if len(audio_data) > 0:
                        resampled_audio = self._resample_audio(audio_data)
                        if self.detector.detect(resampled_audio, device.ip_address):
                            logger.info(f"Wake word detected from {device.ip_address}!")
                            device.listening = True
                        if device.listening:
                            while len(device.vad_buffer) >= self.vad.chunk_size:
                                vad_chunk = np.array(device.vad_buffer[:self.vad.chunk_size])
                                speech_prob = self.vad.process_chunk(vad_chunk)
                                # Remove processed samples
                                device.vad_buffer = device.vad_buffer[self.vad.chunk_size:]
                                
                                if speech_prob < self.vad.vad_threshold:
                                    device.silence_counter += 1
                                    if device.silence_counter >= self.vad.silence_threshold:
                                        # Check minimum audio duration before saving
                                        audio_duration = len(device.audio_buffer) / (2 * 32000)  # 2 bytes/sample, 32kHz
                                        if audio_duration >= self.vad.min_audio_length:
                                            device.save_audio(str(int(time.time())))
                                            logger.info(f"Saved audio from {device.ip_address}")
                                        # Reset regardless of duration to avoid repeated triggers
                                        device.listening = False
                                        device.audio_buffer.clear()
                                        device.vad_buffer.clear()
                                        device.silence_counter = 0
                                else:
                                    device.silence_counter = 0
                                
                            
                            # await self.handle_wake_word_detection(device.ip_address)
                        device.clear_detection_buffer()
                            
                await asyncio.sleep(0.01)
                
            except Exception as e:
                logger.error(f"Error processing audio: {e}")
                await asyncio.sleep(0.1)

    def _resample_audio(self, audio_data):
        """Resample audio from 32kHz to 16kHz"""
        from scipy import signal
        return signal.resample(audio_data, len(audio_data) // 2)

    def save_audio_files(self):
        """Save the accumulated audio data to separate WAV files for each device"""
        saved_files = []
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        for device in self.devices.values():
            filename = device.save_audio(timestamp)
            if filename:
                saved_files.append(filename)
        
        return saved_files

    def stop(self):
        """Stop the UDP server and save the audio files"""
        logger.info("Stopping UDP server")
        self._running = False
        
        saved_files = self.save_audio_files()
        if saved_files:
            logger.info(f"Audio saved successfully to: {', '.join(saved_files)}")
        
        if self.socket:
            try:
                self.socket.close()
            except Exception as e:
                logger.error(f"Error closing UDP socket: {e}")
            self.socket = None
            
        if self.monitor_task:
            self.monitor_task.cancel()
        if self.receive_task:
            self.receive_task.cancel()
        if self.process_task:
            self.process_task.cancel()
        logger.info("UDP Server stopped")

async def main():
    server = None
    try:
        server = VoiceAssistantUDPServer()
        await server.start_server()
        await asyncio.gather(server.receive_task, server.process_task, return_exceptions=True)
    except KeyboardInterrupt:
        logger.info("Server shutdown requested")
    except Exception as e:
        logger.error(f"Critical error: {e}")
    finally:
        if server:
            server.stop()

if __name__ == "__main__":
    asyncio.run(main())