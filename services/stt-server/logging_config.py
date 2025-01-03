import logging

def setup_logging():
    """Set up logging configuration."""
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    # Additional handlers can be added here (e.g., for file output)
    file_handler = logging.FileHandler('app.log')
    file_handler.setLevel(logging.INFO)

    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)

    # Adding the file handler to the root logger
    logging.getLogger().addHandler(file_handler)