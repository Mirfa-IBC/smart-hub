import asyncio
import json
from typing import Dict, Optional, List
import websockets
from collections import defaultdict
import time
import logging
logger = logging.getLogger(__name__)
class Zigbee2MQTTController:
    def __init__(self, host: str = "localhost:192.168.11.99", port: int = 8080, token: str = "a"):
        """Initialize the controller with optimized settings"""
        self.ws_url = f"ws://{host}:{port}/api?token={token}"
        self.device_states: Dict[str, dict] = {}
        self.bridge_info: Optional[dict] = None
        self.ws = None
        self.connected = False
        self.connection_retries = 3
        self.retry_delay = 1  # 1 second retry delay
        self._connection_lock = asyncio.Lock()
        self._message_queue = asyncio.Queue()
        self._command_queue = asyncio.Queue()
        self._batch_timer = None
        self._batch_interval = 0.05  # 50ms batching window
        self._last_state_update: Dict[str, float] = {}
        self._debounce_interval = 0.1  # 100ms debounce
        self._pending_commands: defaultdict = defaultdict(dict)
        self._command_processor_task = None
        self._message_processor_task = None
        self._receive_message_task =  None
        

    def is_connected(self) -> bool:
        """Efficient connection check"""
        return self.ws is not None and self.ws.state == 1

    async def _handle_device_update(self, topic: str, payload) -> None:
        """Handle device state updates with debouncing"""
        try:
            if 'bridge' in topic:
                return

            current_time = asyncio.get_event_loop().time()
            last_update = self._last_state_update.get(topic, 0)
            
            if current_time - last_update < self._debounce_interval:
                return
                
            self._last_state_update[topic] = current_time

            if isinstance(payload, dict):
                if topic not in self.device_states:
                    self.device_states[topic] = {}
                self.device_states[topic].update(payload)
            elif isinstance(payload, list):
                try:
                    self.device_states.setdefault(topic, {}).update(dict(payload))
                except (ValueError, TypeError):
                    pass

        except Exception:
            pass

    async def _process_message_queue(self):
        """Asynchronously process incoming messages"""
        while True:
            try:
                message = await self._message_queue.get()
                data = json.loads(message)
                topic = data.get('topic', '')
                payload = data.get('payload', {})

                if topic == 'bridge/config':
                    self.bridge_info = payload
                elif not topic.startswith('bridge/'):
                    await self._handle_device_update(topic, payload)

                self._message_queue.task_done()
            except Exception:
                continue

    async def _process_command_queue(self):
        """Process batched commands"""
        while True:
            try:
                if self._batch_timer and not self._batch_timer.done():
                    await self._batch_timer
                
                if not self._pending_commands:
                    await asyncio.sleep(self._batch_interval)
                    continue

                if self.is_connected():
                    commands = self._pending_commands.copy()
                    self._pending_commands.clear()
                    
                    for device_id, payload in commands.items():
                        message = {
                            "topic": f"{device_id}/set",
                            "payload": payload
                        }
                        await self.ws.send(json.dumps(message))
                        
            except Exception:
                await asyncio.sleep(self._batch_interval)

    async def _listen_for_messages(self):
        """Listen for WebSocket messages with improved error handling"""
        while True:
            try:
                if not self.is_connected():
                    await self.connect()
                    continue

                if self.ws:
                    message = await self.ws.recv()
                    await self._message_queue.put(message)
            except websockets.exceptions.ConnectionClosed:
                self.connected = False
                self.ws = None
                await asyncio.sleep(self.retry_delay)
            except Exception:
                self.connected = False
                if self.ws:
                    await self.ws.close()
                    self.ws = None
                await asyncio.sleep(self.retry_delay)

    async def connect(self) -> bool:
        """Optimized connection management with enhanced logging"""
        logger.info("connecting using web scokets")
        async with self._connection_lock:
            if self.is_connected():
                return True

            for attempt in range(self.connection_retries):
                try:
                    start_connect_time = time.time()
                    if self.ws:
                        await self.ws.close()
                    
                    self.ws = await websockets.connect(
                        self.ws_url,
                        subprotocols=["websocket"],
                        ping_interval=None,
                        close_timeout=2,
                        max_size=2**20  # 1MB max message size
                    )
                    
                    connect_duration = time.time() - start_connect_time
                    logger.info(f"Connection attempt {attempt+1} took: {connect_duration*1000:.2f}ms")
                    
                    self.connected = True
                    
                    # Start processors if not running
                    if not self._message_processor_task or self._message_processor_task.done():
                        self._message_processor_task = asyncio.create_task(self._process_message_queue())
                    if not self._command_processor_task or self._command_processor_task.done():
                        self._command_processor_task = asyncio.create_task(self._process_command_queue())
                    if not self._receive_message_task or self._receive_message_task.done():
                        self._receive_message_task = asyncio.create_task(self._listen_for_messages())
                    logger.info("connected to webscoket")
                    return True
                    
                except Exception as e:
                    connect_duration = time.time() - start_connect_time
                    logger.info(f"Connection attempt {attempt+1} failed: {str(e)} - Duration: {connect_duration*1000:.2f}ms")
                    
                    if attempt == self.connection_retries - 1:
                        logger.info(f"Final connection attempt failed: {str(e)}")
                        return False
                    
                    # Adding delay between retries
                    await asyncio.sleep(self.retry_delay)
                    
    async def get_devices(self) -> Dict[str, dict]:
        """Get device list with connection check"""
        if not self.is_connected():
            if not await self.connect():
                return self.device_states
        return self.device_states

    async def set_multiple_devices(self, device_states: List[dict]) -> bool:
        if not device_states:
            return False

        start_time = time.time()
        
        # Check connection
        if not self.is_connected():
            connect_start = time.time()
            if not await self.connect():
                logger.info(f"Connection attempt took: {(time.time() - connect_start)*1000:.2f}ms")
                return False
            logger.info(f"Connection established in: {(time.time() - connect_start)*1000:.2f}ms")
        
        try:
            group_start = time.time()
            # Group commands by device
            device_commands = {}
            for device in device_states:
                device_id = device["device_id"]
                
                # Skip devices that don't match our known types
                if not ('switch' in device_id or 'curtain_motor' in device_id):
                    continue
                
                if device_id not in device_commands:
                    device_commands[device_id] = {}
                
                # Handle different device types
                if 'switch' in device_id:
                    # Light switch specific handling
                    device_commands[device_id][f"state_l{device['channel']}"] = "ON" if device['state'] else "OFF"
                elif 'curtain_motor' in device_id:
                    # Curtain motor specific handling
                    device_commands[device_id]["state"] = "OPEN" if device['state'] else "CLOSE"
            
            logger.info(f"Grouping took: {(time.time() - group_start)*1000:.2f}ms")
            
            # Send commands immediately
            send_start = time.time()
            for device_id, payload in device_commands.items():
                message = {
                    "topic": f"{device_id}/set",
                    "payload": payload
                }
                await self.ws.send(json.dumps(message))
                
            logger.info(f"Sending took: {(time.time() - send_start)*1000:.2f}ms")
            logger.info(f"Total operation took: {(time.time() - start_time)*1000:.2f}ms")
            return True
        
        except Exception as e:
            logger.error(f"Error in set_multiple_devices: {e}")
            return False
        
    async def disconnect(self):
        """Clean disconnect with task cleanup"""
        if self._message_processor_task:
            self._message_processor_task.cancel()
        if self._command_processor_task:
            self._command_processor_task.cancel()
        if self._batch_timer:
            self._batch_timer.cancel()
        if self.ws:
            await self.ws.close()
            self.ws = None
        self.connected = False

    def get_device_channels(self, device_id: str) -> list:
        """Get device channels efficiently"""
        if device_id not in self.device_states:
            return []
        
        return sorted(
            int(key[6:]) for key in self.device_states[device_id] 
            if key.startswith('state_l') and key[6:].isdigit()
        )

    def get_device_type(self, device_id: str) -> str:
        """Get device type with caching"""
        if device_id not in self.device_states:
            return "unknown"
            
        state = self.device_states[device_id]
        if 'presence' in state and 'illuminance_lux' in state:
            return "radar_sensor"
        elif any(key.startswith('state_l') for key in state):
            return f"{len(self.get_device_channels(device_id))}ch_switch"
        return "unknown"
