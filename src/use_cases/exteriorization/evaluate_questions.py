"""Evaluate actual proposal/selection contracts, keeping human quality explicitly pending."""

from types import SimpleNamespace

from src.core.exteriorization.personalization import validate_proposals
from src.use_cases.exteriorization.prepare_questions import build_snapshot
from src.use_cases.exteriorization.select_prepared_questions import (
    SelectPreparedQuestions,
    select_proposals,
)


async def evaluation_input(runtime):
    return await build_snapshot(
        runtime, runtime, runtime.owner, runtime.case.now, runtime.configuration
    )


async def evaluate_result(runtime, snapshot, raw_result):
    case = runtime.case
    result = validate_proposals(raw_result, snapshot)
    runtime.prepared = (
        runtime.identifier,
        snapshot.model_dump(mode="json"),
        result.model_dump(mode="json"),
        select_proposals(runtime.identifier, runtime.owner, snapshot, result),
        runtime.configuration.model_dump(mode="json"),
    )
    prepared = await SelectPreparedQuestions(runtime).execute(
        runtime,
        SimpleNamespace(user_id=runtime.owner),
        case.now,
        case.now,
        runtime.curated(),
        runtime.configuration.policy,
        preference_version=case.now,
    )
    trigger, package, bindings = prepared
    personal = [group for group in package.question_groups if group.source == "personalized"]
    personal_ids = {dict(bindings)[group.id] for group in personal}
    checks = dict(
        contract=True,
        initial=case.expected.initial == "either" or trigger.source == case.expected.initial,
        personal_count=case.expected.min_personal <= len(personal) <= case.expected.max_personal,
        topic_limits=not personal_ids.intersection(case.expected.forbidden_topics),
        catalog_alternative=any(group.source == "generic" for group in package.question_groups),
    )
    return {
        "case_id": case.id,
        "checks": checks,
        "automatic_pass": all(checks.values()),
        "initial_source": trigger.source,
        "package": package.model_dump(mode="json"),
        "proposals": result.model_dump(mode="json"),
        "decision": runtime.decision,
    }
