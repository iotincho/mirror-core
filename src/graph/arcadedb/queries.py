"""ArcadeDB-specific Cypher and SQL used by the runtime adapter."""

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

DOCUMENT_AND_RUN = """
MERGE (document:Document {id: $id})
SET document.source = $source,
    document.title = $title,
    document.metadata_json = $metadata_json,
    document.created_at = $created_at,
    document.authored_at = $authored_at
MERGE (run:ExtractionRun {id: $run_id})
SET run.document_id = $document_id,
    run.profile_name = $profile_name,
    run.schema_version = $schema_version,
    run.prompt_version = $prompt_version,
    run.provider = $provider,
    run.model = $model,
    run.created_at = $run_created_at
SET run.origin = $origin,
    run.parent_run_id = $parent_run_id,
    run.item_graph_ids_json = $item_graph_ids_json
MERGE (document)-[:HAS_EXTRACTION]->(run)
"""

ITEMS = """
UNWIND $rows AS row
MERGE (item:{item_type} {{id: row.id}})
SET item.local_id = row.local_id,
    item.run_id = row.run_id,
    item.document_id = row.document_id,
    item.name = row.name,
    item.text = row.text,
    item.type = row.type
WITH item, row
MATCH (run:ExtractionRun {{id: row.run_id}})
MERGE (run)-[:EXTRACTED]->(item)
"""

ATTACH_EXISTING_ITEMS = """
UNWIND $rows AS row
MATCH (item:{item_type} {{id: row.id, document_id: row.document_id}})
MATCH (run:ExtractionRun {{id: row.run_id}})
MERGE (run)-[:EXTRACTED]->(item)
RETURN item.id AS id
"""

RUN_ITEM_IDS = """
MATCH (run:ExtractionRun {id: $run_id})-[:EXTRACTED]->(item)
RETURN DISTINCT item.id AS id
"""

RUN_RELATION_IDS = """
MATCH ()-[relation]->()
WHERE relation.run_id = $run_id
RETURN DISTINCT relation.id AS id
"""

EVIDENCE = """
UNWIND $rows AS row
MERGE (evidence:Evidence {id: row.id})
SET evidence.run_id = row.run_id,
    evidence.document_id = row.document_id,
    evidence.quote = row.quote,
    evidence.start_char = row.start_char,
    evidence.end_char = row.end_char,
    evidence.start_line = row.start_line,
    evidence.end_line = row.end_line
WITH evidence, row
MATCH (item {id: row.owner_id}), (document:Document {id: row.document_id})
MERGE (item)-[:SUPPORTED_BY]->(evidence)
MERGE (evidence)-[:FROM_DOCUMENT]->(document)
"""

RELATIONSHIPS = """
UNWIND $rows AS row
MATCH (source {{id: row.source_id}}), (target {{id: row.target_id}})
MERGE (source)-[relationship:{relation_type} {{id: row.id}}]->(target)
SET relationship.run_id = row.run_id,
    relationship.document_id = row.document_id,
    relationship.evidence_json = row.evidence_json
"""

CLAIM_EMBEDDINGS = """
UNWIND $rows AS row
MERGE (embedding:{embedding_type} {{id: row.id}})
SET embedding.claim_graph_id = row.claim_graph_id,
    embedding.claim_local_id = row.claim_local_id,
    embedding.document_id = row.document_id,
    embedding.run_id = row.run_id,
    embedding.profile_name = row.profile_name,
    embedding.prompt_version = row.prompt_version,
    embedding.text_hash = row.text_hash,
    embedding.vector = row.vector,
    embedding.provider = row.provider,
    embedding.model = row.model,
    embedding.dimensions = row.dimensions,
    embedding.created_at = row.created_at
WITH embedding, row
MATCH (claim:Claim {{id: row.claim_graph_id}})
MERGE (claim)-[:HAS_EMBEDDING]->(embedding)
"""

DOCUMENT_EMBEDDING = """
MERGE (embedding:{embedding_type} {{id: $id}})
SET embedding.document_id = $document_id,
    embedding.text_hash = $text_hash,
    embedding.content = $content,
    embedding.source = $source,
    embedding.metadata_json = $metadata_json,
    embedding.created_at = $created_at,
    embedding.authored_at = $authored_at,
    embedding.vector = $vector,
    embedding.provider = $provider,
    embedding.model = $model,
    embedding.dimensions = $dimensions
WITH embedding
MATCH (document:Document {{id: $document_id}})
MERGE (document)-[:HAS_EMBEDDING]->(embedding)
"""

CLAIM_DETAILS = """
MATCH (claim:Claim)
WHERE claim.id IN $claim_ids
MATCH (run:ExtractionRun {id: claim.run_id})
MATCH (document:Document {id: claim.document_id})
OPTIONAL MATCH (claim)-[:SUPPORTED_BY]->(evidence:Evidence)
WITH claim, run, document, collect(evidence) AS evidence_nodes
RETURN claim.id AS claim_id,
       claim.local_id AS claim_local_id,
       claim.document_id AS document_id,
       claim.run_id AS run_id,
       run.profile_name AS profile_name,
       run.prompt_version AS prompt_version,
       claim.text AS text,
       claim.type AS type,
       document.source AS document_source,
       document.metadata_json AS document_metadata_json,
       document.created_at AS document_created_at,
       document.authored_at AS document_authored_at,
       [item IN evidence_nodes | {
           quote: item.quote,
           start_line: item.start_line,
           end_line: item.end_line
       }] AS evidence
"""

CLAIM_RELATIONS = """
MATCH (source:Claim)-[relationship:ABOUT|RELATES_TO|SUPPORTS|CONTRADICTS|
    EXPRESSES_EMOTION|DESIRES|FEARS|VALUES|QUESTIONS|DECIDES|
    ASSOCIATES_WITH|CROSS_DOCUMENT_LINK]->(target)
WHERE source.id IN $claim_ids
RETURN source.id AS source_claim_id,
       coalesce(relationship.relation_type, type(relationship)) AS relation_type,
       target.id AS target_id,
       CASE
           WHEN target:Claim THEN 'claim'
           WHEN target:Concept THEN 'concept'
           WHEN target:Entity THEN 'entity'
           ELSE 'unknown'
       END AS target_kind,
       coalesce(target.text, target.name) AS target_text
ORDER BY source_claim_id, relation_type, target_id
"""

CROSS_DOCUMENT_LINKS = """
UNWIND $rows AS row
MATCH (source:Claim {id: row.source_claim_id}), (target:Claim {id: row.target_claim_id})
MERGE (source)-[link:CROSS_DOCUMENT_LINK {id: row.id, link_id: row.link_id}]->(target)
SET link.relation_type = row.relation_type,
    link.profile = row.profile,
    link.source_document_id = row.source_document_id,
    link.target_document_id = row.target_document_id,
    link.evidence_json = row.evidence_json
RETURN row.id AS persisted_id
"""

DELETE_DOCUMENT = """
MATCH (node)
WHERE node.document_id = $document_id OR (node:Document AND node.id = $document_id)
DETACH DELETE node
"""

# Read only the canonical projection. Reverse navigation edges share link_id
# but must not be counted as a second proposed relationship.
LINK_NEIGHBORS_BASE = """
MATCH ()-[link:CROSS_DOCUMENT_LINK]->()
WHERE link.relation_type IN $relation_types
  AND (link.source_document_id = $document_id OR link.target_document_id = $document_id)
WITH CASE WHEN link.source_document_id = $document_id
     THEN link.target_document_id ELSE link.source_document_id END AS neighbor_id
"""

LINK_NEIGHBOR_COUNT = LINK_NEIGHBORS_BASE + "RETURN count(DISTINCT neighbor_id) AS total"
LINK_NEIGHBOR_PAGE = LINK_NEIGHBORS_BASE + """
RETURN DISTINCT neighbor_id ORDER BY neighbor_id SKIP $offset LIMIT $limit
"""

LINK_NEIGHBOR_DETAILS = """
MATCH (source:Claim)-[link:CROSS_DOCUMENT_LINK]->(target:Claim)
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

EXTRACTION_READINESS = """
MATCH (run:ExtractionRun)
WHERE run.id IN $run_ids
OPTIONAL MATCH (run)-[:EXTRACTED]->(claim:Claim)
OPTIONAL MATCH (claim)-[:HAS_EMBEDDING]->(embedding)
WHERE embedding.provider = $provider AND embedding.model = $model
      AND embedding.dimensions = $dimensions
RETURN run.id AS run_id, count(DISTINCT claim.id) AS claim_count,
       count(DISTINCT embedding.claim_graph_id) AS embedded_count
"""


def vector_neighbors(embedding_type: str) -> str:
    return (
        "SELECT * FROM (SELECT expand(vector.neighbors("
        f"'{embedding_type}[vector]', :vector, :limit)))"
    )
