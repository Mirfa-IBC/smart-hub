import numpy as np
from collections import deque
from wake_word.detector import WakeWordDetector
from utils.logger import setup_logger
from config import AudioConfig, WakeWordConfig
from typing import Optional, Callable, Coroutine, Any
import struct
import asyncio

logger = setup_logger(__name__)

class AudioProcessor:
    def __init__(
        self,
        audio_config: AudioConfig,
        wake_word_config: WakeWordConfig,
        on_wake_word: Optional[Callable[[float], Coroutine[Any, Any, None]]] = None
    ):
        self.audio_config = audio_config
        self.wake_word_config = wake_word_config
        self.on_wake_word = on_wake_word
        
        # Initialize audio buffer (500ms buffer at 16kHz)
        self.audio_buffer = deque(maxlen=50)
        
        # Initialize wake word detector
        self.detector = WakeWordDetector(
            wake_word_model=wake_word_config.wake_word,
            model_path=wake_word_config.model_path
        )
        
        # State management
        self.is_streaming = False
        self.audio_chunks = 0
        
        logger.info(f"Audio processor initialized with wake word: {wake_word_config.wake_word}")

    async def process_audio(self, data: bytes) -> np.ndarray:
        """Process incoming audio data"""
        try:
            # Convert incoming data to numpy array regardless of streaming state
            audio_data = np.frombuffer(data, dtype=np.int16)
            
            if not self.is_streaming:
                return audio_data
            
            # Get the number of samples in this chunk
            num_samples = len(data) // 2  # 2 bytes per sample for int16
            
            # Log stats periodically
            if self.audio_chunks % 100 == 0:
                logger.debug(f"Chunk size: {len(data)} bytes, {num_samples} samples")
                if len(audio_data) > 0:
                    logger.debug(f"Sample values - Min: {np.min(audio_data)}, Max: {np.max(audio_data)}")
            
            # Process audio in float32
            audio_float = audio_data.astype(np.float32) / 32767.0
            audio_float = np.clip(audio_float, -1.0, 1.0)
            
            # Add to buffer
            self.audio_buffer.append(audio_float)
            
            # Process buffer if we have enough data
            if len(self.audio_buffer) >= self.audio_buffer.maxlen:
                # Process buffer as a single numpy array
                buffer_data = np.concatenate(list(self.audio_buffer))
                self.audio_buffer.clear()
                
                # Convert to int16 for wake word detection
                audio_int16 = (buffer_data * 32767).astype(np.int16)
                
                # Check for wake word
                if self.detector.detect(audio_int16):
                    logger.info("Wake word detected!")
                    if self.on_wake_word:
                        await self.on_wake_word(0.75)
                
                self.audio_chunks += 1
                return audio_int16
            
            self.audio_chunks += 1
            return audio_data
            
        except Exception as e:
            logger.error(f"Error processing audio: {e}", exc_info=True)
            return np.array([], dtype=np.int16)

    async def start_streaming(self):
        """Start audio streaming"""
        self.is_streaming = True
        self.audio_buffer.clear()
        self.audio_chunks = 0
        logger.info("Started audio streaming")

    async def stop_streaming(self):
        """Stop audio streaming"""
        self.is_streaming = False
        self.audio_buffer.clear()
        logger.info("Stopped audio streaming")