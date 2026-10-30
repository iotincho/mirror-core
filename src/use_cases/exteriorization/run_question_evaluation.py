"""Bounded evaluation with immutable plans and durable receipts for paid attempts."""

import time

from src.core.exteriorization.evaluation import REVIEW_DIMENSIONS
from src.core.processing.errors import WorkflowFailure
from src.use_cases.exteriorization.evaluate_questions import evaluate_result, evaluation_input


class RunQuestionEvaluation:
    def __init__(self, dataset, plan, artifacts, runtime_factory, provider_factory):
        self.dataset, self.plan, self.artifacts = dataset, plan, artifacts
        self.runtime_factory, self.provider_factory = runtime_factory, provider_factory

    async def execute(self, identity, *, allow_paid=False):
        if self.plan.mode == "live" and not allow_paid:
            raise ValueError("paid_evaluation_requires_explicit_execution")
        await self.artifacts.write("plan", identity, self.plan.model_dump(mode="json"))
        results, calls = [], 0
        for case in self.dataset.cases:
            name = f"case-{case.id}"
            started = await self.artifacts.read(f"started-{case.id}", identity)
            saved = await self.artifacts.read(name, identity)
            calls += bool(started)
            if saved:
                results.append(saved)
                continue
            if started:
                raise ValueError("ambiguous_paid_attempt_requires_new_reviewed_run")
            runtime = self.runtime_factory(case, self.plan.configuration)
            snapshot, data = await evaluation_input(runtime)
            result, usage, elapsed = case.reference, {}, 0
            paid = self.plan.mode == "live" and bool(snapshot.sources)
            if paid and calls >= self.plan.max_calls:
                results.append(
                    {
                        "case_id": case.id,
                        "automatic_pass": False,
                        "checks": {},
                        "error_code": "call_limit",
                        "review": {},
                    }
                )
                continue
            if paid:
                await self.artifacts.write(
                    f"started-{case.id}", identity, {"case_id": case.id, "reserved_call": calls + 1}
                )
                calls += 1
                clock = time.monotonic()
                try:
                    result, usage = await self.provider_factory(self.plan.configuration).propose(
                        data
                    )
                except Exception:
                    # A refusal/error can still incur cost; no automatic second attempt.
                    saved = {
                        "case_id": case.id,
                        "automatic_pass": False,
                        "checks": {},
                        "error_code": "provider_failed",
                        "review": {},
                        "paid_call": True,
                        "usage": None,
                        "latency_ms": round((time.monotonic() - clock) * 1000),
                    }
                    await self.artifacts.write(name, identity, saved)
                    results.append(saved)
                    continue
                elapsed = round((time.monotonic() - clock) * 1000)
            if not snapshot.sources:
                result = {"proposals": []}
            try:
                saved = await evaluate_result(runtime, snapshot, result)
            except (ValueError, WorkflowFailure):
                saved = {
                    "case_id": case.id,
                    "automatic_pass": False,
                    "checks": {},
                    "error_code": "invalid_result",
                }
            saved.update(
                usage=usage,
                latency_ms=elapsed,
                paid_call=paid,
                review={dimension: "pending" for dimension in REVIEW_DIMENSIONS},
            )
            await self.artifacts.write(name, identity, saved)
            results.append(saved)
        return {
            "mode": self.plan.mode,
            "plan_id": identity,
            "configuration": self.plan.configuration.model_dump(mode="json"),
            "dataset_sha256": self.plan.dataset_sha256,
            "implementation_sha256": self.plan.implementation_sha256,
            "cases": results,
            "calls_reserved": calls,
            "automatic_pass": all(row["automatic_pass"] for row in results),
            "quality_validated": False,
            "ready_to_enable": False,
        }
