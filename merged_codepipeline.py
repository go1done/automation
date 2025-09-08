import functools
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError


class RateLimitedCodePipelineClient:
    def __init__(
        self,
        region_name="us-east-2",
        profile_name=None,
        rps_limit=2,
        max_concurrent_requests=5,
        max_retries=5,
        backoff_base=2,
        client_config=None,
        **client_kwargs,
    ):
        session = boto3.Session(profile_name=profile_name)

        self._client = session.client(
            "codepipeline",
            region_name=region_name,
            config=client_config or Config(max_retries={"max_attempts": 1}),
            **client_kwargs,
        )
        self._rps_limit = rps_limit
        self._semaphore = threading.Semaphore(max_concurrent_requests)
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._rate_lock = threading.Lock()
        self._last_request_time = [time.time()]

    def rate_limited(self, func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(self._max_retries):
                with self._semaphore:
                    with self._rate_lock:
                        now = time.time()
                        elapsed = now - self._last_request_time[0]
                        min_interval = 1.0 / self._rps_limit
                        if elapsed < min_interval:
                            time.sleep(min_interval - elapsed)
                        self._last_request_time[0] = time.time()
                    try:
                        return func(*args, **kwargs)
                    except ClientError as exc:
                        if attempt < self._max_retries - 1:
                            time.sleep(self._backoff_base**attempt)
                        else:
                            raise
            return None

        return wrapper

    @rate_limited
    def start_pipeline_execution(self, pipeline_name, variable_overrides=None):
        params = {"name": pipeline_name}
        if variable_overrides:
            params["variableOverrides"] = variable_overrides
        response = self._client.start_pipeline_execution(**params)
        return response.get("pipelineExecutionId") if response else None

    @rate_limited
    def get_pipeline_execution_status(self, pipeline_name, execution_id):
        response = self._client.get_pipeline_execution(
            pipelineName=pipeline_name,
            pipelineExecutionId=execution_id,
        )
        return response.get("pipelineExecution", {}).get("status") if response else None

    def trigger_pipeline(self, pipeline_name, variable_overrides=None):
        try:
            execution_id = self.start_pipeline_execution(
                pipeline_name, variable_overrides
            )
            return pipeline_name, execution_id
        except Exception as exc:
            print(f"[Trigger Error] {pipeline_name}: {exc}")
            return pipeline_name, None

    def poll_pipeline_status(
        self, pipeline_name, execution_id, abort_event, timeout=7200, poll_interval=10
    ):
        if not execution_id:
            return pipeline_name, "TriggerFailed"
        start_time = time.time()
        while not abort_event.is_set():
            if time.time() - start_time > timeout:
                return pipeline_name, "TimedOut"
            try:
                res = self.get_pipeline_execution_status(pipeline_name, execution_id)
                if res in ["Succeeded", "Failed", "Stopped"]:
                    return pipeline_name, res
                time.sleep(poll_interval)
            except Exception as exc:
                return pipeline_name, f"PollingError: {exc}"
        return pipeline_name, "Aborted"


def listen_for_abort(abort_event):
    try:
        print("\n[Abort] Press Ctrl+C or type 'q' + Enter to cancel monitoring...\n")
        while not abort_event.is_set():
            if input().strip().lower() == "q":
                abort_event.set()
    except KeyboardInterrupt:
        abort_event.set()


def run_pipelines(
    pipeline_names,
    rps_limit=2,
    max_concurrent_requests=5,
    trigger_workers=10,
    poll_workers=10,
    poll_interval=10,
    timeout=7200,
    pipeline_variables=None,  # New: dict of pipeline_name -> variable_overrides
):
    pipeline_client = RateLimitedCodePipelineClient(
        rps_limit=rps_limit, max_concurrent_requests=max_concurrent_requests
    )
    print("\n=== Phase 1: Triggering Pipelines ===")
    execution_map = {}
    with ThreadPoolExecutor(max_workers=trigger_workers) as executor:
        future_to_pipeline = {
            executor.submit(
                pipeline_client.trigger_pipeline,
                pipeline_name,
                (pipeline_variables or {}).get(pipeline_name),
            ): pipeline_name
            for pipeline_name in pipeline_names
        }
        for future in as_completed(future_to_pipeline):
            triggered_name, execution_id = future.result()
            execution_map[triggered_name] = execution_id
            print(
                f"[Triggered] {triggered_name} => Execution ID: {execution_id}"
                if execution_id
                else f"[Trigger Failed] {triggered_name}"
            )
    print("\n=== Phase 2: Polling Pipeline Statuses ===")
    abort_event = threading.Event()
    threading.Thread(target=listen_for_abort, args=(abort_event,), daemon=True).start()
    results = {}
    with ThreadPoolExecutor(max_workers=poll_workers) as executor:
        future_to_pipeline = {
            executor.submit(
                pipeline_client.poll_pipeline_status,
                pipeline_name,
                execution_id,
                abort_event,
                timeout,
                poll_interval,
            ): pipeline_name
            for pipeline_name, execution_id in execution_map.items()
            if execution_id
        }
        for future in as_completed(future_to_pipeline):
            polled_name, res = future.result()
            results[polled_name] = res
            print(f"[Result] {polled_name} => {res}")
            if abort_event.is_set():
                print("[Abort] Stopping further polling due to user interrupt.")
                break
    for pipeline_name, execution_id in execution_map.items():
        if not execution_id:
            results[pipeline_name] = "TriggerFailed"
    return results


if __name__ == "__main__":
    pipeline_names = ["pipeline1", "pipeline2"]
    results = run_pipelines(pipeline_names)
    print("\nFinal Results:")
    for name, status in results.items():
        print(f"{name}: {status}")
