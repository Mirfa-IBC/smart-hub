from wyoming.client import AsyncTcpClient
from wyoming.info import Info, Satellite
from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.wake import Detection
from utils.logger import setup_logger
from config import WyomingConfig
import asyncio
import time
from typing import Optional

logger = setup_logger(__name__)

class WyomingClientWrapper:
    def __init__(self, config: WyomingConfig):
        self.config = config
        self.client: Optional[AsyncTcpClient] = None
        self.is_connected = False
        self.is_streaming = False
        self.stream_queue = asyncio.Queue(maxsize=50)

    async def connect(self) -> None:
        """Connect to Wyoming server"""
        try:
            self.client = AsyncTcpClient(self.config.host, self.config.port)
            await self.client.connect()
            await self.register_device()
            self.is_connected = True
            logger.info(f"Connected to Wyoming server at {self.config.host}:{self.config.port}")
        except Exception as e:
            logger.error(f"Wyoming connection error: {e}")
            self.is_connected = False
            raise

    async def disconnect(self) -> None:
        """Disconnect from Wyoming server"""
        if self.client:
            try:
                await self.client.disconnect()
                self.is_connected = False
                logger.info("Disconnected from Wyoming server")
            except Exception as e:
                logger.error(f"Error disconnecting from Wyoming: {e}")

    async def register_device(self) -> None:
        """Register device with Wyoming server"""
        if not self.client:
            return

        try:
            await self.client.write_event(
                Info(
                    satellite=Satellite(
                        name=self.config.device_name,
                        attribution={"name": "", "url": ""},
                        installed="",
                        description="Integrated Voice Assistant",
                        version="1.0"
                    )
                ).event()
            )
            logger.info(f"Device registered: {self.config.device_name}")
        except Exception as e:
            logger.error(f"Error registering device: {e}")
            self.is_connected = False
            raise

    async def send_wake_detection(self, wake_word: str, score: float) -> None:
        """Send wake word detection event"""
        if not self.client:
            return

        try:
            detection = Detection(
                name=wake_word,
                timestamp=time.time(),
                speaker=self.config.device_name
            ).event()
            await self.client.write_event(detection)
        except Exception as e:
            logger.error(f"Error sending wake detection: {e}")
            self.is_connected = False

    async def start_stream(self, sample_rate: int, width: int, channels: int) -> None:
        """Start audio stream"""
        if not self.client or self.is_streaming:
            return

        try:
            await self.client.write_event(AudioStart(
                rate=sample_rate,
                width=width,
                channels=channels
            ).event())
            self.is_streaming = True
            logger.info("Started audio stream")
        except Exception as e:
            logger.error(f"Error starting stream: {e}")
            self.is_connected = False

    async def stop_stream(self) -> None:
        """Stop audio stream"""
        if not self.is_streaming:
            return

        # Clear stream queue
        while not self.stream_queue.empty():
            try:
                self.stream_queue.get_nowait()
                self.stream_queue.task_done()
            except asyncio.QueueEmpty:
                break

        if self.client and self.is_connected:
            try:
                await self.client.write_event(AudioStop().event())
            except Exception as e:
                logger.error(f"Error sending audio stop event: {e}")
                self.is_connected = False

        self.is_streaming = False
        logger.info("Stopped audio stream")

    async def send_audio_chunk(self, audio_data: bytes, sample_rate: int, width: int, channels: int) -> None:
        """Send audio chunk to server"""
        if not self.client or not self.is_streaming:
            return

        try:
            await self.client.write_event(
                AudioChunk(
                    audio=audio_data,
                    rate=sample_rate,
                    width=width,
                    channels=channels
                ).event()
            )
        except Exception as e:
            logger.error(f"Error sending audio chunk: {e}")
            self.is_connected = False

    async def read_event(self):
        """Read event from Wyoming server"""
        if not self.client:
            return None
            
        try:
            return await self.client.read_event()
        except Exception as e:
            logger.error(f"Error reading Wyoming event: {e}")
            self.is_connected = False
            return None