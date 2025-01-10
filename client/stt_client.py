import asyncio
import numpy as np
import sounddevice as sd
import json
import time
import uuid
import argparse
from wyoming.client import AsyncTcpClient
from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.wake import Detection
from wyoming.info import Info, Satellite
import threading
from typing import Optional
from wake_word.detector import WakeWordDetector
import logging
from collections import deque
import numpy as np

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class WakeWordClient:
    def __init__(
        self,
        server_host: str = "192.168.11.99",
        server_port: int = 10200,
        device_name: Optional[str] = None,
        group: Optional[str] = None,
        wake_word: str = "alexa",
        model_path: Optional[str] = None
    ):
        # Client settings
        self.server_host = server_host
        self.server_port = server_port
        self.device_name = device_name or f"Device_{uuid.uuid4().hex[:8]}"
        self.group = group
        self.wake_word = wake_word
        
        # Initialize the wake word detector
        self.detector = WakeWordDetector(wake_word_model=wake_word,model_path=model_path)
        logger.info(f"Wake word detector initialized for {wake_word}")
        
        # Audio handling
        self.sample_rate = 16000
        self.chunk_size = 320  # 20ms at 16kHz
        self.audio_buffer = deque(maxlen=50)  # 500ms buffer
        self.stream = None
        
        # State management
        self.is_running = False
        self.is_streaming = False
        self.client = None
        self.writer = None  # TCP connection writer
        self.loop = None
        self.audio_process_task = None
        self.connection_monitor_task = None
        self.last_process_time = 0
        self.is_connected = False
        
        # Connection management
        self.reconnect_delay = 1.0
        self.max_reconnect_delay = 30.0
        self.connection_check_interval = 5.0
        
        # Create asyncio queue for streaming
        self.stream_queue = asyncio.Queue(maxsize=50)

    def audio_callback(self, indata, frames, time_info, status):
        """Minimal processing in audio callback"""
        if status:
            logger.warning(f"Audio callback status: {status}")
            return
            
        try:
            # Convert to mono and add to buffer
            audio_chunk = indata[:, 0]
            audio_chunk = np.clip(audio_chunk, -1.0, 1.0)
            self.audio_buffer.append(audio_chunk)
            
        except Exception as e:
            logger.error(f"Error in audio callback: {e}", exc_info=True)

    async def process_audio(self):
        """Process audio chunks asynchronously"""
        while self.is_running:
            try:
                if len(self.audio_buffer) > 0:
                    # Process all available chunks
                    audio_data = np.concatenate(list(self.audio_buffer))
                    self.audio_buffer.clear()
                    
                    # Convert to int16 once
                    audio_int16 = (audio_data * 32767).astype(np.int16)
                    
                    # Check for wake word
                    if not self.is_streaming and self.detector.detect(audio_int16):
                        logger.info("Wake word detected!")
                        await self.handle_wake_word(0.75)
                    
                    # If streaming, add to stream queue
                    if self.is_streaming and self.is_connected:
                        await self.stream_queue.put(audio_int16)
                        
                await asyncio.sleep(0.01)
                    
            except Exception as e:
                logger.error(f"Error processing audio: {e}", exc_info=True)

    async def monitor_connection(self):
        """Monitor connection status and attempt reconnection if needed"""
        while self.is_running:
            try:
                if not self.is_connected:
                    logger.info("Connection lost, attempting to reconnect...")
                    await self.reconnect()
                await asyncio.sleep(self.connection_check_interval)
            except Exception as e:
                logger.error(f"Error in connection monitor: {e}")
                self.is_connected = False
                await asyncio.sleep(1)

    async def reconnect(self):
        """Handle reconnection logic"""
        if self.is_streaming:
            await self.stop_stream()
        
        # Close existing client if any
        if self.client:
            try:
                await self.client.disconnect()  # Using disconnect() instead of close()
            except Exception as e:
                logger.error(f"Error disconnecting client: {e}")
            self.client = None
        
        self.is_connected = False
        
        try:
            success = await self.connect()
            if success:
                logger.info("Successfully reconnected")
                await self.register_device()
                self.is_connected = True
                self.reconnect_delay = 1.0
            else:
                logger.error("Failed to reconnect")
                self.reconnect_delay = min(
                    self.reconnect_delay * 2,
                    self.max_reconnect_delay
                )
        except Exception as e:
            logger.error(f"Reconnection error: {e}")
            self.reconnect_delay = min(
                self.reconnect_delay * 2,
                self.max_reconnect_delay
            )

    async def connect(self) -> bool:
        """Connect to Wyoming server"""
        try:
            self.client = AsyncTcpClient(self.server_host, self.server_port)
            logger.info("Connecting...")
            await self.client.connect()
            logger.info("Connected")
            return True
        except Exception as e:
            logger.error(f"Connection error: {e}")
            return False

    async def register_device(self):
        """Register device with server"""
        try:
            await self.client.write_event(
                Info(
                    satellite=Satellite(
                        name=self.device_name,
                        attribution={"name": "", "url": ""},
                        installed="",
                        description="Wake Word Detection Client",
                        version="1.0"
                    )
                ).event()
            )
            logger.info(f"Device registered: {self.device_name}")
        except Exception as e:
            logger.error(f"Error registering device: {e}")
            self.is_connected = False
            raise

    async def handle_wake_word(self, score: float):
        """Handle wake word detection"""
        try:
            if not self.is_connected:
                logger.warning("Not connected, can't handle wake word")
                return
                
            logger.info("Handling wake word detection...")
            await self.send_detection(score)
            await self.start_stream()
            
        except Exception as e:
            logger.error(f"Handle wake word error: {e}", exc_info=True)
            self.is_streaming = False
            self.is_connected = False

    async def send_detection(self, score: float):
        """Send wake word detection event"""
        detection = Detection(
            name=self.wake_word,
            timestamp=time.time(),
            speaker=self.device_name
        ).event()
        await self.client.write_event(detection)

    async def stream_audio_task(self):
        """Dedicated task for streaming audio"""
        while self.is_streaming and self.is_connected:
            try:
                try:
                    audio_data = await asyncio.wait_for(
                        self.stream_queue.get(),
                        timeout=1.0
                    )
                except asyncio.TimeoutError:
                    continue

                if not self.is_connected:
                    break

                audio_bytes = audio_data.tobytes()
                await self.client.write_event(
                    AudioChunk(
                        audio=audio_bytes,
                        rate=self.sample_rate,
                        width=2,
                        channels=1
                    ).event()
                )
                
                self.stream_queue.task_done()
                
            except Exception as e:
                logger.error(f"Error streaming audio: {e}", exc_info=True)
                self.is_connected = False
                await self.stop_stream()
                break

    async def start_stream(self):
        """Start audio stream to server"""
        if not self.is_streaming and self.is_connected:
            await self.client.write_event(AudioStart(
                rate=self.sample_rate,
                width=2,
                channels=1
            ).event())
            self.is_streaming = True
            # Start dedicated streaming task
            asyncio.create_task(self.stream_audio_task())
            logger.info("Started audio stream")

    async def stop_stream(self):
        """Stop audio stream"""
        if self.is_streaming:
            self.is_streaming = False
            # Clear stream queue
            while not self.stream_queue.empty():
                try:
                    self.stream_queue.get_nowait()
                    self.stream_queue.task_done()
                except asyncio.QueueEmpty:
                    break
            
            if self.is_connected:
                try:
                    await self.client.write_event(AudioStop().event())
                except Exception as e:
                    logger.error(f"Error sending audio stop event: {e}")
                    
            logger.info("Stopped audio stream")

    async def process_server_event(self, event):
        """Process events from server"""
        try:
            if event.type == 'audio-stop':
                logger.info("Received stop streaming command from server")
                await self.stop_stream()
        except Exception as e:
            logger.error(f"Error processing server event: {e}")
            self.is_connected = False

    async def start(self):
        """Start the client"""
        self.loop = asyncio.get_running_loop()
        self.is_running = True

        # Initial connection and registration
        success = await self.connect()
        if success:
            await self.register_device()
            self.is_connected = True
        
        # Start connection monitor
        self.connection_monitor_task = asyncio.create_task(self.monitor_connection())

        # Start audio processing task
        self.audio_process_task = asyncio.create_task(self.process_audio())

        # Start audio capture
        self.stream = sd.InputStream(
            channels=1,
            samplerate=self.sample_rate,
            callback=self.audio_callback,
            blocksize=self.chunk_size,
            latency='low'
        )
        self.stream.start()

        # Main event loop
        while self.is_running:
            try:
                if self.is_connected:
                    event = await self.client.read_event()
                    if event:
                        await self.process_server_event(event)
                else:
                    await asyncio.sleep(1)
            except Exception as e:
                logger.error(f"Event loop error: {e}")
                self.is_connected = False
            await asyncio.sleep(0.1)

    async def stop(self):
        """Stop the client"""
        self.is_running = False
        
        # Cancel all tasks
        for task in [self.audio_process_task, self.connection_monitor_task]:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        
        # Stop streaming
        if self.is_streaming:
            await self.stop_stream()
        
        # Close audio stream
        if self.stream:
            self.stream.stop()
            self.stream.close()
        
        # Disconnect client
        if self.client:
            try:
                await self.client.disconnect()  # Using disconnect() instead of close()
            except Exception as e:
                logger.error(f"Error disconnecting client: {e}")
        
        logger.info("Client stopped")

def create_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Wake Word Client")
    parser.add_argument("--host", default="192.168.11.99", help="Server host address")
    parser.add_argument("--port", type=int, default=10200, help="Server port number")
    parser.add_argument("--name", help="Device name")
    parser.add_argument("--group", help="Group name")
    parser.add_argument("--wake-word", default="alexa", help="Wake word to detect")
    return parser

async def main():
    parser = create_argparser()
    args = parser.parse_args()

    client = WakeWordClient(
        server_host=args.host,
        server_port=args.port,
        device_name=args.name,
        group=args.group,
        wake_word=args.wake_word
    )

    try:
        await client.start()
    except KeyboardInterrupt:
        logger.info("\nShutting down...")
        await client.stop()
    except Exception as e:
        logger.error(f"Error: {e}")
        await client.stop()

if __name__ == "__main__":
    asyncio.run(main())