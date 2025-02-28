from dataclasses import dataclass
from typing import Dict, Set, Optional, Any
from collections import deque
from dataclasses import dataclass,field
from typing import Dict, Optional, Any


import logging
logger = logging.getLogger(__name__)

@dataclass
class Device:
    id: str
    name: str
    group: Optional[str]
    client: Any
    location: str = ""  # Physical location of the device
    is_streaming: bool = False
    audio_buffer: bytearray = field(default_factory=bytearray)
    silence_counter: int = 0
    vad_buffer: deque = field(default_factory=lambda: deque(maxlen=512))
    sample_rate: int = 16000
    sample_width: int = 2
    channels: int = 1
    is_recording: bool = False
    started_at: float = 0.0

class DeviceManager:
    def __init__(self):
        self.devices: Dict[str, Device] = {}
        self.groups: Dict[str, Set[str]] = {}
        
    def add_device(self, device: Device):
        self.devices[device.id] = device
        if device.group:
            if device.group not in self.groups:
                self.groups[device.group] = set()
            self.groups[device.group].add(device.id)
            
    def remove_device(self, device_id: str):
        if device_id in self.devices:
            device = self.devices[device_id]
            if device.group and device.group in self.groups:
                self.groups[device.group].remove(device_id)
                if not self.groups[device.group]:
                    del self.groups[device.group]
            del self.devices[device_id]
            
    def get_group_devices(self, group_name: str) -> Set[Device]:
        if group_name not in self.groups:
            return set()
        return {self.devices[dev_id] for dev_id in self.groups[group_name]}