import asyncio
import logging
import socket
import time
from datetime import datetime
from collections import defaultdict, deque
from dataclasses import dataclass
import numpy as np
import wave
from wake_word.detector import WakeWordDetector
from audio_processing.vad2 import VADProcessor
from audio_processing.transcribe import WhisperProcessor
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
    def __init__(self, host: str = '0.0.0.0', port: int = 12345):
        self.host = host
        self.port = port
        self.socket = None
        self._running = False
        self.devices = {}
        
        # Add timeout for forced audio save
        self.max_listening_duration = 10  # Maximum seconds to wait before forcing audio save
        
        # Initialize processors with proper error handling
        try:
            self.detector = WakeWordDetector(wake_word_model="alexa")
            self.transcriber = WhisperProcessor()
            self.vad = VADProcessor()
            
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
                            if speech_prob == 0.0:
                                device.silence_counter += 1
                                if device.silence_counter >= self.vad.silence_threshold:
                                    await self.handle_speech_end(device)
                                    break
                            else:
                                device.silence_counter = 0
                                transcript =  await self.transcriber.process_vad_chunk(vad_chunk)
                
                await asyncio.sleep(0.01)  # Reduced CPU usage
                
            except Exception as e:
                logger.error(f"Processing error: {e}")
                await asyncio.sleep(0.1)  # Back off on error

    async def handle_speech_end(self, device):
        """Handle end of speech with proper file handling"""
        try:
            audio_duration = len(device.audio_buffer) / (device.framerate * device.sample_width)
            
            if audio_duration >= self.vad.min_audio_length:
                logger.info("audio duration is fin")
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"audio_{device.ip_address}_{timestamp}.wav"
                
                with wave.open(filename, 'wb') as wf:
                    wf.setnchannels(device.channels)
                    wf.setsampwidth(device.sample_width)
                    wf.setframerate(device.framerate)
                    wf.writeframes(device.audio_buffer)
                
                logger.info(f"Saved audio from {device.ip_address}: {filename}")
                
                # Optional: Process with transcriber
                transcript =  await self.transcriber.process_audio('audio_192.168.1.157_20250208_001131.wav')
                # logger.info(f"Transcript: {transcript}")
            else:
                logger.info("audio duration is less ")
            
        except Exception as e:
            logger.error(f"Error handling speech end: {e}")
        
        finally:
            # Reset device state
            device.audio_buffer.clear()
            device.vad_cursor = 0
            device.state = 'DETECTING'
            device.listening = False
            device.silence_counter = 0
            device.detection_buffer.clear()

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
    
    server = VoiceAssistantUDPServer()
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