import openai
from typing import Dict, Any
import json
import time

import traceback
from typing import Dict, List, Any
import logging
logger = logging.getLogger(__name__)
class CommandProcessor:
    def __init__(self):
        """Initialize OpenAI client for command interpretation"""
        self.client = openai.Client()

    def interpret_command(self, text: str, devices_summary: List[dict]) -> Dict[str, Any]:
        logger.info(f"interpret_command start {len(devices_summary)}")
        """Interpret voice command with enhanced context awareness"""
        try:
            # Create system prompt with enhanced context
            system_prompt = f"""You are a smart home assistant that controls Zigbee switches.
    When the command doesn't specify a location but asks to control lights or switches:
    1. Find devices that are currently ON (look at state_l1, state_l2, state_l3 fields)
    2. Prioritize devices in the most relevant location
    3. If no specific room is mentioned and command says "all", include ALL switches
    4. For "all" commands, include every switch device regardless of current state

    Current device states and locations:
    {json.dumps(devices_summary, indent=2)}

    Important rules:
    - Commands with "all" should match all switch devices
    - For regular commands, look for devices that are currently ON
    - Each device can have up to 3 channels (state_l1, state_l2, state_l3)
    - When in doubt, include more rather than fewer devices
    - Respond with high confidence for "all" commands

    Return response as JSON with format:
    {{
        "matched_devices": [          # List of device IDs to control
            "device_id1",
            "device_id2"
        ],
        "action": "action_name",      # Action to perform (e.g., "turn_on", "turn_off")
        "parameters": {{              # Parameters for the action
            "param1": value1,
            "param2": value2
        }},
        "confidence": 0.95,           # Confidence in interpretation (0-1)
        "clarification_needed": false # True if command is ambiguous
    }}"""

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text}
            ]
            t1 = (time.time()*1000)
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                temperature=0.2,
                response_format={"type": "json_object"}
            )

            result = json.loads(response.choices[0].message.content)
            t2 = (time.time()*1000)
            logger.info(f"total open api call time {t2-t1}")
            # Handle "all" commands specifically
            if ("all" in text.lower() or "every" in text.lower()) and not result["matched_devices"]:
                matched_devices = []
                for device in devices_summary:
                    # Check if device is a switch (has state_l fields)
                    if any(key.startswith('state_l') for key in device.get('original', {})):
                        matched_devices.append(device['id'])
                
                if matched_devices:
                    result["matched_devices"] = matched_devices
                    result["confidence"] = 0.95
                    result["clarification_needed"] = False
            
            # If still no devices matched but it's a turn off command, 
            # find all devices that are currently on
            elif not result["matched_devices"] and "turn off" in text.lower():
                on_devices = []
                for device in devices_summary:
                    orig = device.get('original', {})
                    if any(orig.get(f'state_l{i}') == 'ON' for i in range(1, 4)):
                        on_devices.append(device['id'])
                
                if on_devices:
                    result["matched_devices"] = on_devices
                    result["confidence"] = 0.8
                    result["clarification_needed"] = False

            logger.info(f"Command interpretation: {json.dumps(result, indent=2)}")
            return result

        except Exception as e:
            logger.info(f"Error interpreting command: {e}")
            traceback.print_exc()
            return {
                "matched_devices": [],
                "action": "unknown",
                "parameters": {},
                "confidence": 0,
                "clarification_needed": True,
                "error": str(e)
            }