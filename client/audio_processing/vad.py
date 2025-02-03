import numpy as np
import os
from typing import Dict, Set, Optional, Any
import torch
import traceback
from typing import Dict, List, Optional, Any
import logging
import os
import os
logger = logging.getLogger(__name__)

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
            trust_repo=True
        )
        self.sample_rate = 16000
        self.vad_threshold = 0.5
        self.silence_threshold = 30
        self.chunk_size = 512
        self.min_audio_length = 1.0  # Minimum audio length in seconds
        self.max_audio_length = 5.0  # Maximum audio length in seconds

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