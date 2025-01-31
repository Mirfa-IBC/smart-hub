import asyncio
import logging
from aioesphomeapi import APIClient
import socket
import numpy as np
from wake_word.detector import WakeWordDetector
import backoff
import uuid
from dataclasses import dataclass
from typing import Dict, Optional, Callable, List
import time
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@dataclass
class MicrophoneConfig:
    host: str=''
    port: int = 6053
    udp_port: int = 12345
    encryption_key: str=''
    buffer_size: int = 8000  # 0.5 seconds at 16kHz
    detection_cooldown: float = 0.5
    model_path: str = "../models/mirfa.onnx"

class MicrophoneClient:
    def __init__(self, config: MicrophoneConfig):
        self.config = config
        self.id = str(uuid.uuid4())
        self._running = False
        self.udp_server = None
        self.api_client = APIClient(
            config.host,
            config.port,
            password="",
            noise_psk=config.encryption_key
        )
        self.detector = WakeWordDetector(model_path=config.model_path)
        self.last_detection = 0
        
        # Audio processing state
        self.audio_buffer = np.zeros(config.buffer_size, dtype=np.int16)
        self.buffer_position = 0
        self.buffer_filled = False

    async def start(self):
        """Start both API connection and UDP server"""
        await self._connect_api()
        await self._start_udp_server()
        self._running = True
        asyncio.create_task(self._monitor_connection())

    async def stop(self):
        """Stop all components gracefully"""
        self._running = False
        await self._stop_udp_server()
        await self._disconnect_api()

    @backoff.on_exception(backoff.expo, Exception, max_tries=5)
    async def _connect_api(self):
        """Connect to ESPHome API with retry"""
        await self.api_client.connect(login=True)
        logger.info(f"Connected to microphone {self.id} at {self.config.host}")
        
        # Subscribe to voice assistant events
        self.api_client.subscribe_voice_assistant(
            handle_start=self._handle_pipeline_start,
            handle_stop=self._handle_pipeline_stop,
            handle_audio=self._handle_audio
        )

    async def _disconnect_api(self):
        """Disconnect from ESPHome API"""
        # if self.api_client.is_connected:
        # await self.api_client.disconnect()
        # logger.info(f"Disconnected from microphone {self.id}")
        pass

    async def _start_udp_server(self):
        """Start UDP server for audio streaming"""
        self.udp_server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp_server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.udp_server.bind(('0.0.0.0', self.config.udp_port))
        self.udp_server.setblocking(False)
        logger.info(f"Microphone {self.id} UDP server started on port {self.config.udp_port}")

    async def _stop_udp_server(self):
        """Stop UDP server"""
        if self.udp_server:
            self.udp_server.close()
            logger.info(f"Microphone {self.id} UDP server stopped")

    async def _monitor_connection(self):
        """Monitor and maintain connections"""
        while self._running:
            try:
                # Check API connection status
                # if not self.api_client._connection or not self.api_client._connection._transport:
                #     logger.warning(f"Microphone {self.id} API disconnected, reconnecting...")
                #     await self._connect_api()
                #     # Resubscribe to voice assistant after reconnection
                #     self.api_client.subscribe_voice_assistant(
                #         handle_start=self._handle_pipeline_start,
                #         handle_stop=self._handle_pipeline_stop,
                #         handle_audio=self._handle_audio
                #     )

                # # Process UDP packets
                # await self._process_udp_packets()

                await asyncio.sleep(1)

            except Exception as e:
                logger.error(f"Microphone {self.id} connection error: {e}")
                await asyncio.sleep(5) 

    async def _process_udp_packets(self):
        """Process incoming UDP packets"""
        try:
            while True:
                print("cjeclom")
                data, _ = await asyncio.get_event_loop().sock_recvfrom(
                    self.udp_server, 4096
                )
                print("cjeclomsas")
                await self._process_audio_data(data)
        except (BlockingIOError, InterruptedError):
            pass

    async def _process_audio_data(self, data: bytes):
        """Process audio data for wake word detection"""
        print("in audio")
        audio_chunk = np.frombuffer(data, dtype=np.int16)[::2]  # Downsample to 16kHz
        
        # Update ring buffer
        chunk_size = len(audio_chunk)
        start_pos = self.buffer_position
        end_pos = start_pos + chunk_size
        
        if end_pos > self.config.buffer_size:
            wrap_pos = end_pos - self.config.buffer_size
            self.audio_buffer[start_pos:] = audio_chunk[:self.config.buffer_size - start_pos]
            self.audio_buffer[:wrap_pos] = audio_chunk[self.config.buffer_size - start_pos:]
            self.buffer_position = wrap_pos
        else:
            self.audio_buffer[start_pos:end_pos] = audio_chunk
            self.buffer_position = end_pos

        # Check if buffer is filled and detect wake word
        if self.buffer_position >= self.config.buffer_size:
            self.buffer_filled = True
            self.buffer_position = 0

        if self.buffer_filled and self._check_wake_word():
            logger.info(f"Wake word detected on microphone {self.id}")
            await self._trigger_assistant()

    def _check_wake_word(self) -> bool:
        """Check for wake word with cooldown"""
        current_time = time.time()
        if current_time - self.last_detection < self.config.detection_cooldown:
            return False
        
        if self.detector.detect(self.audio_buffer):
            self.last_detection = current_time
            return True
        return False

    async def _trigger_assistant(self):
        """Trigger voice assistant pipeline"""
        await self.api_client.send_voice_assistant_audio_settings(
            conversation_id=str(uuid.uuid4()),
            flags=0,
            audio_settings=VoiceAssistantAudioSettings(
                noise_suppression_level=1,
                auto_gain=30,
                volume_multiplier=1.0
            )
        )

    async def _handle_pipeline_start(self, conversation_id: str, flags: int, audio_settings, wake_word_phrase: str):
        """Handle pipeline start event from ESPHome"""
        logger.info(f"Pipeline started on {self.id} (Conversation: {conversation_id})")
        return self.config.udp_port

    async def _handle_pipeline_stop(self, server_side: bool):
        """Handle pipeline stop event from ESPHome"""
        logger.info(f"Pipeline stopped on {self.id} (server_side: {server_side})")

    async def _handle_audio(self, data: bytes):
        print("in handle")
        """Handle audio data from ESPHome"""
        # Implement if needed for bidirectional communication
        pass

class VoiceAssistantHub:
    def __init__(self):
        self.microphones: Dict[str, MicrophoneClient] = {}
        self._running = False

    async def add_microphone(self, config: MicrophoneConfig) -> str:
        """Add and start a new microphone client"""
        client = MicrophoneClient(config)
        mic_id = client.id
        self.microphones[mic_id] = client
        await client.start()
        return mic_id

    async def remove_microphone(self, mic_id: str):
        """Remove and stop a microphone client"""
        if mic_id in self.microphones:
            await self.microphones[mic_id].stop()
            del self.microphones[mic_id]

    async def run(self):
        """Main hub operation"""
        self._running = True
        while self._running:
            await asyncio.sleep(1)

    async def stop(self):
        """Stop all microphone clients"""
        self._running = False
        for mic in self.microphones.values():
            await mic.stop()
        self.microphones.clear()

async def main():
    hub = VoiceAssistantHub()
    
    # Add multiple microphone clients
    await hub.add_microphone(MicrophoneConfig(
        host="192.168.1.199",
        udp_port=12345,
        encryption_key="B/ZTOpKW5IyL0jUv9InGeNOpVPdj4+oDO48fmwrh5Ak="
    ))
    
    await hub.add_microphone(MicrophoneConfig(
        host="192.168.1.157",
        udp_port=12346,
        encryption_key="B/ZTOpKW5IyL0jUv9InGeNOpVPdj4+oDO48fmwrh5Ak="
    ))

    try:
        await hub.run()
    except KeyboardInterrupt:
        await hub.stop()

if __name__ == "__main__":
    asyncio.run(main())