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
from device_manager import Device,DeviceManager
from voice_processing import *
from command_processor import *
from zigbee_controller import Zigbee2MQTTController
from smart_home_controller import SmartHomeController

import logging
logger = logging.getLogger(__name__)

class ClientEventHandler(AsyncEventHandler):
    def __init__(
        self, 
        reader: asyncio.StreamReader, 
        writer: asyncio.StreamWriter,
        server: 'STTServer'
    ):
        super().__init__(reader, writer)
        self.server = server
        self.device_id = str(uuid.uuid4())
        self.device = None
        self.is_registered = False
        

    async def handle_event(self, event: Event) -> bool:
        try:
            if not self.is_registered:
                if event.type == 'info':
                    self.device = Device(
                        id=self.device_id,
                        name=f"Device_{self.device_id[:8]}",
                        group=None,
                        client=self
                    )
                    self.server.device_manager.add_device(self.device)
                    logger.info(f"Device registered: {self.device.name}")
                    self.is_registered = True
                return True
            
            # logger.info(f"Event: {event.type}, Streaming: {self.device.is_streaming}, Recording: {self.device.is_recording}")

            if event.type == 'audio-start':
                logger.info(f"Audio stream started for device {self.device_id}")
                self.device.is_streaming = True
                self.device.is_recording = True
                self.device.started_at = time.time()
                self.device.audio_buffer = bytearray()
                self.device.silence_counter = 0
                self.device.vad_buffer.clear()

            elif event.type == 'audio-chunk' and self.device.is_streaming:
                # Convert audio chunk to numpy array for VAD
                audio_np = np.frombuffer(event.payload, dtype=np.int16).astype(np.float32) / 32767.0
                
                # Check audio duration
                current_duration = time.time() - self.device.started_at
                if current_duration >= self.server.vad.max_audio_length:
                    logger.info(f"Max audio length reached ({self.server.vad.max_audio_length}s)")
                    await self.stop_and_process_audio()
                    return True

                # Add to main audio buffer if recording
                if self.device.is_recording:
                    self.device.audio_buffer.extend(event.payload)
                
                # Add to VAD buffer
                self.device.vad_buffer.extend(audio_np)
                
                # Process VAD when we have enough samples
                if len(self.device.vad_buffer) >= self.server.vad.chunk_size:
                    vad_chunk = np.array(list(self.device.vad_buffer)[:self.server.vad.chunk_size])
                    speech_prob = self.server.vad.process_chunk(vad_chunk)
                    
                    # logger.info(f"Speech probability: {speech_prob:.3f}, Silence counter: {self.device.silence_counter}")
                    
                    if speech_prob < self.server.vad.vad_threshold:
                        self.device.silence_counter += 1
                        if self.device.silence_counter >= self.server.vad.silence_threshold:
                            audio_duration = time.time() - self.device.started_at
                            if audio_duration >= self.server.vad.min_audio_length:
                                logger.info(f"Silence threshold reached after {audio_duration:.2f}s, processing audio...")
                                await self.stop_and_process_audio()
                    else:
                        self.device.silence_counter = 0
                    
                    # Clear processed VAD samples
                    for _ in range(self.server.vad.chunk_size):
                        if self.device.vad_buffer:
                            self.device.vad_buffer.popleft()

            elif event.type == 'audio-stop':
                if self.device.is_streaming:
                    await self.stop_and_process_audio()

            elif isinstance(event, Detection):
                logger.info(f"Wake word detected on {self.device_id}")
                await self.server.handle_wake_word(self.device_id)

            return True

        except Exception as e:
            logger.info(f"Error handling event for device {self.device_id}: {e}")
            import traceback
            traceback.print_exc()
            return False

    def save_wav_file(self, filename: str, audio_data: bytearray):
        """Save audio data as WAV file with proper headers"""
        try:
            with wave.open(filename, 'wb') as wav_file:
                wav_file.setnchannels(self.device.channels)
                wav_file.setsampwidth(self.device.sample_width)
                wav_file.setframerate(self.device.sample_rate)
                wav_file.writeframes(audio_data)
            logger.info(f"Saved WAV file: {filename} ({len(audio_data)} bytes)")
        except Exception as e:
            logger.info(f"Error saving WAV file: {e}")
            traceback.print_exc()

    async def stop_and_process_audio(self):
        """Stop streaming and process accumulated audio"""
        try:
            logger.info(f"Stopping audio stream for device {self.device_id}")
            self.device.is_recording = False
            self.device.is_streaming = False
            
            # Send stop command to client
            await self.write_event(AudioStop().event())
            
            # Process audio if we have enough
            if len(self.device.audio_buffer) > 0:
                audio_duration = time.time() - self.device.started_at
                logger.info(f"Processing {len(self.device.audio_buffer)} bytes of audio ({audio_duration:.2f}s)...")
                
                # Create timestamp for filename
                timestamp = time.strftime("%Y%m%d_%H%M%S")
                audio_dir = "audio_files"
                os.makedirs(audio_dir, exist_ok=True)
                
                # Save with proper WAV headers
                wav_filename = os.path.join(audio_dir, f"audio_{self.device_id}_{timestamp}.wav")
                self.save_wav_file(wav_filename, self.device.audio_buffer)
                
                # Process audio using Whisper and handle command
                await self.server.handle_transcription(self.device, wav_filename,self.device.id)
            else:
                logger.info("No audio to process")
            
            # Clear buffers
            self.device.audio_buffer = bytearray()
            self.device.silence_counter = 0
            self.device.vad_buffer.clear()
            
        except Exception as e:
            logger.info(f"Error in stop_and_process_audio: {e}")
            import traceback
            traceback.print_exc()

class STTServer:
    def __init__(self, host: str = "0.0.0.0", port: int = 10200,
                 mqtt_api_host: str = "192.168.11.99"):
        self.host = host
        self.port = port
        
        # Initialize audio processing
        self.whisper = WhisperProcessor()  # Use base model for good balance
        self.command_processor = CommandProcessor(os.getenv("OPENAI_API_KEY"))
        
        # Initialize device management
        self.device_manager = DeviceManager()
        self.vad = VADProcessor()
        
        # Initialize Zigbee control
        self.zigbee = Zigbee2MQTTController(mqtt_api_host,8080,'a')
        # self.smart_home = SmartHomeController(self.command_processor, self.zigbee,self.command_processor)
        
        # Initialize server
        self.server = AsyncTcpServer(
            host=self.host,
            port=self.port
        )
    
    def create_handler(
        self, 
        reader: asyncio.StreamReader, 
        writer: asyncio.StreamWriter
    ) -> AsyncEventHandler:
        return ClientEventHandler(reader, writer, self)

    async def handle_transcription(self, device: Device, wav_filename: str,mic_id:str):
        t1 =  int(time.time()*1000)
        try:
            
            logger.info(f"processing start for {t1} {wav_filename}")
            

            # Use Whisper for transcription
            text = self.whisper.process_audio(wav_filename)
            if not text:
                logger.info("No transcription received from Whisper")
                return
                
            logger.info(f"Transcription from {device.name}: {text}")
            
            # Process command with OpenAI
            
            result = await self.smart_home.process_voice_command(text,mic_id)
            
            # Create response as Event
            response = Event(
                type="transcription",
                data={
                    "device_id": device.id,
                    "device_name": device.name,
                    "text": text,
                    "action_results": result
                }
            )
            
            # Send response to device using proper event writing
            await device.client.write_event(response)
            
            # Handle group notifications
            if device.group:
                group_devices = self.device_manager.get_group_devices(device.group)
                for group_device in group_devices:
                    if group_device.id != device.id:
                        group_response = Event(
                            type="transcription",
                            data={
                                **response.data,
                                "group": device.group
                            }
                        )
                        await group_device.client.write_event(group_response)
                        
        except Exception as e:
            logger.info(f"Error handling transcription: {e}")
            traceback.print_exc()
        t2 = int(time.time()*1000)
        logger.info(f"processing complete for {wav_filename} {t2} {t2-t1} ")
    async def handle_wake_word(self, device_id: str):
        device = self.device_manager.devices.get(device_id)
        if device and device.group:
            group_devices = self.device_manager.get_group_devices(device.group)
            notification = {
                "type": "wake_word_detected",
                "device_id": device_id,
                "device_name": device.name,
                "group": device.group
            }
            for group_device in group_devices:
                if group_device.id != device_id:
                    await group_device.client.write_event(json.dumps(notification))

    async def start(self):
        
        await self.server.start(self.create_handler)
        await self.zigbee.connect()
        self.smart_home = SmartHomeController(self.command_processor, self.zigbee,self.command_processor)
        logger.info(f"STT Server running on {self.host}:{self.port}")

    async def stop(self):
        if hasattr(self, 'server'):
            await self.server.stop()