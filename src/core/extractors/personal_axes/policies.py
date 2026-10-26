"""Pure normalization and literal-evidence validation."""

import unicodedata


def label_key(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).casefold().split())


def evidence_issues(response, content):
    issues = []
    for index, finding in enumerate(response.findings):
        if not finding.title.strip() or not finding.content.strip():
            issues.append({"code": "finding_empty", "finding": index})
        if not finding.tags or any(not tag.strip() or len(tag) > 160 for tag in finding.tags):
            issues.append({"code": "finding_tags_invalid", "finding": index})
        if not finding.evidence:
            issues.append({"code": "finding_evidence_missing", "finding": index})
        seen = set()
        for position, evidence in enumerate(finding.evidence):
            quote = evidence.quote
            offset, matches = 0, 0
            if quote.strip():
                while (start := content.find(quote, offset)) >= 0:
                    matches += 1
                    offset = start + 1
            if matches != 1 or quote in seen:
                issues.append(
                    {
                        "code": "finding_evidence_invalid",
                        "finding": index,
                        "evidence": position,
                        "matches": matches,
                    }
                )
            seen.add(quote)
    return issues
