from typing import Dict
import traceback
from typing import Dict, List
from zigbee_controller import Zigbee2MQTTController
from command_processor import CommandProcessor
import time
import logging
logger = logging.getLogger(__name__)

class LocationAwareController:
    def __init__(self):
        self.mic_locations = {
            "apartment_bedroom": {
                "primary": ["apartment_bedroom", "apartment_bedroom_bathroom"],
                "secondary": ["apartment_lobby", "apartment_living"]
            },
            "apartment_living": {
                "primary": ["apartment_living", "apartment_living_bathroom"],
                "secondary": ["apartment_lobby", "apartment_bedroom"]
            },
            "apartment_lobby": {
                "primary": ["apartment_lobby"],
                "secondary": ["apartment_living", "apartment_bedroom"]
            },
            "villa_living": {
                "primary": ["villa_living", "villa_living_bathroom"],
                "secondary": ["villa_lobby", "villa_bedroom"]
            }
        }
        
        # Device priority based on mic location
        self.location_priorities = {
            loc: {
                **{area: 1.0 for area in areas["primary"]},
                **{area: 0.5 for area in areas["secondary"]}
            }
            for loc, areas in self.mic_locations.items()
        }

class SmartHomeController:
    def __init__(self, openai_client, zigbee_controller: Zigbee2MQTTController, command_processor: CommandProcessor):
        self.openai_client = openai_client
        self.zigbee = zigbee_controller
        self.devices = {}
        self.device_capabilities = {}
        self.location_controller = LocationAwareController()
        self.command_processor = command_processor
    
    def get_location_context(self, mic_id: str) -> Dict[str, float]:
        """Get device priorities based on microphone location"""
        mic_location = self._get_mic_location(mic_id)
        return self.location_controller.location_priorities.get(mic_location, {})
    

    def _get_mic_location(self, mic_id: str) -> str:
        """Extract location from mic ID"""
        return "apartment_bedroom"  # Default for now
    
    
    
    async def refresh_devices(self):
        """Refresh the list of available devices and their capabilities"""
        self.devices = await self.zigbee.get_devices()
        
        # Map devices to their capabilities
        for device_id, device in self.devices.items():
            capabilities = []
            if 'definition' in device:
                for exposes in device['definition'].get('exposes', []):
                    if exposes.get('type') == 'light':
                        capabilities.extend(['turn_on', 'turn_off', 'brightness'])
                        if 'color_temp' in exposes:
                            capabilities.append('color_temperature')
                        if 'color' in exposes:
                            capabilities.append('color')
                    elif exposes.get('type') == 'switch':
                        capabilities.extend(['turn_on', 'turn_off'])
                    elif exposes.get('type') == 'lock':
                        capabilities.extend(['lock', 'unlock'])
                    elif exposes.get('type') == 'cover':
                        capabilities.extend(['open', 'close', 'stop'])
            
            self.device_capabilities[device_id] = capabilities
    
    def normalize_device_info(self, device_id: str, device: dict) -> dict:
        """Normalize device information for better command interpretation"""
        try:
            switch_capabilities = ['turn_on', 'turn_off']
            
            device_type = 'switch'  
            device_caps = switch_capabilities  
            
            parts = device_id.split('_')
            location = parts[0] if parts[0] in ['apartment', 'villa'] else 'unknown'
            
            room = None
            for part in parts:
                if part in ['bedroom', 'living', 'bathroom', 'lobby']:
                    room = part
                    break
            if not room and len(parts) > 1:
                room = parts[1]  
                
            return {
                "id": device_id,
                "name": device_id,  
                "type": device_type,
                "capabilities": device_caps,
                "location": location,
                "room": room or 'unknown',
                "original": device  
            }
            
        except Exception as e:
            logger.info(f"Error normalizing device {device_id}: {e}")
            return {
                "id": device_id,
                "name": device_id,
                "type": "unknown",
                "capabilities": [],
                "location": "unknown",
                "room": "unknown",
                "original": device
            }
        
    async def process_voice_command(self, transcription: str, mic_id: str) -> Dict[str, any]:
        """Process voice command with location awareness"""
        try:
            
            await self.refresh_devices()
            
            location_priorities = self.get_location_context(mic_id)
            
            devices_summary = []
            for device_id, device in self.devices.items():
                normalized = self.normalize_device_info(device_id, device)
                normalized["priority"] = location_priorities.get(normalized["room"], 0.1)
                devices_summary.append(normalized)
            
            interpretation = self.command_processor.interpret_command(
                transcription, devices_summary
            )

            results = []
            light_states = []
            for device_id in interpretation["matched_devices"]:
                state_update = self._prepare_state_update(
                    interpretation["action"],
                    interpretation["parameters"]
                )
                
                # Add all channels for this device to the batch
                for channel in range(1, 4):
                    light_states.append({
                        "device_id": device_id,
                        "channel": channel,
                        "state": state_update.get(f"state_l{channel}") == "ON"
                    })

            # Send all updates in one batch operation
            t1 =  int(time.time()*1000)
            success = await self.zigbee.set_multiple_devices(light_states)
            t2 =  int(time.time()*1000)
            logger.info(f" total set_multiple_devices time {t2-t1}")
            # Record results for each device
            results.extend([
                {
                    "device_id": device_id,
                    "success": success,
                    "action": interpretation["action"],
                    "parameters": interpretation["parameters"]
                }
                for device_id in interpretation["matched_devices"]
            ])
            
            return {
                "status": "success",
                "results": results,
                "interpretation": interpretation,
                "mic_location": self._get_mic_location(mic_id)
            }

        except Exception as e:
            logger.info(f"Error processing voice command: {e}")
            traceback.print_exc()
            return {
                "status": "error",
                "error": str(e)
            }

    def _prepare_state_update(self, action: str, parameters: dict) -> dict:
        """Convert high-level action and parameters to device state update"""
        try:
            states = {}
            if action == "turn_on":
                for i in range(1, 4):  
                    states[f"state_l{i}"] = "ON"
                    
            elif action == "turn_off":
                for i in range(1, 4):
                    states[f"state_l{i}"] = "OFF"
                    
            else:
                logger.info(f"Unknown action: {action}")
                
            return states
                
        except Exception as e:
            logger.info(f"Error preparing state update: {e}")
            logger.info(f"Action: {action}, Parameters: {parameters}")
            return {}
