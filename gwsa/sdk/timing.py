import time
import logging
from functools import wraps

logger = logging.getLogger(__name__)

def time_api_call(func):
    """A decorator to time API calls and log the duration."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.perf_counter()
        result = func(*args, **kwargs)
        end_time = time.perf_counter()
        duration = end_time - start_time
        logger.debug(f"API call '{func.__name__}' took {duration:.4f} seconds.")
        return result
    return wrapper
