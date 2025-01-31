import asyncio
import logging
import json
import redis
from zeroconf import Zeroconf, ServiceBrowser, ServiceListener
import socket

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Redis configuration
REDIS_HOST = 'localhost'
REDIS_PORT = 6379
REDIS_KEY = 'devices'

class ESP32DiscoveryListener(ServiceListener):
    def __init__(self):
        self.found_devices = {}
        self.redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
        
    def _push_to_redis(self, device_info):
        try:
            # Convert device info to JSON string
            device_json = json.dumps(device_info)
            # Push to Redis list
            self.redis_client.lpush(REDIS_KEY, device_json)
            logger.info(f"Successfully pushed device info to Redis: {device_json}")
        except Exception as e:
            logger.error(f"Error pushing to Redis: {e}")
    
    def update_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        info = zc.get_service_info(type_, name)
        if info and info.properties:
            mac = info.properties.get(b'mac', b'').decode('utf-8')
            ip = socket.inet_ntoa(info.addresses[0])
            hostname = info.server.lower()
            port = info.port
            
            if "esp32s3" in hostname:
                logger.info(f"Updated ESP32-S3 at {ip}:{port}")
                
                # Create device info dictionary
                device_info = {
                    'mac': mac,
                    'ip': ip,
                    'port': port,
                    'hostname': hostname,
                    'properties': {
                        k.decode('utf-8'): v.decode('utf-8') 
                        for k, v in info.properties.items()
                    }
                }
                
                self.found_devices[mac] = (ip, port)
                self._push_to_redis(device_info)
    
    def remove_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        if name in self.found_devices:
            logger.info(f"Device removed: {name}")
            del self.found_devices[name]
    
    def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        info = zc.get_service_info(type_, name)
        if info and info.properties:
            mac = info.properties.get(b'mac', b'').decode('utf-8')
            ip = socket.inet_ntoa(info.addresses[0])
            hostname = info.server.lower()
            port = info.port
            
            if "esp32s3" in hostname:
                logger.info(f"Found ESP32-S3 at {ip}:{port}")
                
                # Create device info dictionary
                device_info = {
                    'mac': mac,
                    'ip': ip,
                    'port': port,
                    'hostname': hostname,
                    'properties': {
                        k.decode('utf-8'): v.decode('utf-8') 
                        for k, v in info.properties.items()
                    }
                }
                
                self.found_devices[mac] = (ip, port)
                self._push_to_redis(device_info)

async def discover_esp32s3():
    zeroconf = Zeroconf()
    listener = ESP32DiscoveryListener()
    
    browser = ServiceBrowser(zeroconf, "_esphomelib._tcp.local.", listener)
    
    try:
        while True:
            await asyncio.sleep(5)
            if listener.found_devices:
                logger.info("Currently discovered devices:")
                for mac, (ip, port) in listener.found_devices.items():
                    logger.info(f"Active device: {mac} at {ip}:{port}")
            else:
                logger.info("No devices currently found")
    except asyncio.CancelledError:
        zeroconf.close()
        raise
    
    return listener.found_devices

async def main():
    try:
        await discover_esp32s3()
    except KeyboardInterrupt:
        logger.info("Discovery stopped by user")
    except Exception as e:
        logger.error(f"Error during discovery: {e}")

if __name__ == "__main__":
    asyncio.run(main())