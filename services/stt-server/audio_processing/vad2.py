import numpy as np
import torch
import logging
import os

logger = logging.getLogger(__name__)

class VADProcessor:
    """
    Simplified Silero VAD implementation that works reliably on CPU
    even with CUDA-enabled PyTorch installations.
    """
    
    def __init__(self) -> None:
        """Initialize the Silero VAD model on CPU."""
        try:
            # Setup cache dir
            cache_dir = os.path.join(os.path.dirname(__file__), "models", "torch_cache")
            os.makedirs(cache_dir, exist_ok=True)
            os.environ['TORCH_HOME'] = cache_dir
            
            logger.info(f"Loading Silero VAD model (CPU only)")
            
            # First load model without device specification
            self.vad_model, utils = torch.hub.load(
                repo_or_dir='snakers4/silero-vad',
                model='silero_vad',
                force_reload=False,
                trust_repo=True
            )
            
            # Then explicitly move it to CPU
            self.vad_model = self.vad_model.to('cpu')
            self.vad_model.eval()
            
            logger.info(f"Model loaded on: {next(self.vad_model.parameters()).device}")
            
            # Configuration
            self.sample_rate = 16000
            self.threshold = 0.4
            self.min_audio_length =1 
            self.silence_threshold = 30
            self.chunk_size = 512
            self.vad_threshold = 0.4
        except Exception as e:
            logger.error(f"Failed to initialize Silero VAD: {e}")
            raise
    
    def process_chunk(self, audio_chunk: np.ndarray, binary_output: bool = True) -> float:
        """
        Process audio chunk and return speech probability or binary decision.
        
        Args:
            audio_chunk: Audio data as numpy array
            binary_output: If True, returns 0.0 or 1.0 based on threshold (0.4)
            
        Returns:
            float: Speech probability or binary decision
        """
        try:
            # Ensure audio is the right shape
            if len(audio_chunk.shape) == 1:
                audio_chunk = audio_chunk.reshape(1, -1)
            
            # Convert to tensor on CPU
            audio_tensor = torch.tensor(audio_chunk, dtype=torch.float32)
            audio_tensor = audio_tensor.to('cpu')  # Ensure it's on CPU
            
            # Get speech probability
            with torch.no_grad():
                speech_prob = self.vad_model(audio_tensor, self.sample_rate).item()
            
            # Convert to binary if requested
            # if binary_output:
            #     return 1.0 if speech_prob > 0.4 else 0.0
            
            return speech_prob
            
        except Exception as e:
            logger.error(f"Error in VAD processing: {e}")
            return 0.0
        
    def get_audio_duration(self, audio_length: int, sample_rate: int = 16000,
                          sample_width: int = 2, channels: int = 1) -> float:
        """Calculate audio duration in seconds."""
        return audio_length / (sample_rate * sample_width * channels)