"""Plan/run the bundled synthetic evaluation, review outputs, or read aggregate metrics."""

import argparse
import asyncio
import json
from decimal import Decimal
from pathlib import Path

from src.core.exteriorization.evaluation import REVIEW_DIMENSIONS, EvaluationDataset, EvaluationPlan
from src.core.exteriorization.personalization import PreparationConfiguration
from src.core.exteriorization.question_policy import QuestionPolicy
from src.core.processing.artifacts import artifact_digest


def dataset():
    return EvaluationDataset.model_validate_json(
        Path(__file__).with_name("daily_question_cases.json").read_text()
    )


def implementation_digest():
    root = Path(__file__).resolve().parents[3]
    paths = [
        *sorted((root / "core/exteriorization").glob("*.py")),
        *sorted((root / "use_cases/exteriorization").glob("*.py")),
        root / "adapters/providers/openai/daily_questions.py",
        root / "adapters/storage/memory/question_evaluation.py",
    ]
    return artifact_digest({str(path.relative_to(root)): path.read_text() for path in paths})


def make_plan(args):
    config = PreparationConfiguration(
        model=args.model,
        max_input_tokens=args.max_input_tokens,
        max_output_tokens=args.max_output_tokens,
        policy=QuestionPolicy(
            max_followups=args.max_followups,
            rest_days=args.rest_days,
            silence_hours=args.silence_hours,
            general_every=args.general_every,
        ),
    )
    return EvaluationPlan(
        dataset_sha256=artifact_digest(dataset().model_dump(mode="json")),
        implementation_sha256=implementation_digest(),
        mode=args.mode,
        configuration=config,
        max_calls=args.max_calls,
        budget_usd=args.budget_usd,
        input_usd_per_million=args.input_price,
        output_usd_per_million=args.output_price,
        price_source=args.price_source,
    )


def markdown_report(report, cases):
    config = report["configuration"]
    lines = [
        "# Evaluación de pregunta diaria",
        "",
        f"Modo: `{report['mode']}`. Plan: `{report['plan_id']}`.",
        f"Modelo: `{config['model']}`. Prompt: `{config['prompt_version']}`. "
        f"Selector: `{config['selector_version']}`. Política: `{config['policy']['version']}`.",
        "",
        "Los checks automáticos no validan la calidad semántica. "
        "La revisión humana está pendiente.",
        "",
    ]
    by_id = {case.id: case for case in cases}
    for row in report["cases"]:
        case = by_id[row["case_id"]]
        lines += [
            f"## {case.id}",
            "",
            case.purpose,
            "",
            f"Comprobaciones automáticas: {'aprobadas' if row['automatic_pass'] else 'fallidas'}.",
            "",
        ]
        for note in case.notes:
            lines += [f"> {note.content}", ""]
        for proposal in row.get("proposals", {}).get("proposals", []):
            lines += [f"Tema: {proposal['label']}", ""]
            for depth, text in proposal["questions"].items():
                lines += [f"- **{depth}:** {text}"]
            lines += [""]
        if row.get("error_code"):
            lines += [f"Código: `{row['error_code']}`.", ""]
        for group in row.get("package", {}).get("question_groups", []):
            lines += [f"Selección publicada en la simulación ({group['source']}):", ""]
            lines += [f"- {question['text']}" for question in group["questions"]]
            lines += [""]
        lines += [
            "Revisar fundamento, límites, esfuerzo suave, progresión de profundidad, "
            "ausencia de presuposiciones y trato.",
            "",
        ]
    return "\n".join(lines)


def review_report(report, review):
    if review.get("plan_id") != report["plan_id"] or review.get(
        "results_sha256"
    ) != artifact_digest(report["cases"]):
        raise ValueError("review_identity_mismatch")
    rows = review.get("cases", {})
    complete = all(
        all(
            rows.get(row["case_id"], {}).get(dimension) == "pass" for dimension in REVIEW_DIMENSIONS
        )
        for row in report["cases"]
    )
    return dict(
        plan_id=report["plan_id"],
        automatic_pass=report["automatic_pass"],
        human_pass=complete,
        quality_validated=complete and report["mode"] == "live" and report["automatic_pass"],
        ready_to_enable=False,
        external_acceptance="pending",
    )


async def run(args, provider_factory, runtime_factory, artifacts_factory, close_providers=None):
    from src.use_cases.exteriorization.run_question_evaluation import RunQuestionEvaluation

    current = dataset()
    plan = EvaluationPlan.model_validate_json(Path(args.plan).read_text())
    if (
        plan.dataset_sha256 != artifact_digest(current.model_dump(mode="json"))
        or plan.implementation_sha256 != implementation_digest()
    ):
        raise ValueError("evaluation_plan_is_stale")
    identity = artifact_digest(plan.model_dump(mode="json"))
    directory = Path(args.output_dir)
    artifacts = artifacts_factory(directory / "receipts")
    try:
        report = await RunQuestionEvaluation(
            current, plan, artifacts, runtime_factory, provider_factory
        ).execute(identity, allow_paid=args.allow_paid)
    finally:
        if close_providers:
            await close_providers()
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    (directory / "report.md").write_text(markdown_report(report, current.cases))
    template = {
        "plan_id": identity,
        "results_sha256": artifact_digest(report["cases"]),
        "cases": {row["case_id"]: row.get("review", {}) for row in report["cases"]},
    }
    # A rerun never overwrites an already edited human review.
    target = directory / "review.json"
    if not target.exists():
        target.write_text(json.dumps(template, indent=2) + "\n")
    print(json.dumps({key: value for key, value in report.items() if key != "cases"}, indent=2))
    return 0 if report["automatic_pass"] else 1


def main(provider_factory, runtime_factory, artifacts_factory, metrics=None, close_providers=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan")
    plan.add_argument("--model", required=True)
    plan.add_argument("--mode", choices=["reference", "live"], default="reference")
    plan.add_argument("--max-calls", type=int, default=16)
    plan.add_argument("--max-input-tokens", type=int, default=24000)
    plan.add_argument("--max-output-tokens", type=int, default=3000)
    plan.add_argument("--max-followups", type=int, choices=range(1, 15), default=1)
    plan.add_argument("--rest-days", type=int, choices=range(1, 91), default=7)
    plan.add_argument("--silence-hours", type=int, choices=range(1, 721), default=48)
    plan.add_argument("--general-every", type=int, choices=range(2, 15), default=4)
    plan.add_argument("--budget-usd", type=Decimal)
    plan.add_argument("--input-price", type=Decimal)
    plan.add_argument("--output-price", type=Decimal)
    plan.add_argument("--price-source")
    plan.add_argument("--output", required=True)
    execute = sub.add_parser("run")
    execute.add_argument("--plan", required=True)
    execute.add_argument("--output-dir", required=True)
    execute.add_argument("--allow-paid", action="store_true")
    review = sub.add_parser("review")
    review.add_argument("--report", required=True)
    review.add_argument("--review", required=True)
    if metrics:
        stats = sub.add_parser("metrics")
        stats.add_argument("--days", type=int, choices=range(1, 31), default=7)
    args = parser.parse_args()
    try:
        if args.command == "plan":
            result = make_plan(args)
            with Path(args.output).open("x") as stream:
                json.dump(result.model_dump(mode="json"), stream, indent=2)
            print(
                json.dumps(
                    {
                        "calls_max": result.max_calls,
                        "reserved_usd": str(result.reserved_usd())
                        if result.reserved_usd() is not None
                        else None,
                        "input_tokens_max": result.max_calls
                        * result.configuration.max_input_tokens,
                        "output_tokens_max": result.max_calls
                        * result.configuration.max_output_tokens,
                    }
                )
            )
            return 0
        if args.command == "review":
            print(
                json.dumps(
                    review_report(
                        json.loads(Path(args.report).read_text()),
                        json.loads(Path(args.review).read_text()),
                    ),
                    indent=2,
                )
            )
            return 0
        if args.command == "metrics":
            print(json.dumps(asyncio.run(metrics(args.days)), indent=2))
            return 0
        return asyncio.run(
            run(args, provider_factory, runtime_factory, artifacts_factory, close_providers)
        )
    except Exception as error:
        # Do not print payload-bearing validation or SDK exceptions.
        print(json.dumps({"error": type(error).__name__, "code": "daily_question_command_failed"}))
        return 2
