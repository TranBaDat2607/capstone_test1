import { forwardRef } from 'react'
import { Arrow, Chip, Cluster, Defs, NodeBox, Note, PANEL, T } from './primitives'

const UID = 'f2'
const W = 820
const H = 1020
const CX = 380 // main vertical spine

/** Left-margin run-order gutter: stage id aligned to each stage's vertical centre. */
const ORDER: Array<[string, number]> = [
  ['01', 103],
  ['02', 207],
  ['03', 330],
  ['03b', 342],
  ['03c', 354],
  ['04', 425],
  ['05', 514],
  ['05b', 526],
  ['05c', 538],
  ['05d', 606],
  ['06', 678],
  ['07', 751],
  ['08', 860],
  ['09', 926],
]

const Figure2 = forwardRef<SVGSVGElement>(function Figure2(_props, ref) {
  return (
    <svg
      ref={ref}
      viewBox={`0 0 ${W} ${H}`}
      width="100%"
      role="img"
      aria-label="Figure 2. Temporal knowledge-graph construction block diagram for src/esg_kg."
      style={{ display: 'block', background: '#ffffff' }}
    >
      <Defs uid={UID} />
      <rect x={0} y={0} width={W} height={H} fill="#ffffff" />

      <text x={410} y={18} textAnchor="middle" fontFamily={T.sans} fontSize={11} fontWeight={700} fill="#000">
        src/esg_kg stage pipeline — python src/run.py &lt;stage&gt;
      </text>

      {/* run-order gutter */}
      <line x1={32} y1={76} x2={32} y2={986} stroke={T.soft} strokeWidth={0.6} strokeDasharray="2 4" />
      {ORDER.map(([id, y]) => (
        <Note key={id} x={26} y={y + 3} anchor="end" text={id} size={7.5} mono fill={T.caption} />
      ))}

      {/* ============================================== input */}
      <Chip
        x={250}
        y={30}
        w={260}
        h={30}
        icon="folder"
        label="data/outputs/esg_extracted/"
        note="labeled ESG records — report + news"
      />
      <Arrow uid={UID} points={[[CX, 60], [CX, 74]]} />

      {/* 01 */}
      <NodeBox
        x={270}
        y={76}
        w={220}
        h={54}
        title="01  extract"
        sub="kpi/extract.py"
        fill={T.fill.llm}
        llm
        caption="Gemini structured output → typed KPIObservation; only ESG pages sent"
      />
      <Arrow uid={UID} points={[[CX, 130], [CX, 142]]} />
      <Chip x={280} y={144} w={200} icon="json" label="kpi_output/…/page_NNN_kpis.json" />
      <Arrow uid={UID} points={[[CX, 166], [CX, 178]]} />

      {/* 02 */}
      <NodeBox
        x={250}
        y={180}
        w={260}
        h={54}
        title="02  extract_triples"
        sub="graph/extract_triples.py"
        fill={T.fill.llm}
        llm
        caption="page text + KPIs + schema → temporal triples · --source report|news · stamps source_type"
      />
      <Arrow uid={UID} points={[[CX, 234], [CX, 246]]} />
      <Chip x={277} y={248} w={206} icon="graph" label="graph_output/graphs/<doc>/page{N}.json" />
      <Arrow uid={UID} points={[[CX, 270], [CX, 284]]} />

      {/* ============================================== BLOCK: build_validated */}
      <Cluster
        x={40}
        y={286}
        w={720}
        h={104}
        label="BLOCK: build_validated  (03 → 03b → 03c)"
        sub="writes its artifact exactly once"
        tint={PANEL.validated}
      />
      <NodeBox
        x={52}
        y={306}
        w={222}
        h={72}
        title="03  fix_triples"
        fill={T.fill.llm}
        llm
        caption="reverse-edge repair + schema validate (offline) → LLM batch-repair of invalid triples → aggregate"
      />
      <NodeBox
        x={290}
        y={306}
        w={222}
        h={72}
        title="03b  anchor_kpi"
        fill={T.fill.offline}
        caption="offline gazetteer match: KPIObservation → Facility edges"
      />
      <NodeBox
        x={528}
        y={306}
        w={222}
        h={72}
        title="03c  canonicalize"
        fill={T.fill.offline}
        caption="offline: KPI → 35-indicator vocabulary (alias + fuzzy); adds kpi_id, unit / value_normalized"
      />
      <Arrow uid={UID} points={[[276, 342], [288, 342]]} />
      <Arrow uid={UID} points={[[514, 342], [526, 342]]} />
      <Arrow uid={UID} points={[[CX, 390], [CX, 402]]} />
      <Chip x={270} y={404} w={220} icon="db" label="validated/all_validated_triples.json" />

      {/* 04 issuer — side input to entity resolution */}
      <NodeBox
        x={560}
        y={398}
        w={250}
        h={54}
        title="04  issuer"
        sub="registry/issuer.py"
        fill={T.fill.llm}
        llm
        caption="run-once bootstrap: name variants → config/issuer_registry.json (hand-confirmed)"
      />
      <Arrow uid={UID} points={[[685, 452], [685, 460]]} />
      <Arrow uid={UID} points={[[CX, 426], [CX, 460]]} />

      {/* ============================================== BLOCK: build_resolved */}
      <Cluster
        x={40}
        y={462}
        w={720}
        h={118}
        label="BLOCK: build_resolved  (05 → 05b → 05c)"
        sub="writes its artifact exactly once"
        tint={PANEL.resolved}
      />
      <NodeBox
        x={52}
        y={482}
        w={222}
        h={88}
        title="05  entities"
        fill={T.fill.llm}
        llm
        caption="A deterministic identity_keys + frozen issuer / standards anchors · B VN-aware blocking + embeddings · C LLM adjudication (budgeted) · D consolidate"
      />
      <NodeBox
        x={290}
        y={482}
        w={222}
        h={88}
        title="05b  provenance"
        fill={T.fill.offline}
        caption="offline: stamps source_doc / source_page (+ article title, url for news) back onto claim and evidence nodes"
      />
      <NodeBox
        x={528}
        y={482}
        w={222}
        h={88}
        title="05c  indicators"
        fill={T.fill.offline}
        caption="offline: appends ~35 StandardIndicator nodes + partOf / measuredUnder / equivalentTo / alignsWithIndicator edges"
      />
      <Arrow uid={UID} points={[[276, 526], [288, 526]]} />
      <Arrow uid={UID} points={[[514, 526], [526, 526]]} />
      <Arrow uid={UID} points={[[CX, 580], [CX, 592]]} />
      <Chip x={270} y={594} w={220} icon="graph" label="resolved/resolved_graph.json" />

      {/* 05d optional */}
      <NodeBox
        x={44}
        y={586}
        w={196}
        h={40}
        title="05d  align_claims"
        fill={T.fill.llm}
        dashed
        badge="LLM · opt"
        caption="topic → alignsWithIndicator; not a verdict"
      />
      <Arrow uid={UID} points={[[242, 605], [266, 605]]} dashed soft />

      {/* 11 export_kgc — read-only side view */}
      <NodeBox
        x={520}
        y={584}
        w={290}
        h={52}
        title="11  export_kgc"
        sub="export/export_kgc.py → graph_output/export_kgc/"
        fill={T.fill.offline}
        dashed
        caption="READ-ONLY: high-degree Organization hubs → synthetic HubBucket nodes (SSRL view); never patches the graph"
      />
      <Arrow uid={UID} points={[[492, 605], [516, 605]]} dashed soft />

      <Arrow uid={UID} points={[[CX, 616], [CX, 650]]} />

      {/* 06 neo4j_load */}
      <NodeBox
        x={280}
        y={652}
        w={200}
        h={52}
        title="06  neo4j_load"
        sub="load/neo4j_load.py"
        fill={T.fill.neo4j}
        caption="{nodes, edges} → property graph; MERGE on temporal edges"
      />
      <Arrow uid={UID} points={[[482, 678], [556, 678]]} />
      <g>
        <path
          d="M 560 660 V 690 a 95 11 0 0 0 190 0 V 660 Z"
          fill={T.fill.neo4j}
          stroke={T.stroke}
          strokeWidth={T.sw}
        />
        <ellipse cx={655} cy={660} rx={95} ry={11} fill="#fff" stroke={T.stroke} strokeWidth={T.sw} />
        <text x={655} y={679} textAnchor="middle" fontFamily={T.sans} fontSize={10} fontWeight={700} fill="#111">
          Neo4j
        </text>
        <text x={655} y={690} textAnchor="middle" fontFamily={T.mono} fontSize={7} fill={T.caption}>
          bolt://localhost:8687
        </text>
      </g>
      <Arrow uid={UID} points={[[CX, 704], [CX, 718]]} />

      {/* 07 claims_vs_conduct */}
      <NodeBox
        x={250}
        y={720}
        w={260}
        h={62}
        title="07  claims_vs_conduct"
        sub="crosscheck/claims_vs_conduct.py"
        fill={T.fill.llm}
        llm
        caption="per SustainabilityClaim: retrieve conduct candidates (issuer + topic + temporal window) → LLM adjudicates supports / contradicts / irrelevant"
      />
      <Arrow uid={UID} points={[[CX, 782], [CX, 794]]} />
      <Chip x={266} y={796} w={228} icon="json" label="crosscheck/<ticker>_claim_assessments.json" />
      <Arrow uid={UID} points={[[CX, 818], [CX, 832]]} />

      {/* 08 neo4j_sync */}
      <NodeBox
        x={280}
        y={834}
        w={200}
        h={52}
        title="08  neo4j_sync"
        sub="load/neo4j_sync.py"
        fill={T.fill.neo4j}
        caption="MERGE dossier + evidence edges onto the advisory layer; idempotent"
      />
      <Arrow uid={UID} points={[[482, 860], [786, 860], [786, 676], [754, 676]]} dashed soft />
      <Arrow uid={UID} points={[[CX, 886], [CX, 900]]} />

      {/* 09 claim_ledger */}
      <NodeBox
        x={265}
        y={902}
        w={230}
        h={48}
        title="09  claim_ledger"
        sub="report/claim_ledger.py"
        fill={T.fill.ledger}
        caption="Neo4j-only, no LLM: contradicted → supported → unverified"
      />
      <Arrow uid={UID} points={[[CX, 950], [CX, 962]]} />
      <Chip x={280} y={964} w={200} icon="md" label="<ticker>_claim_ledger.md" />

      <Note
        x={40}
        y={1002}
        italic
        fill={T.soft}
        text="Solid = main run order.  Dashed grey = optional, read-only, or advisory write-back.  Orange pill = calls Gemini."
      />
    </svg>
  )
})

export default Figure2
