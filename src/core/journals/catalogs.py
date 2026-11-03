"""Editorial approval is pinned to a goal; identifiers do not depend on wording/revision."""

import hashlib
import json

from src.core.journals.models import JournalRun, JournalTemplate, StageCatalog


def goal_hash(purpose, instructions, stage):
    return hashlib.sha256(
        json.dumps(
            [purpose, instructions, stage.objective, stage.instructions],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def catalog_for(run: JournalRun, stage):
    expected = goal_hash(run.purpose, run.instructions, stage.definition)
    return next(
        (
            item
            for item in run.catalogs
            if item.stage_key == stage.definition.key and item.goal_hash == expected
        ),
        None,
    )


def with_catalogs(template: JournalTemplate, prompts) -> JournalTemplate:
    return JournalTemplate.model_validate(
        {
            **template.model_dump(),
            "catalogs": tuple(
                StageCatalog(
                    stage_key=stage.key,
                    goal_hash=goal_hash(template.purpose, template.instructions, stage),
                    prompts=prompts[stage.key],
                )
                for stage in template.stages
            ),
        }
    )
