import boto3
import time
import threading
from botocore.config import Config
from botocore.exceptions import ClientError


class BaseRateLimitedAWSClient:
    def __init__(self,
                 service_name: str,
                 rps_limit: int = 2,
                 max_concurrent_requests: int = 5,
                 max_retries: int = 5,
                 backoff_base: int = 2,
                 client_config: Config = None,
                 **client_kwargs):

        # Create underlying boto3 client with retries disabled by default
        self._client = boto3.client(
            service_name,
            config=client_config or Config(retries={'max_attempts': 1}),
            **client_kwargs
        )

        # Rate limit and concurrency
        self.rps_limit = rps_limit
        self.semaphore = threading.Semaphore(max_concurrent_requests)
        self.max_retries = max_retries
        self.backoff_base = backoff_base

        # Thread-safe rate limit
        self._rate_lock = threading.Lock()
        self._last_request_time = [time.time()]  # Use mutable container for thread safety

    def _rate_limit(self):
        with self._rate_lock:
            now = time.time()
            elapsed = now - self._last_request_time[0]
            min_interval = 1.0 / self.rps_limit
            if elapsed < min_interval:
                sleep_time = min_interval - elapsed
                print(f"[RateLimit] Sleeping {sleep_time:.2f}s to stay under {self.rps_limit} RPS")
                time.sleep(sleep_time)
            self._last_request_time[0] = time.time()

    def _wrap_call(self, func, *args, **kwargs):
        for attempt in range(self.max_retries):
            self.semaphore.acquire()
            try:
                self._rate_limit()
                return func(*args, **kwargs)
            except ClientError as e:
                if attempt < self.max_retries - 1:
                    backoff = self.backoff_base ** attempt
                    print(f"[Retry] {func.__name__} failed: {e}. Retrying in {backoff}s...")
                    time.sleep(backoff)
                else:
                    print(f"[Retry] Final attempt failed: {e}")
                    raise
            finally:
                self.semaphore.release()

    def __getattr__(self, name):
        """
        Dynamically wrap any method of the boto3 client
        with rate limiting, concurrency, and retries.
        """
        attr = getattr(self._client, name)
        if callable(attr):
            def wrapper(*args, **kwargs):
                return self._wrap_call(attr, *args, **kwargs)
            return wrapper
        else:
            return attr
