#!/usr/bin/env python3
"""Run the documented Alex diary questions and retain auditable API evidence."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

QUESTIONS = (
    ("01", "baseline", "¿Qué propuesta laboral recibí y por qué la rechacé?", ("06", "09")),
    ("02", "baseline", "¿Cuáles son los principales temas que aparecen en mis notas?", tuple(f"{number:02d}" for number in range(1, 16))),
    ("03", "baseline", "¿Qué preocupaciones o deseos se repiten en mis notas?", ("01", "02", "04", "06", "07", "08", "09", "12", "15")),
    ("04", "baseline", "¿Qué tensiones recurrentes aparecen en mis notas?", ("01", "02", "04", "05", "06", "07", "08", "09", "11", "12", "13", "14", "15")),
    ("05", "baseline", "¿Cómo cambié respecto de los proyectos entre enero y julio?", ("01", "04", "07", "08", "10", "13", "14")),
    ("06", "baseline", "¿Cambió para mí la importancia del dinero y la autonomía?", ("02", "06", "09", "12", "15")),
    ("07", "baseline", "¿Qué relación hay entre mi trabajo, una mudanza y mis proyectos propios?", ("01", "03", "05", "06", "09", "11", "12")),
    ("08", "baseline", "¿Qué contradicciones o tensiones aparecen en mis notas?", ("02", "04", "05", "08", "11", "12", "15")),
    ("09", "baseline", "¿Qué patrón sigo al iniciar proyectos?", ("04", "07", "08", "13", "14", "15")),
    ("10", "baseline", "¿Qué relación podría haber entre mudarme a las sierras y emprender?", ("05", "09", "11", "12")),
    ("11", "baseline", "¿Por qué la autonomía es importante para mí? Mostrame las notas.", ("01", "03", "09", "12")),
    ("12", "baseline", "¿Cómo se llama la empresa donde trabajo?", ()),
    ("13", "baseline", "¿Tengo miedo al compromiso?", ("04", "05", "07", "11")),
    ("14", "baseline", "¿Finalmente me mudaré a las sierras?", ("05", "11", "15")),
    ("15", "baseline", "Quiero dejar mi trabajo para ganar más dinero: ¿qué evidencia respalda esa afirmación?", ("02", "09", "12")),
    ("16", "incremental", "¿Cómo evolucionó mi relación con el trabajo y el emprendimiento de enero a septiembre?", ("01", "02", "09", "12", "16", "17")),
    ("17", "incremental", "¿Todavía estoy considerando mudarme?", ("05", "11", "15", "18")),
    ("18", "incremental", "¿Qué esperaba de las sierras y qué viví después?", ("05", "11", "15", "18")),
)


def request_json(url: str, *, method: str = "GET", payload: dict | None = None, cookie: str | None = None):
    headers = {"Accept": "application/json"}
    body = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload).encode()
    if cookie:
        headers["Cookie"] = cookie
    try:
        with urlopen(Request(url, data=body, headers=headers, method=method), timeout=90) as response:  # noqa: S310
            return json.loads(response.read().decode())
    except HTTPError as error:
        return {"_error": {"status": error.code, "detail": error.read().decode(errors="replace")}}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("baseline", "incremental"), required=True)
    parser.add_argument("--api-url", default="http://localhost:8080/api")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cookie", required=True, help="Authenticated el_espejo_session cookie")
    args = parser.parse_args()
    base_url = args.api_url.rstrip("/")
    documents = request_json(f"{base_url}/documents", cookie=args.cookie)
    note_by_document = {item["id"]: item["metadata"].get("note_number") for item in documents}
    results = json.loads(args.output.read_text(encoding="utf-8"))["results"] if args.output.exists() else []
    completed_test_ids = {item["test_id"] for item in results}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for test_id, phase, question, expected_notes in QUESTIONS:
        if phase != args.phase or test_id in completed_test_ids:
            continue
        vector = request_json(f"{base_url}/search", method="POST", payload={"query": question, "limit": 20}, cookie=args.cookie)
        reflection = request_json(f"{base_url}/resolve", method="POST", payload={"question": question, "limit": 20, "profile_name": "v1"}, cookie=args.cookie)
        if "_error" in reflection:
            results.append({"test_id": test_id, "question": question, "expected_note_numbers": expected_notes, "strategy": "hybrid (claim vector retrieval plus graph relations)", "error": reflection["_error"], "vector_results": vector})
            args.output.write_text(json.dumps({"run_at": datetime.now(UTC).isoformat(), "phase": args.phase, "document_count": len(documents), "results": results}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"failed test {test_id}: HTTP {reflection['_error']['status']}")
            continue
        candidates = reflection["candidates"]
        cited = {claim_id for observation in reflection.get("result", {}).get("observations", []) for claim_id in observation["source_claim_ids"]}
        cited_claims = [candidate for candidate in candidates if candidate["claim_id"] in cited]
        results.append({
            "test_id": test_id,
            "question": question,
            "expected_note_numbers": expected_notes,
            "strategy": "hybrid (claim vector retrieval plus graph relations)",
            "reflection": reflection,
            "retrieved_note_numbers": sorted({note_by_document.get(candidate["document_id"]) for candidate in candidates if note_by_document.get(candidate["document_id"]) is not None}),
            "cited_note_numbers": sorted({note_by_document.get(candidate["document_id"]) for candidate in cited_claims if note_by_document.get(candidate["document_id"]) is not None}),
            "cited_claims": cited_claims,
            "vector_results": vector,
        })
        args.output.write_text(json.dumps({"run_at": datetime.now(UTC).isoformat(), "phase": args.phase, "document_count": len(documents), "results": results}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"completed test {test_id}")
    output = {"run_at": datetime.now(UTC).isoformat(), "phase": args.phase, "document_count": len(documents), "results": results}
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
