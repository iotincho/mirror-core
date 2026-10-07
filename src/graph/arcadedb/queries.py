"""Document storage and graph visualization queries."""

DOCUMENT = """
MERGE (document:Document {id: $id})
SET document.content = $content,
    document.source = $source,
    document.title = $title,
    document.metadata_json = $metadata_json,
    document.created_at = $created_at,
    document.authored_at = $authored_at
RETURN document.id AS id, document.content AS content
"""

DELETE_DOCUMENT = """
MATCH (node)
WHERE node.document_id = $document_id OR (node:Document AND node.id = $document_id)
DETACH DELETE node
"""

LINK_NEIGHBORS_BASE = """
MATCH ()-[link:CROSS_DOCUMENT_LINK]->()
WHERE link.relation_type IN $relation_types
  AND (link.source_document_id = $document_id OR link.target_document_id = $document_id)
WITH CASE WHEN link.source_document_id = $document_id
     THEN link.target_document_id ELSE link.source_document_id END AS neighbor_id
"""

LINK_NEIGHBOR_COUNT = LINK_NEIGHBORS_BASE + "RETURN count(DISTINCT neighbor_id) AS total"

LINK_NEIGHBOR_PAGE = (
    LINK_NEIGHBORS_BASE
    + """
RETURN DISTINCT neighbor_id ORDER BY neighbor_id SKIP $offset LIMIT $limit
"""
)

LINK_NEIGHBOR_DETAILS = """
MATCH (source)-[link:CROSS_DOCUMENT_LINK]->(target)
WHERE link.relation_type IN $relation_types
  AND (link.source_document_id = $document_id OR link.target_document_id = $document_id)
  AND link.source_document_id IN $document_ids AND link.target_document_id IN $document_ids
  AND (link.relation_type IN ['SHIFTS', 'REVISITS'] OR source.id < target.id)
RETURN DISTINCT link.link_id AS link_id, source.id AS source_claim_id,
       target.id AS target_claim_id, link.source_document_id AS source_document_id,
       link.target_document_id AS target_document_id, link.relation_type AS relation_type,
       link.profile AS profile, link.evidence_json AS evidence_json
ORDER BY link_id LIMIT $link_limit
"""

# Layer presentation is independent of each extractor's schema. An artifact-backed
# run is an administrative container; its children are projected onto the document.
GRAPH_LAYERS = """
MATCH (document:Document {id:$document_id})-[edge]-(node)
RETURN DISTINCT coalesce(edge.layer, node.layer) AS layer
"""

GRAPH_FIELDS = """
RETURN node.id AS node_id, labels(node) AS node_types,
       node.label AS node_label, node.title AS node_title,
       node.name AS node_name, node.text AS node_text,
       node.document_id AS node_document_id, node.quote AS quote,
       node.profile_id AS profile_id, edge.id AS edge_id, type(edge) AS edge_type,
       coalesce(edge.layer, node.layer) AS layer
"""

GRAPH_OUTGOING = (
    """
MATCH (document:Document {id:$document_id})-[edge]->(node)
WHERE node.artifact_hash IS NULL
"""
    + GRAPH_FIELDS
)

GRAPH_INCOMING = (
    """
MATCH (document:Document {id:$document_id})<-[edge]-(node)
WHERE node.artifact_hash IS NULL
"""
    + GRAPH_FIELDS
)

GRAPH_RUN_CHILDREN = (
    """
MATCH (document:Document {id:$document_id})-[]->(run)-[edge]->(node)
WHERE run.artifact_hash IS NOT NULL AND node.artifact_hash IS NULL
"""
    + GRAPH_FIELDS
)
