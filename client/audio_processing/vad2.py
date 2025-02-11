import numpy as np
import os
from typing import Dict, Set, Optional, Any
import webrtcvad
import logging
import os

logger = logging.getLogger(__name__)

class VADProcessor:
    def __init__(self):
        # WebRTC VAD has aggression levels 0-3, with 3 being the most aggressive
        # We'll use level 2 as a moderate default
        self.vad = webrtcvad.Vad(1)
        self.sample_rate = 16000  # WebRTC VAD only supports 8000, 16000, 32000, 48000 Hz
        self.vad_threshold = 0.5
        self.silence_threshold = 15
        self.chunk_size = 512  # Note: WebRTC VAD requires frame sizes of 10, 20, or 30ms
        self.min_audio_length = 1.0  # Minimum audio length in seconds
        self.max_audio_length = 5.0  # Maximum audio length in seconds

    def process_chunk(self, audio_chunk: np.ndarray) -> float:
        try:
            # Convert float32 numpy array to int16 bytes
            audio_bytes = (audio_chunk * 32768).astype(np.int16).tobytes()
            
            # WebRTC VAD expects frames of 10, 20, or 30ms
            # For 16kHz audio: 160, 320, or 480 samples respectively
            # We'll adjust the chunk to 480 samples (30ms) if needed
            frame_duration = 30  # ms
            samples_per_frame = int(self.sample_rate * frame_duration / 1000)
            
            if len(audio_bytes) >= samples_per_frame * 2:  # *2 because of int16
                # Process the frame
                is_speech = self.vad.is_speech(audio_bytes[:samples_per_frame * 2], self.sample_rate)
                # Convert boolean to float probability (0.0 or 1.0)
                return float(is_speech)
            else:
                logger.warning(f"Audio chunk too small for WebRTC VAD: {len(audio_bytes)} bytes")
                return 0.0

        except Exception as e:
            logger.info(f"Error in VAD processing: {e}")
            import traceback
            traceback.print_exc()
            return 0.0

    def get_audio_duration(self, audio_length: int, sample_rate: int = 16000, 
                          sample_width: int = 2, channels: int = 1) -> float:
        """Calculate audio duration in seconds"""
        return audio_length / (sample_rate * sample_width * channels)