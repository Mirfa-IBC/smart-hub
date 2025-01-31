import openwakeword
import numpy as np
import logging
import sounddevice as sd
import soundfile as sf
import io
import time
import os
import requests
from pathlib import Path

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class WakeWordDetector:
    @staticmethod
    def download_models():
        """
        Download all available wake word models using openwakeword's built-in function.
        """
        try:
            logger.info("Downloading wake word models...")
            # openwakeword.utils.download_models()
            logger.info("Models downloaded successfully")
            return True
        except Exception as e:
            logger.error(f"Error downloading models: {str(e)}")
            return False

    def __init__(self, wake_word_model="mirfa", model_path=None):
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
                    wakeword_model_paths=[str(model_path)] 
                )
            else:
                # Try to initialize with default model, downloading if needed
                try:
                    logger.info(f"Attempting to load model: {wake_word_model}")
                    self.oww = openwakeword.Model(
                        wakeword_model_paths=[wake_word_model]
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

    def detect(self, audio_chunk):
        """
        Detect wake word in audio chunk.
        
        Args:
            audio_chunk (numpy.ndarray): Audio data as numpy array
            
        Returns:
            bool: True if wake word detected, False otherwise
        """
        current_time = time.time()
        
        try:
            # Convert audio_chunk to numpy array if it's not already
            audio_chunk = np.asarray(audio_chunk)
            
            # Input validation
            if audio_chunk.size == 0:
                logger.warning("Received empty audio chunk")
                return False
                
            if not np.isfinite(audio_chunk).all():
                logger.warning("Audio chunk contains invalid values")
                return False

            # Append new audio to the buffer more efficiently
            if len(self.buffer) == 0:
                self.buffer = audio_chunk
            else:
                self.buffer = np.concatenate((self.buffer, audio_chunk))

            # Keep only the last 1.5 seconds of audio
            if len(self.buffer) > self.max_buffer_size:
                self.buffer = self.buffer[-self.max_buffer_size:]

            # Ensure the buffer is the correct size before prediction
            if len(self.buffer) == self.max_buffer_size:
                # Get the detection score
                prediction = self.oww.predict(self.buffer)
                confidence = prediction[self.wake_word_model]

                # Check if wake word was detected
                if confidence > self.detection_threshold:
                    self.consecutive_detections += 1
                    logger.debug(f"Potential wake word detected. Consecutive detections: {self.consecutive_detections}")
                else:
                    if self.consecutive_detections > 0:
                        logger.debug(f"Resetting consecutive detections from {self.consecutive_detections} to 0")
                    self.consecutive_detections = 0

                # Check if we have enough consecutive detections and cooldown period has passed
                if (self.consecutive_detections >= self.consecutive_threshold and 
                    current_time - self.last_detection_time > self.detection_cooldown):
                    self.last_detection_time = current_time
                    logger.info(f"Wake word confirmed with confidence: {confidence:.4f}")
                    
                    # Reset consecutive detections and buffer to prevent immediate re-triggering
                    self.reset_buffer()
                    return True
                
                # Reset if exceeded maximum consecutive detections
                if self.consecutive_detections > self.consecutive_threshold * 2:
                    logger.debug(f"Exceeded maximum consecutive detections ({self.consecutive_threshold * 2}). Resetting.")
                    self.consecutive_detections = 0
                    
        except Exception as e:
            logger.error(f"Error in detect method: {str(e)}")
            self.reset_buffer()
            return False
        
        return False

    def reset_buffer(self):
        """Reset the audio buffer and detection state."""
        self.buffer = np.zeros(0)
        self.consecutive_detections = 0
        logger.debug("Buffer and consecutive detections reset.")

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