import asyncio
import os
import logging
from logging_config import setup_logging

from stt import STTServer
setup_logging()
async def main():
    if not os.getenv("OPENAI_API_KEY"):
        raise ValueError("OPENAI_API_KEY environment variable not set")

    server = STTServer()
    try:
        await server.start()
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        await server.stop()

if __name__ == "__main__":
    asyncio.run(main())