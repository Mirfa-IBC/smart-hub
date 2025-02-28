import logging
import time
from typing import Optional

class PerformanceLogger:
    def __init__(self, log_file: str = "performance.log"):
        self.logger = logging.getLogger("PerformanceLogger")
        self.logger.setLevel(logging.INFO)
        
        # File handler
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.INFO)
        
        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        
        # Create formatter
        formatter = logging.Formatter('%(asctime)s - %(message)s')
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)
        
        # Add handlers
        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)
        
        self._start_time: Optional[float] = None
        self._last_checkpoint: Optional[float] = None
        self._process_id: Optional[str] = None

    def start_process(self, process_id: str):
        """Start timing a new process"""
        self._process_id = process_id
        self._start_time = time.time()
        self._last_checkpoint = self._start_time
        self.logger.info(f"Started process {process_id}")

    def log_step(self, step_name: str, include_total: bool = False):
        """Log time taken for a step"""
        if not self._start_time or not self._last_checkpoint:
            self.logger.warning("No active process")
            return

        current_time = time.time()
        step_duration = (current_time - self._last_checkpoint) * 1000  # Convert to ms
        total_duration = (current_time - self._start_time) * 1000

        if include_total:
            self.logger.info(
                f"Process {self._process_id} - {step_name}: {step_duration:.2f}ms "
                f"(Total: {total_duration:.2f}ms)"
            )
        else:
            self.logger.info(
                f"Process {self._process_id} - {step_name}: {step_duration:.2f}ms"
            )

        self._last_checkpoint = current_time

    def end_process(self):
        """End the current process and log total time"""
        if not self._start_time:
            self.logger.warning("No active process")
            return

        total_duration = (time.time() - self._start_time) * 1000
        self.logger.info(
            f"Process {self._process_id} completed - Total time: {total_duration:.2f}ms"
        )
        
        # Reset timers
        self._start_time = None
        self._last_checkpoint = None
        self._process_id = None

# Example usage:
"""
logger = PerformanceLogger()

# Start timing a process
logger.start_process("audio_processing_123")

# Log WAV processing time
logger.log_step("WAV Processing")

# Log Whisper processing
logger.log_step("Whisper Transcription")

# Log command interpretation
logger.log_step("Command Interpretation")

# End process and get total time
logger.end_process()
"""