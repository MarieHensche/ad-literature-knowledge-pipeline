from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from ad_lit_pipeline.core.errors import PipelinePause
from ad_lit_pipeline.core.manifest import ManifestRecorder, utc_now
from ad_lit_pipeline.core.step import StepResult


StepCallable = Callable[[], StepResult]


def select_steps(
    pipeline: list[str],
    only_step: str | None = None,
    from_step: str | None = None,
) -> list[str]:
    """Select steps from a pipeline using --only-step or --from-step semantics."""
    if only_step and from_step:
        raise ValueError("Use only one of --only-step or --from-step.")

    if only_step:
        if only_step not in pipeline:
            raise ValueError(f"Unknown step: {only_step}")
        return [only_step]

    if from_step:
        if from_step not in pipeline:
            raise ValueError(f"Unknown step: {from_step}")
        return pipeline[pipeline.index(from_step) :]

    return list(pipeline)


def run_selected_steps(
    selected_steps: list[str],
    step_functions: dict[str, StepCallable],
    manifest: ManifestRecorder,
    dry_run: bool = False,
) -> str:
    """Run selected steps and record each result in a manifest."""
    for step_name in selected_steps:
        if dry_run:
            print(f"Would run step: {step_name}")
            continue

        print(f"Running: {step_name}")
        step_function = step_functions[step_name]
        started = time.monotonic()
        started_at = utc_now()
        try:
            result = step_function()
            result.elapsed_seconds = time.monotonic() - started
            result.metadata["started_at"] = started_at
            result.metadata["ended_at"] = utc_now()
            if result.error is not None:
                manifest.record_step(result, status="failed")
                manifest.finish(status="failed")
                print(f"Failed: {step_name} ({result.elapsed_seconds:.1f}s)")
                raise RuntimeError(result.error)
            manifest.record_step(result)
            print(f"Completed: {step_name} ({result.elapsed_seconds:.1f}s)")
        except PipelinePause as pause:
            pause_result = pause.result
            if not isinstance(pause_result, StepResult):
                pause_result = StepResult(step_name=step_name)
            pause_result.elapsed_seconds = time.monotonic() - started
            pause_result.metadata["started_at"] = started_at
            pause_result.metadata["ended_at"] = utc_now()
            pause_result.metadata["pause_message"] = str(pause)
            manifest.record_step(pause_result, status="paused")
            manifest.finish(status="paused")
            print(f"Paused: {step_name} ({pause_result.elapsed_seconds:.1f}s)")
            print(str(pause))
            return "paused"
        except Exception as error:
            result = StepResult(
                step_name=step_name,
                elapsed_seconds=time.monotonic() - started,
                error=str(error),
                metadata={"started_at": started_at, "ended_at": utc_now()},
            )
            manifest.record_step(result, status="failed")
            manifest.finish(status="failed")
            raise

    manifest.finish(status="dry_run" if dry_run else "succeeded")
    return "dry_run" if dry_run else "succeeded"


def default_trace_dir(manifest: ManifestRecorder) -> Path:
    """Return the default trace directory for a run."""
    trace_dir = manifest.run_dir / "traces"
    trace_dir.mkdir(parents=True, exist_ok=True)
    return trace_dir
