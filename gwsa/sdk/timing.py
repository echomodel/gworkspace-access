import time
import logging
from functools import wraps

logger = logging.getLogger(__name__)

# Dictionary to track counts per API function name
_api_call_stats = {}

def get_api_call_count():
    """Returns the total global API call count."""
    return sum(_api_call_stats.values())

def get_api_call_stats():
    """Returns a dictionary of API call counts per function."""
    return _api_call_stats.copy()

def reset_api_call_count():
    """Resets the global API call stats."""
    global _api_call_stats
    _api_call_stats = {}

def time_api_call(func):
    """A decorator to time API calls and log the duration."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        api_name = func.__name__
        
        # Track stats
        _api_call_stats[api_name] = _api_call_stats.get(api_name, 0) + 1
        
        logger.debug(f"Invoking {api_name} google api...")
        
        start_time = time.perf_counter()
        try:
            result = func(*args, **kwargs)
            duration = time.perf_counter() - start_time
            logger.debug(f"API call '{api_name}' completed in {duration:.4f}s")
            return result
        except Exception as e:
            duration = time.perf_counter() - start_time
            logger.debug(f"API call '{api_name}' failed in {duration:.4f}s: {e}")
            raise e
    return wrapper
