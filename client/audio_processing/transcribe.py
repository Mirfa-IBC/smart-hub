import numpy as np
import os
from typing import Dict, Set, Optional, Any
import torch
import traceback
from typing import Dict, List, Optional, Any
import logging
from faster_whisper import WhisperModel  # Add this import
import os
import os
logger = logging.getLogger(__name__)

class WhisperProcessor:

    def __init__(self, model_name: str = "distil-large-v3"):
        """Initialize Whisper with specified model"""
        logger.info(f"Loading Whisper model: {model_name}")
        download_dir = os.path.join(os.path.dirname(__file__), "models")
        logger.info(f" downloading models ${model_name} in ${download_dir}")
        num_threads = min(os.cpu_count(), 4)

        self.model = WhisperModel(model_name,device="cpu",compute_type="int8",download_root=download_dir,cpu_threads=num_threads)
        self.common_wake_words = ["alexa", "hey alexa", "ok google", "hey google", "siri", "hey siri","mirfa "]

    def _remove_wake_words(self, text: str) -> str:
        """Remove common wake words from transcription"""
        text_lower = text.lower()
        
        # Remove common wake words
        for wake_word in self.common_wake_words:
            if text_lower.startswith(wake_word):
                return text[len(wake_word):].strip()
        
        return text
    
    def process_audio(self, audio_filename: str) -> Optional[str]:
        """Transcribe audio file using local Whisper model with enhanced processing"""
        try:
            logger.info(f"Processing audio file with Whisper: {audio_filename}")
            
            # Transcribe with faster-whisper
            segments, info = self.model.transcribe(
                audio_filename,
                language="en",
                beam_size=5,
                best_of=5,
                vad_filter=False,
                initial_prompt="This is a smart home voice command."
            )
            
            # Get text from segments
            transcription = " ".join([segment.text for segment in segments]).strip()
            
            # Remove wake words from transcription
            cleaned_text = self._remove_wake_words(transcription)
            
            logger.info(f"Original transcription: {transcription}")
            logger.info(f"Cleaned transcription: {cleaned_text}")
            
            return cleaned_text
            
        except Exception as e:
            logger.error(f"Error in Whisper transcription: {e}")
            traceback.print_exc()
            return None
            
    def _remove_wake_words(self, text: str) -> str:
        """Remove common wake words from transcription"""
        text_lower = text.lower()
        
        # Remove common wake words
        for wake_word in self.common_wake_words:
            if text_lower.startswith(wake_word):
                return text[len(wake_word):].strip()
        
        return text
        

    def transcribe_audio(self, audio_buffer: bytearray) -> str:
        """Transcribe audio using Faster-Whisper"""
        try:
            # Convert bytearray to numpy array
            audio_np = np.frombuffer(audio_buffer, dtype=np.int16).astype(np.float32) / 32768.0

            # Resample to 16kHz (required by Whisper)
            from scipy import signal
            audio_resampled = signal.resample(audio_np, int(len(audio_np) * 16000 / 32000))

            # Transcribe using Faster-Whisper
            segments, _ = self.model.transcribe(audio_resampled, language="en")
            transcription = " ".join([segment.text for segment in segments])

            return transcription
        except Exception as e:
            logger.error(f"Error transcribing audio: {e}")
            return ""