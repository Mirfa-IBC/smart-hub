import asyncio
from typing import Optional
import uuid
from  utils.logger import setup_logger
from config import AppConfig
from clients.esphome_client import ESPHomeClientWrapper
from clients.wyoming_client import WyomingClientWrapper
from .audio_processor import AudioProcessor
from aioesphomeapi.model import VoiceAssistantAudioSettings
import time
logger = setup_logger(__name__)

class VoiceAssistant:
    def __init__(self, config: AppConfig):
        self.config = config
        self.conversation_id: Optional[str] = None
        self.is_running = False
        
        # Initialize clients
        self.esphome_client = ESPHomeClientWrapper(config.esphome)
        self.wyoming_client = WyomingClientWrapper(config.wyoming)
        
        # Initialize audio processor
        self.audio_processor = AudioProcessor(
            audio_config=config.audio,
            wake_word_config=config.wake_word,
            on_wake_word=self.handle_wake_word
        )

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
        
        self.conversation_id = conversation_id or str(uuid.uuid4())
        self.is_running = True
        
        return 0  # No port needed since we're not using UDP

    async def handle_pipeline_stop(self, server_side: bool) -> None:
        """Handle the stop of audio streaming"""
        logger.info(f"Voice assistant stopped streaming (server_side: {server_side})")
        await self.handle_pipeline_finished()

    async def handle_pipeline_finished(self):
        """Handle the completion of a voice assistant pipeline"""
        logger.info("Voice assistant pipeline finished")
        await self.wyoming_client.stop_stream()
        self.conversation_id = None
        self.is_running = False

    async def handle_audio(self, audio_data: bytes) -> None:
        """Handle incoming audio data from ESPHome device"""
        
        try:
            # Initialize counters if needed
            # if not hasattr(self, '_audio_stats'):
            #     self._audio_stats = {
            #         'chunks_received': 0,
            #         'bytes_received': 0,
            #         'last_log_time': 0,
            #         'streaming_chunks': 0
            #     }
            
            # # Update stats
            # self._audio_stats['chunks_received'] += 1
            # self._audio_stats['bytes_received'] += len(audio_data)
            
            # # Log stats every second
            # current_time = time.time()
            # if current_time - self._audio_stats['last_log_time'] >= 1.0:
            #     logger.debug(
            #         f"Audio stats - Chunks: {self._audio_stats['chunks_received']}, "
            #         f"Bytes: {self._audio_stats['bytes_received']}, "
            #         f"Avg chunk size: {self._audio_stats['bytes_received'] / max(1, self._audio_stats['chunks_received']):.1f} bytes"
            #     )
            #     # Reset counters
            #     self._audio_stats['chunks_received'] = 0
            #     self._audio_stats['bytes_received'] = 0
            #     self._audio_stats['last_log_time'] = current_time
            
            # # Validate audio data
            # if not audio_data or len(audio_data) == 0:
            #     logger.warning("Received empty audio data")
            #     return
            
            # # Check if chunk size is as expected (2 bytes per sample)
            # expected_chunk_size = 2 * (self.config.audio.sample_rate // 50)  # 20ms chunks
            # if len(audio_data) != expected_chunk_size:
            #     logger.warning(f"Unexpected chunk size: {len(audio_data)} bytes (expected {expected_chunk_size})")
            
            # Process audio
            processed_audio = await self.audio_processor.process_audio(audio_data)
            
            # Handle processed audio
            if processed_audio.size > 0:
                # Get audio processor stats
                # audio_stats = self.audio_processor.get_stats()
                
                # # Log detailed stats periodically
                # if audio_stats['chunks_processed'] % 100 == 0:
                #     logger.debug(
                #         f"Audio processing stats - Buffer: {audio_stats['buffer_size']}, "
                #         f"Max amplitude: {audio_stats['last_max_amplitude']}, "
                #         f"Silence counter: {audio_stats['silence_counter']}"
                #     )
                logger.info("here in process audio")
                
                # Send to Wyoming server if streaming
                if self.wyoming_client.is_streaming and self.wyoming_client.is_connected:
                    # self._audio_stats['streaming_chunks'] += 1
                    await self.wyoming_client.send_audio_chunk(
                        processed_audio.tobytes(),
                        self.config.audio.sample_rate,
                        self.config.audio.sample_width,
                        self.config.audio.channels
                    )
                    
                    # Log streaming stats
                    # if self._audio_stats['streaming_chunks'] % 100 == 0:
                    #     logger.debug(f"Streaming stats - Chunks sent: {self._audio_stats['streaming_chunks']}")
        
        except Exception as e:
            logger.error(f"Error handling audio data: {e}", exc_info=True)

    async def handle_wake_word(self, score: float):
        """Handle wake word detection"""
        try:
            if not self.wyoming_client.is_connected:
                logger.warning("Not connected to Wyoming server, can't handle wake word")
                return
            
            logger.info("Handling wake word detection...")
            
            # Send detection event
            await self.wyoming_client.send_wake_detection(
                self.config.wake_word.wake_word,
                score
            )
            
            # Start streaming
            await self.wyoming_client.start_stream(
                self.config.audio.sample_rate,
                self.config.audio.sample_width,
                self.config.audio.channels
            )
            
        except Exception as e:
            logger.error(f"Handle wake word error: {e}")
            self.wyoming_client.is_streaming = False
            self.wyoming_client.is_connected = False

    async def process_wyoming_events(self):
        """Process events from Wyoming server"""
        while self.is_running:
            if self.wyoming_client.is_connected:
                event = await self.wyoming_client.read_event()
                if event and event.type == 'audio-stop':
                    await self.wyoming_client.stop_stream()
            await asyncio.sleep(0.1)

    async def connect(self):
        """Connect to both ESPHome and Wyoming servers"""
        try:
            logger.info("Starting connection process...")
            
            # Connect to ESPHome
            logger.info(f"Connecting to ESPHome device at {self.config.esphome.host}:{self.config.esphome.port}")
            try:
                await self.esphome_client.connect()
            except Exception as e:
                logger.error(f"Failed to connect to ESPHome: {e}", exc_info=True)
                raise
            
            # Subscribe to voice assistant events
            logger.info("Setting up voice assistant event subscriptions...")
            try:
                self.esphome_client.subscribe_voice_assistant(
                    handle_start=self.handle_pipeline_start,
                    handle_stop=self.handle_pipeline_stop,
                    handle_audio=self.handle_audio
                )
            except Exception as e:
                logger.error(f"Failed to subscribe to voice assistant events: {e}", exc_info=True)
                raise
            
            # Connect to Wyoming server
            logger.info(f"Connecting to Wyoming server at {self.config.wyoming.host}:{self.config.wyoming.port}")
            try:
                await self.wyoming_client.connect()
            except Exception as e:
                logger.error(f"Failed to connect to Wyoming server: {e}", exc_info=True)
                raise
            
            self.is_running = True
            logger.info("✅ Voice assistant fully connected and ready")
            
        except Exception as e:
            logger.error(f"❌ Connection failed: {e}", exc_info=True)
            await self.disconnect()
            raise

    async def disconnect(self):
        """Disconnect from both servers"""
        self.is_running = False
        
        # Stop streaming if active
        if self.wyoming_client.is_streaming:
            await self.wyoming_client.stop_stream()
        
        # Disconnect from both servers
        await self.wyoming_client.disconnect()
        await self.esphome_client.disconnect()
        
        logger.info("Voice assistant disconnected")

    async def run(self):
        """Main run loop"""
        try:
            # Connect to services
            await self.connect()
            
            # Start audio processing
            await self.audio_processor.start_streaming()
            
            # Start Wyoming event processing
            wyoming_task = asyncio.create_task(self.process_wyoming_events())
            
            # Keep running until stopped
            while self.is_running:
                await asyncio.sleep(1)
                
                # Check Wyoming connection and reconnect if needed
                if not self.wyoming_client.is_connected:
                    logger.info("Wyoming connection lost, attempting to reconnect...")
                    try:
                        await self.wyoming_client.connect()
                    except Exception as e:
                        logger.error(f"Wyoming reconnection failed: {e}")
                
                # Check ESPHome connection and reconnect if needed
                if not self.esphome_client.is_connected:
                    logger.info("ESPHome connection lost, attempting to reconnect...")
                    try:
                        await self.connect()
                    except Exception as e:
                        logger.error(f"ESPHome reconnection failed: {e}")
            
            # Cancel Wyoming event processing
            wyoming_task.cancel()
            try:
                await wyoming_task
            except asyncio.CancelledError:
                pass
                
        except asyncio.CancelledError:
            logger.info("Shutting down...")
        except Exception as e:
            logger.error(f"Error in run loop: {e}")
        finally:
            # Stop audio processing
            await self.audio_processor.stop_streaming()
            await self.disconnect()