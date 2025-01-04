import asyncio
import openai
import numpy as np
from wyoming.server import AsyncTcpServer
from wyoming.info import Info
from wyoming.audio import AudioChunk, AudioStart, AudioStop
from wyoming.wake import Detection
import os
from dataclasses import dataclass
from typing import Dict, Set, Optional, Any
import uuid
import json
from wyoming.server import AsyncEventHandler
from wyoming.event import Event
import torch
from collections import deque
from dataclasses import dataclass,field
import time
import wave
import traceback
from typing import Dict, List, Optional, Any
import whisper

import aiohttp
from wyoming.event import Event, async_write_event
import websockets
import logging
import os
logger = logging.getLogger(__name__)
class WhisperProcessor:
    def __init__(self, model_name: str = "large-v2"):
        """Initialize Whisper with specified model"""
        logger.info(f"Loading Whisper model: {model_name}")
        download_dir = os.path.join(os.path.dirname(__file__), "models")
        logger.info(f" downloading models ${model_name} in ${download_dir}")
        self.model = whisper.load_model(model_name,download_root=download_dir)
        self.common_wake_words = ["alexa", "hey alexa", "ok google", "hey google", "siri", "hey siri"]

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
            
            # Use more aggressive settings for better transcription
            result = self.model.transcribe(
                audio_filename,
                language="en",
                temperature=0.2,
                initial_prompt="This is a smart home voice command for controlling lights and switches.",
                condition_on_previous_text=True,
                fp16=False
            )
            
            transcription = result["text"].strip()
            
            # Remove wake words from transcription
            cleaned_text = self._remove_wake_words(transcription)
            
            logger.info(f"Original transcription: {transcription}")
            logger.info(f"Cleaned transcription: {cleaned_text}")
            
            return cleaned_text
            
        except Exception as e:
            logger.info(f"Error in Whisper transcription: {e}")
            traceback.print_exc()
            return None
        
class VADProcessor:
    def __init__(self):
        cache_dir = os.path.join(os.path.dirname(__file__), "models", "torch_cache")
        # os.makedirs(cache_dir, exist_ok=True)
        os.environ['TORCH_HOME'] = cache_dir
        logger.info(f"Downloading models silero_vad in {cache_dir}")
        self.vad_model, _ = torch.hub.load(
            repo_or_dir='snakers4/silero-vad',
            model='silero_vad',
            force_reload=True,
            trust_repo=True,
            model_dir=cache_dir
        )
        self.sample_rate = 16000
        self.vad_threshold = 0.3
        self.silence_threshold = 15
        self.chunk_size = 512
        self.min_audio_length = 1.0  # Minimum audio length in seconds
        self.max_audio_length = 30.0  # Maximum audio length in seconds

    def process_chunk(self, audio_chunk: np.ndarray) -> float:
        try:
            # Ensure audio is the right shape and type
            if len(audio_chunk.shape) == 1:
                audio_chunk = audio_chunk.reshape(1, -1)
            
            # Convert to torch tensor
            audio_tensor = torch.tensor(audio_chunk).float()
            
            # Get speech probability
            with torch.no_grad():
                speech_prob = self.vad_model(audio_tensor, self.sample_rate).item()
            
            return speech_prob
            
        except Exception as e:
            logger.info(f"Error in VAD processing: {e}")
            import traceback
            traceback.print_exc()
            return 0.0

    def get_audio_duration(self, audio_length: int, sample_rate: int = 16000, 
                          sample_width: int = 2, channels: int = 1) -> float:
        """Calculate audio duration in seconds"""
        return audio_length / (sample_rate * sample_width * channels)