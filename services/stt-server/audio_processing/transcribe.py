import numpy as np
import os
from typing import Optional
import traceback
from typing import Optional
import logging
from faster_whisper import WhisperModel  # Add this import
import os
import time
logger = logging.getLogger(__name__)
import os
import asyncio

class WhisperProcessor:
    def __init__(self, model_name: str = "medium"):
        """Initialize Whisper with specified model"""
        logger.info(f"Loading Whisper model: {model_name}")
        download_dir = os.path.join(os.path.dirname(__file__), "models")
        self.lock = asyncio.Lock()  # Add lock for sequential processing
        # Check CUDA memory and configuration
        try:
            import torch
            torch.cuda.empty_cache()  # Clear any existing allocations
            free_memory = torch.cuda.get_device_properties(0).total_memory - torch.cuda.memory_allocated(0)
            logger.info(f"CUDA available with {free_memory/1e9:.2f}GB free memory")
            
            # Set optimal CUDA settings
            torch.cuda.set_device(0)
            torch.backends.cudnn.enabled = True
            torch.backends.cudnn.benchmark = False  # Disable autotuner
            torch.backends.cudnn.deterministic = True  # More stable but slower
        except Exception as e:
            logger.error(f"Error configuring CUDA: {e}")
            raise
        if torch.cuda.is_available():
            logger.info(f"GPU Memory before model load: {torch.cuda.memory_allocated()/1024**2:.2f}MB")
        # Initialize model with optimized CUDA settings
        self.model = WhisperModel(
            model_name,
            device="cuda",
            compute_type="float16",  # Use float16 for better memory efficiency
            download_root=download_dir,
            cpu_threads=min(os.cpu_count(), 4),
            num_workers=1
        )
        if torch.cuda.is_available():
            logger.info(f"GPU Memory after model load: {torch.cuda.memory_allocated()/1024**2:.2f}MB")
        
        # Optimize transcribe options for GPU processing
        self.transcribe_options = {
                    "language": "en",
                    "beam_size": 1,
                    "best_of": 1,
                    "vad_filter": False,
                    "initial_prompt": "This is a smart home voice command.",
                    "condition_on_previous_text": False,
                    "temperature": 0.0
                }
        
        self.common_wake_words = ["alexa", "hey alexa", "ok google", "hey google", "siri", "hey siri", "mirfa"]

    async def process_audio(self, audio_filename: str) -> Optional[str]:
        """Transcribe audio file using Whisper model with optimized GPU handling"""
        async with self.lock:  # Ensure sequential processing
            try:
                logger.info(f"Processing audio file with Whisper: {audio_filename}")
                start = time.time()
                
                # Clear CUDA cache before processing
                import torch
                torch.cuda.empty_cache()
                

                # Process in smaller chunks if needed
                try:
                    loop = asyncio.get_event_loop()
                    segments, info = await loop.run_in_executor(
                        None, 
                        lambda: self.model.transcribe(audio_filename, **self.transcribe_options)
                    )
                    transcription = " ".join(segment.text for segment in segments).strip()
                    cleaned_text = self._remove_wake_words(transcription)
                    
                    duration = time.time() - start
                    logger.info(f"Transcription completed in {duration:.2f}s")
                    logger.info(f"Original transcription: {transcription}")
                    logger.info(f"Cleaned transcription: {cleaned_text}")
                    
                    return cleaned_text
                    
                except RuntimeError as e:
                    if "CUDNN_STATUS_EXECUTION_FAILED" in str(e):
                        logger.error("CUDA execution failed - possible memory issue")
                        # Clear CUDA memory and retry
                        torch.cuda.empty_cache()
                        # Wait a moment for memory to clear
                        time.sleep(1)
                        
                        # Retry with more aggressive memory optimization
                        segments, info = self.model.transcribe(
                            audio_filename,
                            **{
                                **self.transcribe_options,
                                "beam_size": 1,
                                "best_of": 1,
                                "compression_ratio_threshold": 2.8,  # More aggressive compression
                            }
                        )
                        
                        transcription = " ".join(segment.text for segment in segments).strip()
                        cleaned_text = self._remove_wake_words(transcription)
                        return cleaned_text
                    else:
                        raise
                        
            except Exception as e:
                logger.error(f"Error in Whisper transcription: {e}")
                traceback.print_exc()
                return None
            finally:
                # Always try to clean up GPU memory
                try:
                    torch.cuda.empty_cache()
                except Exception as e:
                    logger.warning(f"Failed to clear CUDA memory: {e}")
    
    async def process_vad_chunk(self, audio_chunk: np.ndarray, sample_rate: int = 16000) -> Optional[str]:
        """
        Transcribe a VAD-detected audio chunk using Whisper model.
        
        Args:
            audio_chunk (np.ndarray): The audio chunk detected by VAD
            sample_rate (int): Sample rate of the audio, defaults to 16kHz
            
        Returns:
            Optional[str]: Transcribed text or None if transcription fails
        """
        
        try:
            logger.info("Processing VAD chunk with Whisper")
            start = time.time()
            
            # Clear CUDA cache before processing
            import torch
            torch.cuda.empty_cache()
            
            try:
                loop = asyncio.get_event_loop()
                # Note: faster-whisper expects audio data as numpy array
                segments, info = await loop.run_in_executor(
                    None,
                    lambda: self.model.transcribe(
                        audio_chunk,
                        **self.transcribe_options
                    )
                )
                
                transcription = " ".join(segment.text for segment in segments).strip()
                cleaned_text = self._remove_wake_words(transcription)
                
                duration = time.time() - start
                logger.info(f"VAD chunk transcription completed in {duration:.2f}s")
                logger.info(f"Original VAD transcription: {transcription}")
                logger.info(f"Cleaned VAD transcription: {cleaned_text}")
                
                return cleaned_text
                
            except RuntimeError as e:
                if "CUDNN_STATUS_EXECUTION_FAILED" in str(e):
                #     logger.error("CUDA execution failed during VAD chunk processing - possible memory issue")
                #     # Clear CUDA memory and retry
                #     torch.cuda.empty_cache()
                #     time.sleep(1)
                    
                #     # Retry with more aggressive memory optimization
                #     segments, info = self.model.transcribe(
                #         audio_chunk,
                #         **{
                #             **self.transcribe_options,
                #             "beam_size": 1,
                #             "best_of": 1,
                #             "compression_ratio_threshold": 2.8,
                #         }
                #     )
                    
                #     transcription = " ".join(segment.text for segment in segments).strip()
                #     cleaned_text = self._remove_wake_words(transcription)
                    # return cleaned_text
                    traceback.print_exc()
                else:
                    traceback.print_exc()
                    raise
                    
        except Exception as e:
            logger.error(f"Error in VAD chunk Whisper transcription: {e}")
            traceback.print_exc()
            return None
            
        finally:
            # Always try to clean up GPU memory
            try:
                torch.cuda.empty_cache()
            except Exception as e:
                logger.warning(f"Failed to clear CUDA memory during VAD processing: {e}")                
    def _remove_wake_words(self, text: str) -> str:
        """Remove wake words while preserving case and spacing"""
        text_lower = text.lower()
        
        for wake_word in self.common_wake_words:
            if text_lower.startswith(wake_word):
                # Preserve original case by using the original text
                return text[len(wake_word):].strip()
        
        return text


async def main():
    # Initialize the processor
    processor = WhisperProcessor()
    a = await processor.process_audio('audio_192.168.1.157_20250208_001131.wav')
    print(a)
if __name__ == "__main__":
    asyncio.run(main())