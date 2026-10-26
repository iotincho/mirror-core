"""Inventory and atomically retire legacy graph projections, preserving originals."""

import re
from contextlib import asynccontextmanager

LEGACY_VERTICES = {
    "ExtractionRun",
    "Concept",
    "Entity",
    "Claim",
    "Evidence",
    "ClaimEmbedding",
    "DocumentEmbedding",
}
LEGACY_EDGES = {
    "HAS_EXTRACTION",
    "EXTRACTED",
    "SUPPORTED_BY",
    "FROM_DOCUMENT",
    "HAS_EMBEDDING",
    "CROSS_DOCUMENT_LINK",
    "ABOUT",
    "RELATES_TO",
    "SUPPORTS",
    "CONTRADICTS",
    "EXPRESSES_EMOTION",
    "DESIRES",
    "FEARS",
    "VALUES",
    "QUESTIONS",
    "DECIDES",
    "ASSOCIATES_WITH",
}


def rows(response):
    if response.get("truncated"):
        raise ValueError("Inventory response was truncated; cleanup refused")
    return response.get("result", [])


class MigrationGraph:
    def __init__(self, client, projection):
        self.client, self.projection = client, projection

    async def empty(self):
        counts = rows(
            await self.client.query("MATCH (n) RETURN count(n) AS count", language="cypher")
        )
        return not any(row["count"] for row in counts)

    async def ensure_documents(self):
        await self.client.command("CREATE VERTEX TYPE Document IF NOT EXISTS")

    async def persist_document(self, document):
        await self.projection.persist_document(document)

    async def inventory(self):
        schema = rows(await self.client.query("SELECT name, type, parentTypes FROM schema:types"))
        targets = {
            item["name"] for item in schema if item["name"] in LEGACY_VERTICES | LEGACY_EDGES
        }
        # Include every vector specification, not just the current embedding model.
        changed = True
        while changed:
            changed = False
            for item in schema:
                if set(item.get("parentTypes", [])) & targets and item["name"] not in targets:
                    targets.add(item["name"])
                    changed = True
        for name in targets:
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", name):
                raise ValueError("Unexpected schema identifier")
        records = {}
        for name in sorted(targets | {"Document"}):
            if name in {item["name"] for item in schema}:
                records[name] = rows(await self.client.query(f"SELECT FROM `{name}`"))
        return {"schema": schema, "records": records}

    @asynccontextmanager
    async def remove_derived(self, expected):
        targets = set(expected["records"]) - {"Document"}
        kinds = {item["name"]: item["type"] for item in expected["schema"]}
        # Child types first; SQL includes subtypes, so deletion is safely replayable.
        async with self.client.transaction() as transaction:
            for name in sorted(targets, key=lambda n: (kinds[n] != "edge", -len(n), n)):
                await transaction.command(f"DELETE FROM `{name}`")
            preserved = rows(await transaction.query("SELECT FROM Document"))
            if preserved != expected["records"].get("Document", []):
                raise ValueError("Graph originals changed; transaction aborted")
            for name in targets:
                if rows(await transaction.query(f"SELECT FROM `{name}`")):
                    raise ValueError("Derived graph records remain; transaction aborted")
            yield
