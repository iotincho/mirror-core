"""Preview projection and temporary bridge for historical readers (stages 3/4)."""

from src.bootstrap.personal_axes_reads import build_axis_exploration
from src.extractors.personal_axes.contracts import AxisError, legacy_errors
from src.extractors.personal_axes.pagination import page


class AxisExploration:
    def __init__(self, previews):
        self.case = build_axis_exploration(
            previews.processing.sessions, previews.runtime, owner=previews.owner
        )

    @legacy_errors
    async def coverage(self, *args, **kwargs):
        return await self.case.coverage(*args, **kwargs)

    @legacy_errors
    async def finding(self, *args, **kwargs):
        return await self.case.finding(*args, **kwargs)

    @legacy_errors
    async def findings(self, *args, **kwargs):
        return await self.case.findings(*args, **kwargs)

    @legacy_errors
    async def tags(self, *args, **kwargs):
        return await self.case.tags(*args, **kwargs)

    @legacy_errors
    async def neighbors(self, *args, **kwargs):
        return await self.case.neighbors(*args, **kwargs)


async def preview_neighbors(service, preview_id, node_id=None, cursor=None, limit=30):
    results = await service.results(preview_id)
    graph = results["graph"]
    root = node_id or graph["root_id"]
    nodes = {n["id"]: n for n in graph["nodes"]}
    if root not in nodes:
        raise AxisError("axis_node_not_found", 404)
    revision = results["preview"]["revision_hash"]
    scope = [str(service.owner), str(preview_id), revision, root]
    adjacent = [e for e in graph["edges"] if root in (e["source"], e["target"])]
    neighbors = {e["target"] if e["source"] == root else e["source"] for e in adjacent}
    chosen, following = page(list(neighbors), scope, cursor, limit, lambda item: item)
    visible = set(chosen) | {root}
    # A page counts direct neighbors; finding context is bounded by the payload contract.
    finding_ids = {n for n in visible if nodes[n]["type"] == "AxisFinding"}
    for edge in graph["edges"]:
        if edge["type"] in {"HAS_FINDING", "HAS_TAG"} and (
            edge["source"] in finding_ids or edge["target"] in finding_ids
        ):
            visible.update((edge["source"], edge["target"]))
    return {
        "preview_id": str(preview_id),
        "revision_hash": revision,
        "root_id": root,
        "nodes": [nodes[n] for n in sorted(visible)],
        "edges": [e for e in graph["edges"] if e["source"] in visible and e["target"] in visible],
        "next_cursor": following,
        "limit": limit,
    }
