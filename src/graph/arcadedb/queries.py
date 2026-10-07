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
