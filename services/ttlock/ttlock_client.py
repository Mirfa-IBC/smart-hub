#!/usr/bin/env python3
import asyncio
import logging
from bleak import BleakClient, BleakScanner
from typing import Dict, Optional, Callable
import time
import struct
import base64

class TTLockClient:
    # TTLock UUIDs
    COMMAND_UUID = "00001001-0000-1000-8000-00805f9b34fb"
    NOTIFY_UUID = "00001002-0000-1000-8000-00805f9b34fb"
    
    def __init__(self):
        self.logger = logging.getLogger('ttlock_client')
        self._client = None
        self._lock_data = None
        self._notification_callback = None
        self._command_future = None

    async def connect(self, address: str, lock_data: Dict):
        """Connect to TTLock device"""
        try:
            self._lock_data = lock_data
            self._client = BleakClient(address)
            await self._client.connect()
            
            # Setup notifications
            await self._client.start_notify(
                self.NOTIFY_UUID,
                self._handle_notification
            )
            
            return True
        except Exception as e:
            self.logger.error(f"Connection error: {e}")
            return False

    async def disconnect(self):
        """Disconnect from device"""
        if self._client and self._client.is_connected:
            await self._client.disconnect()

    async def initialize_lock(self, admin_ps: str, lock_data: Dict):
        """Initialize a new lock"""
        command = self._build_init_command(admin_ps, lock_data)
        response = await self._send_command(command)
        return self._parse_init_response(response)

    async def unlock(self):
        """Unlock the lock"""
        command = self._build_unlock_command()
        response = await self._send_command(command)
        return self._parse_unlock_response(response)

    async def lock(self):
        """Lock the lock"""
        command = self._build_lock_command()
        response = await self._send_command(command)
        return self._parse_lock_response(response)

    async def get_battery_level(self):
        """Get lock battery level"""
        command = self._build_battery_command()
        response = await self._send_command(command)
        return self._parse_battery_response(response)

    def _build_init_command(self, admin_ps: str, lock_data: Dict) -> bytes:
        """Build initialization command"""
        timestamp = int(time.time())
        
        # Command structure based on TTLock protocol
        command = bytearray([
            0xAA,  # Start
            0x55,  # Start
            0x01,  # Command type: Initialize
            0x00,  # Length (filled later)
            lock_data.get('lockVersion', 3)  # Lock version
        ])
        
        # Add admin code
        command.extend(bytes.fromhex(admin_ps))
        
        # Add timestamp
        command.extend(struct.pack('>I', timestamp))
        
        # Set length
        command[3] = len(command) - 4
        
        # Add checksum
        checksum = sum(command[2:]) & 0xFF
        command.append(checksum)
        
        return bytes(command)

    def _build_unlock_command(self) -> bytes:
        """Build unlock command"""
        timestamp = int(time.time())
        
        command = bytearray([
            0xAA,  # Start
            0x55,  # Start
            0x02,  # Command type: Unlock
            0x00,  # Length
            self._lock_data.get('lockVersion', 3)
        ])
        
        # Add lock key
        command.extend(bytes.fromhex(self._lock_data['lockKey']))
        
        # Add timestamp
        command.extend(struct.pack('>I', timestamp))
        
        # Set length
        command[3] = len(command) - 4
        
        # Add checksum
        checksum = sum(command[2:]) & 0xFF
        command.append(checksum)
        
        return bytes(command)

    async def _send_command(self, command: bytes) -> Optional[bytes]:
        """Send command to lock and wait for response"""
        try:
            if not self._client or not self._client.is_connected:
                raise Exception("Not connected to lock")

            # Create future for response
            self._command_future = asyncio.Future()
            
            # Send command
            await self._client.write_gatt_char(self.COMMAND_UUID, command)
            
            # Wait for response
            response = await asyncio.wait_for(self._command_future, timeout=5.0)
            self._command_future = None
            
            return response

        except Exception as e:
            self.logger.error(f"Command error: {e}")
            self._command_future = None
            return None

    def _handle_notification(self, sender: int, data: bytes):
        """Handle notification from lock"""
        if self._command_future and not self._command_future.done():
            self._command_future.set_result(data)

    def _parse_response(self, data: bytes) -> Dict:
        """Parse response from lock"""
        if not data or len(data) < 5:
            return {'success': False}

        command_type = data[2]
        length = data[3]
        response_data = data[4:4+length]
        
        return {
            'success': True,
            'command': command_type,
            'data': response_data
        }