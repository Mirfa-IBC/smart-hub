import asyncio
import logging
import socket
import time
import numpy as np

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class AudioUDPServer:
    def __init__(self, host: str = '0.0.0.0', port: int = 12345):
        self.host = host
        self.port = port
        self.socket = None
        self._running = False
        self.last_packet_time = None
        self.packets_received = 0
        
        # Audio processing setup
        self.buffer_size = 8000  # 0.5 seconds at 16kHz
        self.audio_buffer = np.zeros(self.buffer_size, dtype=np.int16)
        self.buffer_position = 0
        self.buffer_filled = False

    async def start(self):
        """Start the UDP server."""
        try:
            logger.info(f"Starting UDP server on {self.host}:{self.port}")
            
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            
            # Set buffer sizes
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 65536)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 65536)
            
            self.socket.bind((self.host, self.port))
            self.socket.setblocking(False)
            self._running = True
            
            logger.info(f"UDP Server started successfully")
            await self.receive_loop()

        except Exception as e:
            logger.error(f"Failed to start UDP server: {e}")
            raise

    async def receive_loop(self):
        """Main loop for receiving audio data."""
        logger.info("Starting UDP receive loop")
        buffer_size = 4096
        
        while self._running and self.socket:
            try:
                loop = asyncio.get_event_loop()
                data, addr = await loop.sock_recvfrom(self.socket, buffer_size)
                
                self.last_packet_time = time.time()
                self.packets_received += 1

                await self.process_audio(data)

            except (BlockingIOError, InterruptedError):
                await asyncio.sleep(0.001)
            except Exception as e:
                logger.error(f"Error in receive loop: {e}")
                await asyncio.sleep(0.1)

    async def process_audio(self, data: bytes):
        """Process incoming audio data."""
        try:
            # Convert and downsample from 32kHz to 16kHz
            audio_data = np.frombuffer(data, dtype=np.int16)[::2]
            
            # Process in fixed-size chunks
            chunk_size = len(audio_data)
            
            # Update ring buffer
            if self.buffer_position + chunk_size > self.buffer_size:
                # Split the chunk
                first_part = self.buffer_size - self.buffer_position
                second_part = chunk_size - first_part
                
                self.audio_buffer[self.buffer_position:] = audio_data[:first_part]
                self.audio_buffer[:second_part] = audio_data[first_part:]
                self.buffer_position = second_part
            else:
                self.audio_buffer[self.buffer_position:self.buffer_position + chunk_size] = audio_data
                self.buffer_position += chunk_size
                
            if self.buffer_position >= self.buffer_size:
                self.buffer_position = 0
                self.buffer_filled = True
                
            # Here you can add your audio processing logic
            if self.buffer_filled:
                # Example: Log audio buffer statistics
                logger.debug(f"Audio buffer stats - Mean: {np.mean(self.audio_buffer):.2f}, Max: {np.max(self.audio_buffer)}")
                # Add your processing here
                pass

        except Exception as e:
            import traceback
            traceback.print_exc()
            logger.error(f"Error processing audio data: {e}")

    def stop(self):
        """Stop the UDP server."""
        logger.info("Stopping UDP server")
        self._running = False
        if self.socket:
            try:
                self.socket.close()
            except Exception as e:
                logger.error(f"Error closing UDP socket: {e}")
            self.socket = None
        logger.info("UDP Server stopped")

async def main():
    server = AudioUDPServer()
    try:
        await server.start()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    except Exception as e:
        logger.error(f"Error in main: {e}")
    finally:
        server.stop()

if __name__ == "__main__":
    asyncio.run(main())