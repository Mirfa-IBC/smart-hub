import asyncio
from config import (
    AppConfig,
    ESPHomeConfig,
    WyomingConfig,
    AudioConfig,
    WakeWordConfig
)
from core.voice_assistant import VoiceAssistant
from utils.logger import setup_logger

logger = setup_logger(__name__)

async def main():
    # Create configuration
    config = AppConfig(
        esphome=ESPHomeConfig(
            host="192.168.1.200",  # Replace with your ESPHome device IP
            port=6053,
            encryption_key=None
        ),
        wyoming=WyomingConfig(
            host="localhost",  # Replace with your Wyoming server IP
            port=10200,
            device_name="IntegratedAssistant"
        ),
        audio=AudioConfig(
            sample_rate=16000,
            sample_width=2,
            channels=1,
            buffer_size=50
        ),
        wake_word=WakeWordConfig(
            wake_word="alexa",
            model_path=None
        )
    )
    
    # Create and run voice assistant
    assistant = VoiceAssistant(config)
    
    try:
        await assistant.run()
    except KeyboardInterrupt:
        logger.info("Stopping voice assistant...")
    except Exception as e:
        logger.error(f"Unhandled error: {e}")
    finally:
        await assistant.disconnect()

if __name__ == "__main__":
    asyncio.run(main())