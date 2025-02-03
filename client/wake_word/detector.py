import openwakeword
import numpy as np
import logging
import sounddevice as sd
import soundfile as sf
import io
import time
import os
import requests
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional
from collections import defaultdict



logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

@dataclass
class MicrophoneState:
    buffer: np.ndarray
    consecutive_detections: int
    last_detection_time: float
    
    @classmethod
    def create_empty(cls):
        return cls(
            buffer=np.zeros(0),
            consecutive_detections=0,
            last_detection_time=0
        )


class WakeWordDetector:
    @staticmethod
    def download_models():
        """
        Download all available wake word models using openwakeword's built-in function.
        """
        try:
            logger.info("Downloading wake word models...")
            openwakeword.utils.download_models()
            logger.info("Models downloaded successfully")
            return True
        except Exception as e:
            logger.error(f"Error downloading models: {str(e)}")
            return False

    def __init__(self, wake_word_model="alexa", model_path=None):
        """
        Initialize the wake word detector.
        
        Args:
            wake_word_model (str): Name of the wake word model to use
            model_path (str, optional): Path to custom model file
        """
        try:
            # Check if model_path is provided for custom model
            if model_path:
                if not Path(model_path).exists():
                    raise FileNotFoundError(f"Custom model file not found at: {model_path}")
                logger.info(f"Using custom model from: {model_path}")
                self.oww = openwakeword.Model(
                    wakeword_models=[str(model_path)] 
                )
                self.wake_word_model = wake_word_model;
            else:
                # Try to initialize with default model, downloading if needed
                try:
                    logger.info(f"Attempting to load model: {wake_word_model}")
                    self.oww = openwakeword.Model(
                        wakeword_models=[wake_word_model]
                    )
                except Exception as e:
                    logger.info("Model not found, attempting to download...")
                    if self.download_models():
                        logger.info("Retrying model initialization...")
                        self.oww = openwakeword.Model(
                            wakeword_models=[wake_word_model],
                            inference_framework="onnx"
                        )
                    else:
                        raise RuntimeError("Failed to download and initialize model")
            
            logger.info("Wake word model loaded successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize wake word model: {str(e)}")
            raise

        self.buffer = np.zeros(0)
        self.wake_word_model = wake_word_model
        self.last_detection_time = 0
        self.detection_cooldown = 0.3
        self.detection_threshold = 0.4
        self.consecutive_detections = 0
        self.consecutive_threshold = 2
        self.max_buffer_size = int(16000 * 1.5)  # 1.5 seconds at 16kHz
        self.mic_states: Dict[str, MicrophoneState] = defaultdict(MicrophoneState.create_empty)


    def detect(self, audio_chunk: np.ndarray, mic_id: str) -> bool:
        """
        Detect wake word in audio chunk for a specific microphone.
        
        Args:
            audio_chunk (numpy.ndarray): Audio data as numpy array
            mic_id (str): Unique identifier for the microphone (e.g., IP address)
            
        Returns:
            bool: True if wake word detected, False otherwise
        """
        current_time = time.time()
        mic_state = self.mic_states[mic_id]
        
        try:
            # Input validation
            if not self._validate_audio(audio_chunk):
                return False

            # Update buffer for this specific microphone
            mic_state.buffer = self._update_buffer(mic_state.buffer, audio_chunk)

            # Process if buffer is full
            if len(mic_state.buffer) == self.max_buffer_size:
                prediction = self.oww.predict(mic_state.buffer)
                confidence = prediction[self.wake_word_model]

                # Update detection state
                if confidence > self.detection_threshold:
                    mic_state.consecutive_detections += 1
                else:
                    mic_state.consecutive_detections = 0

                # Check for wake word detection
                if self._is_wake_word_detected(mic_state, current_time):
                    logging.info(f"Wake word detected on mic {mic_id} with confidence: {confidence:.4f}")
                    self._reset_mic_state(mic_state)
                    return True

                # Reset if too many consecutive detections
                if mic_state.consecutive_detections > self.consecutive_threshold * 2:
                    mic_state.consecutive_detections = 0

        except Exception as e:
            logging.error(f"Error in detect method for mic {mic_id}: {str(e)}")
            self._reset_mic_state(mic_state)
            return False

        return False

    def _validate_audio(self, audio_chunk: np.ndarray) -> bool:
        """Validate audio chunk data."""
        audio_chunk = np.asarray(audio_chunk)
        return audio_chunk.size > 0 and np.isfinite(audio_chunk).all()

    def _update_buffer(self, buffer: np.ndarray, audio_chunk: np.ndarray) -> np.ndarray:
        """Update the audio buffer for a microphone."""
        if len(buffer) == 0:
            buffer = audio_chunk
        else:
            buffer = np.concatenate((buffer, audio_chunk))
            
        # Keep only the latest audio
        if len(buffer) > self.max_buffer_size:
            buffer = buffer[-self.max_buffer_size:]
            
        return buffer

    def _is_wake_word_detected(self, mic_state: MicrophoneState, current_time: float) -> bool:
        """Check if wake word is detected based on consecutive detections and cooldown."""
        return (mic_state.consecutive_detections >= self.consecutive_threshold and 
                current_time - mic_state.last_detection_time > self.detection_cooldown)

    def reset_buffer(self):
        """Reset the audio buffer and detection state."""
        self.buffer = np.zeros(0)
        self.consecutive_detections = 0
        # logger.debug("Buffer and consecutive detections reset.")
    
    def _reset_mic_state(self, mic_state: MicrophoneState):
        """Reset the state for a specific microphone."""
        mic_state.buffer = np.zeros(0)
        mic_state.consecutive_detections = 0
        mic_state.last_detection_time = time.time()

    def play_audio(self, audio_data):
        """
        Play audio data for testing/debugging purposes.
        
        Args:
            audio_data: Audio data as file path, BytesIO object, or numpy array
        """
        try:
            logger.info("Playing audio...")
            if isinstance(audio_data, str):
                data, samplerate = sf.read(audio_data)
            elif isinstance(audio_data, io.BytesIO):
                audio_data.seek(0)
                data = np.frombuffer(audio_data.read(), dtype=np.float32)
                samplerate = 16000
            elif isinstance(audio_data, np.ndarray):
                data = audio_data
                samplerate = 16000
            else:
                raise ValueError("Unsupported audio data type")

            # Normalize and clip audio
            data = data / np.max(np.abs(data))
            data = data * 1.5
            data = np.clip(data, -1, 1)

            sd.play(data, samplerate)
            sd.wait()
            logger.info("Audio playback finished.")
            
        except Exception as e:
            logger.error(f"Error playing audio: {str(e)}")