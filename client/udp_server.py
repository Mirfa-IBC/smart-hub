import asyncio
import logging
import socket
import time
import backoff
import wave
from datetime import datetime
from collections import defaultdict,deque
import numpy as np
from wake_word.detector import WakeWordDetector

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class VoiceAssistantUDPServer:
    def __init__(self, host: str = '0.0.0.0', port: int = 12345, max_retries: int = 3):
        self.host = host
        self.port = port
        self.base_port = port
        self.socket = None
        self._running = False
        self.last_packet_time = None
        self.packets_received = 0
        self.audio_callback = None
        self.max_retries = max_retries
        self.connection_attempts = 0
        self.last_error_time = 0
        self.error_threshold = 5
        self.error_count = 0
        self.last_error_reset = time.time()
        self.monitor_task = None
        self.receive_task = None
        # self.detection_buffers = defaultdict(lambda: deque(maxlen=50))  # Processing buffer per IP
# 
        self.detector = WakeWordDetector(wake_word_model="alexa")
        # self.detector = WakeWordDetector(wake_word_model="mirfa",model_path="/Users/naveenjain/Documents/code/mirfa/custom_wake_word/my_model/mirfa.onnx")
        self.detector.download_models();

        # Audio configuration - matched to incoming 32kHz audio
        self.audio_buffers = defaultdict(bytearray)
        # self.audio_buffer = deque(maxlen=50)  #500ms buffer
        self.detection_buffers = defaultdict(lambda: deque(maxlen=50))
        self.sample_width = 2      # 16-bit audio
        self.channels = 1          # mono
        self.framerate = 32000     # Matching incoming audio rate
        self.buffer_size = 1280    # Smaller buffer for better handling

    async def start_server(self):
        while self.connection_attempts < self.max_retries:
            try:
                current_port = self.base_port + self.connection_attempts
                logger.info(f"Attempting to start UDP server on {self.host}:{current_port}")
                
                self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 65536 * 4)  # Increased buffer
                
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
        """Continuously receive UDP packets and store audio data per IP"""
        logger.info("Starting UDP receive loop")
        
        while self._running and self.socket:
            try:
                loop = asyncio.get_event_loop()
                data, addr = await loop.sock_recvfrom(self.socket, self.buffer_size)
                
                self.last_packet_time = time.time()
                self.packets_received += 1
                
                # Store the received audio data for this IP
                ip_address = addr[0]
                
                self.audio_buffers[ip_address].extend(data)

                audio_chunk = np.frombuffer(data, dtype=np.int16)
                audio_chunk = np.clip(audio_chunk, -32768, 32767).astype(np.int16)
                self.detection_buffers[ip_address].append(audio_chunk)

            except (BlockingIOError, InterruptedError):
                await asyncio.sleep(0.001)
            except ConnectionError as e:
                logger.error(f"Connection error in receive loop: {e}")
                raise
            except Exception as e:
                logger.error(f"Unexpected error in receive loop: {e}")
                await asyncio.sleep(0.1)

    def save_audio_files(self):
        """Save the accumulated audio data to separate WAV files for each IP"""
        saved_files = []
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        for ip_address, buffer in self.audio_buffers.items():
            if len(buffer) > 0:
                filename = f"captured_audio_{ip_address}_{timestamp}.wav"
                
                try:
                    logger.info(f"Saving audio file for {ip_address}, buffer size: {len(buffer)} bytes")
                    with wave.open(filename, 'wb') as wave_file:
                        wave_file.setnchannels(self.channels)
                        wave_file.setsampwidth(self.sample_width)
                        wave_file.setframerate(self.framerate)
                        wave_file.writeframes(buffer)
                    
                    logger.info(f"Audio from {ip_address} saved to {filename}")
                    saved_files.append(filename)
                except Exception as e:
                    logger.error(f"Error saving audio file for {ip_address}: {e}")
            else:
                logger.warning(f"No audio data to save for {ip_address}")
        
        return saved_files

    def stop(self):
        """Stop the UDP server and save the audio files"""
        logger.info("Stopping UDP server")
        self._running = False
        
        # Save all audio files before closing
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
        logger.info("UDP Server stopped")

    async def process_audio_loop(self):
        """Process audio chunks for wake word detection"""
        logger.info("Starting audio processing loop")
        
        while self._running:
            try:
                for ip_address, buffer in self.detection_buffers.items():
                    if len(buffer) > 0:
                        # Concatenate audio chunks
                        audio_data = np.concatenate(list(buffer))

                        
                        buffer.clear()
                        
                        # Resample from 32kHz to 16kHz for wake word detection
                        # resampled_audio = self._resample_audio(audio_data)
                        
                        # Check for wake word
                        resampled_audio = self._resample_audio(audio_data)
                        # logger.info("checking detection")
                        if self.detector.detect(resampled_audio,ip_address):
                            logger.info(f"Wake word detected from {ip_address}!")
                            # await self.handle_wake_word_detection(ip_address)
                            
                await asyncio.sleep(0.01)
                
            except Exception as e:
                logger.error(f"Error processing audio: {e}")
                await asyncio.sleep(0.1)

    def _resample_audio(self, audio_data):
        """Resample audio from 32kHz to 16kHz"""
        # Simple decimation (taking every other sample)
        """Better resampling using scipy"""
        from scipy import signal
        return signal.resample(audio_data, len(audio_data) // 2)
    

async def main():
    server = None
    try:
        server = VoiceAssistantUDPServer()
        await server.start_server()
        # Wait for the server tasks to complete or until interrupted
        await asyncio.gather(server.receive_task,server.process_task, return_exceptions=True)
    except KeyboardInterrupt:
        logger.info("Server shutdown requested")
    except Exception as e:
        logger.error(f"Critical error: {e}")
    finally:
        if server:
            server.stop()

if __name__ == "__main__":
    asyncio.run(main())