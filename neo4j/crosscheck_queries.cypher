// ============================================================================
// crosscheck_queries.cypher — Step 7 / P5 analyst queries (docs/SYSTEM_DESIGN.md §9.2)
//
// Run against the step-5 graph (Neo4j Browser / cypher-shell, bolt://localhost:8687)
// AFTER pushing the cross-check dossiers into Neo4j:
//     python src/sync_crosscheck_to_neo4j.py
//
// The sync writes an ADVISORY LAYER on top of the extracted graph:
//   * on each SustainabilityClaim: c.assessment (appears_supported | appears_contradicted |
//     unverified_insufficient_evidence), c.assessment_is_advisory=true, c.caveats (list),
//     c.structural_contradiction, c.kpi_gap, c.crosscheck_ticker.
//   * advisory edges (all carry llm_suggested=true + confidence / rationale / provider /
//     evidence_text / evidence_class / source_domain / year / independent):
//       (:SustainabilityClaim)-[:llm_supports]->(evidence)          -- independent support
//       (:SustainabilityClaim)-[:llm_contradicts]->(evidence)       -- incl. KPIObservation gaps
//       (:SustainabilityClaim)-[:llm_flagged_support]->(evidence)   -- company-domain, not counted
//
// These `llm_*` types are namespaced so advisory opinions are NEVER confused with extracted
// facts (the schema edges verifiedBy / contradictedBy / contradictedByMedia from step 5).
// Advisory only — evidence for human review, never a greenwashing verdict (SYSTEM_DESIGN §1.1).
// ============================================================================


// --- 1. Review queue (one row per claim): contradicted, no independent support ---
// The schema payoff (§4.1). These are the claims an analyst should look at first.
MATCH (c:SustainabilityClaim {crosscheck_ticker:'AAA'})
WHERE c.assessment = 'appears_contradicted' AND NOT (c)-[:llm_supports]->()
RETURN c.claim_id AS claim_id, c.date AS year, c.description AS claim
ORDER BY c.date;


// --- 2. Review queue with contradicting evidence (one row per evidence item) ------
MATCH (c:SustainabilityClaim {crosscheck_ticker:'AAA'})-[x:llm_contradicts]->(e)
WHERE NOT (c)-[:llm_supports]->()
RETURN c.description        AS claim,
       x.confidence         AS confidence,
       x.evidence_class     AS evidence_class,
       x.source_domain      AS source_domain,
       x.evidence_text      AS evidence,
       x.rationale          AS rationale
ORDER BY x.confidence DESC;


// --- 3. Assessment roll-up for the issuer -----------------------------------------
MATCH (c:SustainabilityClaim {crosscheck_ticker:'AAA'})
RETURN c.assessment AS assessment, count(*) AS claims
ORDER BY claims DESC;


// --- 4. One claim's full advisory dossier -----------------------------------------
// Swap in any claim_id from query 1/2. Shows every supporting/contradicting/flagged link.
MATCH (c:SustainabilityClaim {claim_id:'AAA_SC_001'})
OPTIONAL MATCH (c)-[x]->(e) WHERE x.llm_suggested = true
RETURN c.assessment AS assessment, c.caveats AS caveats,
       type(x) AS link, x.confidence AS confidence,
       x.evidence_class AS evidence_class, x.evidence_text AS evidence, x.rationale AS rationale
ORDER BY link, confidence DESC;


// --- 5. Coverage sanity: independent conduct available for the issuer --------------
// Thin coverage means "little external evidence found", NOT "the company is clean" (§8.3).
MATCH (n)
WHERE n.source_type = 'news'
  AND any(l IN labels(n) WHERE l IN ['Controversy','Penalty','MediaReport','KPIObservation','ThirdPartyVerification'])
RETURN [l IN labels(n) WHERE l <> '_Entity'][0] AS conduct_class, count(*) AS items
ORDER BY items DESC;


// --- 6. (housekeeping) remove the advisory layer, if you ever need to re-sync ------
// MATCH ()-[r]->() WHERE r.llm_suggested = true DELETE r;
// MATCH (c:SustainabilityClaim) WHERE c.crosscheck_ticker IS NOT NULL
//   REMOVE c.assessment, c.assessment_is_advisory, c.caveats,
//          c.structural_contradiction, c.kpi_gap, c.crosscheck_ticker;
