import numpy as np
import os
from typing import Dict, Optional, Any, Tuple
import torch
import traceback
import logging

logger = logging.getLogger(__name__)

class VADProcessor:
    """
    Voice Activity Detection processor using Silero VAD model.
    CPU-only implementation.
    """
    
    def __init__(self) -> None:
        """
        Initialize VAD processor with Silero model on CPU.
        Sets up model cache directory and loads pretrained model.
        """
        # Force CPU usage by setting environment variable
        os.environ['CUDA_VISIBLE_DEVICES'] = ''
        
        cache_dir = os.path.join(os.path.dirname(__file__), "models", "torch_cache")
        os.makedirs(cache_dir, exist_ok=True)
        os.environ['TORCH_HOME'] = cache_dir
        
        logger.info(f"Downloading models silero_vad in {cache_dir}")
        
        # Force CPU device during model loading
        self.vad_model, _ = torch.hub.load(
            repo_or_dir='snakers4/silero-vad',
            model='silero_vad',
            force_reload=False,
            trust_repo=True
        )
        
        # Ensure model is in eval mode and on CPU
        self.vad_model.eval()
        self.vad_model = self.vad_model.cpu()
        
        # Configuration parameters
        self.sample_rate: int = 16000  # Hz
        self.vad_threshold: float = 0.5
        self.silence_threshold: int = 30  # frames
        self.chunk_size: int = 512  # samples
        self.min_audio_length: float = 1.0  # seconds
        self.max_audio_length: float = 5.0  # seconds

    def process_chunk(self, audio_chunk: np.ndarray) -> float:
        """
        Process an audio chunk and return speech probability.
        CPU-only implementation.
        
        Args:
            audio_chunk: Audio data as numpy array
            
        Returns:
            float: Probability of speech presence (0.0 to 1.0)
        """
        try:
            # Ensure audio is the right shape and type
            if len(audio_chunk.shape) == 1:
                audio_chunk = audio_chunk.reshape(1, -1)
            
            # Convert to torch tensor on CPU
            audio_tensor = torch.tensor(audio_chunk, dtype=torch.float32, device='cpu')
            
            # Get speech probability
            with torch.no_grad():
                speech_prob = self.vad_model(audio_tensor, self.sample_rate).item()
            
            return speech_prob
            
        except Exception as e:
            logger.error(f"Error in VAD processing: {e}")
            logger.error(traceback.format_exc())
            return 0.0

    def get_audio_duration(self, audio_length: int, sample_rate: int = 16000,
                          sample_width: int = 2, channels: int = 1) -> float:
        """Calculate audio duration in seconds."""
        return audio_length / (sample_rate * sample_width * channels)