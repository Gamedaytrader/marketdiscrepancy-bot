import logging

# Set up basic configuration for logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Example functions where print statements should be replaced

def example_function():
    logger.info('This is an info message')
    logger.warning('This is a warning message')

    data = "Some data"
    logger.debug(f'Debugging data: {data}')

if __name__ == '__main__':
    example_function()