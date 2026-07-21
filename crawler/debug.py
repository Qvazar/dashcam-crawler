from functools import wraps
import time
import logging

logger = logging.getLogger(__name__)

def timed(f):
    """Decorator to measure the execution time of a function."""

    @wraps(f)
    def wrapper(*args, **kwargs):
        if logger.isEnabledFor(logging.DEBUG):
            start_time = time.time()
            result = f(*args, **kwargs)
            end_time = time.time()
            elapsed_time = end_time - start_time
            logger.debug(f"Function {f.__name__} executed in {elapsed_time:.4f} seconds")
            return result
        else:
            return f(*args, **kwargs)

    return wrapper