from dataclasses import dataclass, field
from typing import Optional

@dataclass
class ESPHomeConfig:
    host: str
    port: int = 6053
    encryption_key: Optional[str] = None

@dataclass
class WyomingConfig:
    host: str
    port: int = 10200
    device_name: Optional[str] = None

@dataclass
class AudioConfig:
    sample_rate: int = 16000
    sample_width: int = 2
    channels: int = 1
    buffer_size: int = 50

@dataclass
class WakeWordConfig:
    wake_word: str = "alexa"
    model_path: Optional[str] = None

@dataclass
class AppConfig:
    esphome: ESPHomeConfig
    wyoming: WyomingConfig
    audio: AudioConfig = field(default_factory=AudioConfig)
    wake_word: WakeWordConfig = field(default_factory=WakeWordConfig)