from aioesphomeapi import APIClient
from aioesphomeapi.model import VoiceAssistantAudioSettings
from utils.logger import setup_logger
from config import ESPHomeConfig
from typing import Callable, Optional, Coroutine, Any
import asyncio
import logging
import time

# Set up logging with more detailed format
logger = setup_logger(__name__)
logging.getLogger('aioesphomeapi.connection').setLevel(logging.INFO)
logging.getLogger('aioesphomeapi._frame_helper.base').setLevel(logging.INFO)

class ESPHomeClientWrapper:
    def __init__(self, config: ESPHomeConfig):
        self.config = config
        logger.debug(f"Initializing ESPHomeClientWrapper with host={config.host}, port={config.port}")
        
        self.client = APIClient(
            config.host, 
            config.port, 
            config.encryption_key, 
            noise_psk=config.encryption_key
        )
        self.is_connected = False
        self._lock = asyncio.Lock()
        self._connect_time = None
        logger.info(f"ESPHomeClientWrapper initialized for {config.host}:{config.port}")

    async def connect(self) -> None:
        """Connect to ESPHome device if not already connected"""
        async with self._lock:
            if self.is_connected:
                logger.debug("Already connected to ESPHome device, skipping connection")
                return
                
            logger.info(f"Attempting to connect to ESPHome device at {self.config.host}:{self.config.port}")
            try:
                connect_start = time.time()
                await self.client.connect(login=True)
                connect_duration = time.time() - connect_start
                logger.info(f"Connected to ESPHome device in {connect_duration:.2f} seconds")
                
                device_info = await self.client.device_info()
                logger.info(
                    f"Device Information:\n"
                    f"  Name: {device_info.name}\n"
                    f"  ESPHome Version: {device_info}\n"
                    f"  Device Version: {device_info}\n"
                    f"  Compilation Time: {device_info.compilation_time}"
                )
                
                self.is_connected = True
                self._connect_time = time.time()
                logger.debug("Connection state updated to connected")
                
            except Exception as e:
                logger.error(
                    f"ESPHome connection failed: {str(e)}\n"
                    f"Host: {self.config.host}\n"
                    f"Port: {self.config.port}",
                    exc_info=True
                )
                self.is_connected = False
                self._connect_time = None
                raise

    async def disconnect(self) -> None:
        """Disconnect from ESPHome device if connected"""
        async with self._lock:
            if not self.is_connected:
                logger.debug("Already disconnected from ESPHome device, skipping disconnection")
                return
                
            logger.info(f"Attempting to disconnect from ESPHome device at {self.config.host}:{self.config.port}")
            try:
                disconnect_start = time.time()
                await self.client.disconnect()
                disconnect_duration = time.time() - disconnect_start
                
                self.is_connected = False
                uptime = time.time() - self._connect_time if self._connect_time else 0
                self._connect_time = None
                
                logger.info(
                    f"Disconnected from ESPHome device:\n"
                    f"  Disconnect duration: {disconnect_duration:.2f} seconds\n"
                    f"  Session uptime: {uptime:.2f} seconds"
                )
                
            except Exception as e:
                logger.error(
                    f"Error disconnecting from ESPHome device: {str(e)}\n"
                    f"Host: {self.config.host}\n"
                    f"Port: {self.config.port}",
                    exc_info=True
                )
                raise

    def subscribe_voice_assistant(
        self,
        handle_audio: Callable[[bytes], Coroutine[Any, Any, None]],
        handle_start: Optional[Callable[[], Coroutine[Any, Any, None]]] = None,
        handle_stop: Optional[Callable[[], Coroutine[Any, Any, None]]] = None
    ) -> None:
        """
        Subscribe to voice assistant events
        
        Args:
            handle_audio: Coroutine to handle received audio data
            handle_start: Optional coroutine to handle start events
            handle_stop: Optional coroutine to handle stop events
            
        Raises:
            RuntimeError: If not connected to ESPHome device
        """
        if not self.is_connected:
            logger.error("Cannot subscribe to voice assistant: Not connected to ESPHome device")
            raise RuntimeError("Not connected to ESPHome device")
            
        logger.info("Attempting to subscribe to voice assistant events")
        try:
            # Wrap handlers to add logging
            async def logged_handle_start():
                logger.info("Voice assistant recording started")
                if handle_start:
                    await handle_start()
                    
            async def logged_handle_stop():
                logger.info("Voice assistant recording stopped")
                if handle_stop:
                    await handle_stop()
                    
            async def logged_handle_audio(audio_data: bytes):
                logger.debug(f"Received audio data: {len(audio_data)} bytes")
                await handle_audio(audio_data)
            
            self.client.subscribe_voice_assistant(
                handle_start=logged_handle_start,
                handle_stop=logged_handle_stop,
                handle_audio=logged_handle_audio
            )
            logger.info(
                f"Successfully subscribed to voice assistant events on {self.config.host}:\n"
                f"  Audio handler: {handle_audio.__name__}\n"
                f"  Start handler: {handle_start.__name__ if handle_start else 'None'}\n"
                f"  Stop handler: {handle_stop.__name__ if handle_stop else 'None'}"
            )
            
        except Exception as e:
            logger.error(
                f"Error subscribing to voice assistant events: {str(e)}\n"
                f"Host: {self.config.host}\n"
                f"Port: {self.config.port}",
                exc_info=True
            )
            raise

    @property
    def connected(self) -> bool:
        """Check if client is connected to ESPHome device"""
        return self.is_connected

    @property
    def uptime(self) -> Optional[float]:
        """Get the connection uptime in seconds, or None if not connected"""
        if self._connect_time and self.is_connected:
            return time.time() - self._connect_time
        return None