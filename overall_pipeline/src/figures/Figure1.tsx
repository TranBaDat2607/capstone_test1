import { forwardRef } from 'react'
import { Arrow, Cluster, Defs, IconNode, NodeBox, Note, PANEL, Panel, T } from './primitives'

const UID = 'f1'
const W = 830
const H = 690

/**
 * Module names and typed icons only — no file paths, no folder names, no prose
 * captions. Panel (c) is a fresh, compact schematic of src/esg_kg's own stage names
 * (not a shrunk copy of Figure 2's stage-by-stage block diagram): one box per module,
 * grouped into the two blocks that write a shared artifact once, connected by plain
 * arrows. Colour still marks what kind of stage it is (purple = calls an LLM, near-
 * white = offline, blue = touches Neo4j) since that's a glance-able category, not
 * detail; dashed border marks optional / read-only.
 */
const Figure1 = forwardRef<SVGSVGElement>(function Figure1(_props, ref) {
  return (
    <svg
      ref={ref}
      viewBox={`0 0 ${W} ${H}`}
      width="100%"
      role="img"
      aria-label="Figure 1. End-to-end ESG pipeline architecture: report and news ingestion, ESG labeling and record extraction, and the temporal knowledge-graph construction modules."
      style={{ display: 'block', background: '#ffffff' }}
    >
      <Defs uid={UID} />
      <rect x={0} y={0} width={W} height={H} fill="#ffffff" />

      {/* ============================================== PANEL (a) */}
      <Panel x={10} y={24} w={810} h={118} letter="a" title="Report Ingestion & ESG Labeling" tint={PANEL.a} />
      <g transform="translate(30,0)">
        <IconNode x={26} y={63} icon="sheet" label="annual_report" />
        <Arrow uid={UID} points={[[60, 80], [71, 80]]} />
        <NodeBox x={73} y={66} w={117} h={28} title="download_reports" />
        <Arrow uid={UID} points={[[190, 80], [201, 80]]} />
        <IconNode x={203} y={63} icon="pdf" label="raw_pdf" />
        <Arrow uid={UID} points={[[237, 80], [248, 80]]} />

        {/* prepare_sentences sub-frame */}
        <rect x={250} y={50} width={245} height={54} rx={6} fill="#ffffff" fillOpacity={0.6} stroke={T.stroke} strokeWidth={0.8} />
        <Note x={256} y={61} text="prepare_sentences" size={8} weight={700} fill="#111" />
        <NodeBox x={256} y={66} w={101} h={28} title="pdf_extractor" />
        <Arrow uid={UID} points={[[357, 80], [365, 80]]} />
        <NodeBox x={367} y={66} w={122} h={28} title="sentence_splitter" />

        <Arrow uid={UID} points={[[495, 80], [506, 80]]} />
        <IconNode x={508} y={63} icon="json" label="sentences" />
        <Arrow uid={UID} points={[[542, 80], [553, 80]]} />
        <NodeBox
          x={555}
          y={60}
          w={132}
          h={40}
          icon="model"
          fill={T.fill.model}
          title="ViDeBERTa-v3-ESG"
          sub="esg_classifier"
        />
        <Arrow uid={UID} points={[[687, 80], [698, 80]]} />
        <IconNode x={700} y={63} icon="json" label="labeled" />

        <NodeBox x={555} y={112} w={132} h={20} title="kaggle_esg_classify" fill={T.fill.offline} dashed />
        <Arrow uid={UID} points={[[621, 112], [621, 102]]} dashed soft />
      </g>

      {/* ============================================== PANEL (b) */}
      <Panel x={10} y={152} w={810} h={142} letter="b" title="ESG Record Extraction" tint={PANEL.b} />
      <g transform="translate(30,0)">
        <IconNode x={40} y={228} icon="json" label="labeled" />
        <Arrow uid={UID} points={[[74, 245], [84, 245]]} />
        <NodeBox x={86} y={231} w={100} h={28} title="extract_esg" />
        {[
          { y: 180, icon: 'json' as const, label: 'esg_all_records' },
          { y: 215, icon: 'graph' as const, label: 'esg_by_document' },
          { y: 250, icon: 'chart' as const, label: 'esg_stats' },
        ].map((out) => (
          <g key={out.icon}>
            <IconNode x={198} y={out.y} size={30} icon={out.icon} label={out.label} labelSide="right" />
            <Arrow uid={UID} points={[[186, 245], [192, 245], [192, out.y + 15], [196, out.y + 15]]} />
          </g>
        ))}

        <line x1={369} y1={184} x2={369} y2={284} stroke={PANEL.b.stroke} strokeWidth={0.9} strokeDasharray="4 3" />

        <IconNode x={501} y={228} icon="news" label="news_labeled" />
        <Arrow uid={UID} points={[[535, 245], [545, 245]]} />
        <NodeBox x={547} y={231} w={117} h={28} title="preprocess_news" />
        <Arrow uid={UID} points={[[664, 245], [674, 245]]} />
        <IconNode x={676} y={228} icon="json" label="news_preprocessed" />

        {/* (a) → (b) handoff */}
        <Arrow uid={UID} points={[[717, 97], [717, 147], [57, 147], [57, 226]]} dashed />

        {/* (b) → (c) handoff — converges on panel (c)'s first row */}
        <path d="M 299 195 L 306 195 L 306 299" fill="none" stroke={T.stroke} strokeWidth={T.sw} />
        <path d="M 710 245 L 730 245 L 730 299" fill="none" stroke={T.stroke} strokeWidth={T.sw} />
        <path d="M 730 299 L 350 299" fill="none" stroke={T.stroke} strokeWidth={T.sw} />
        <Arrow uid={UID} points={[[350, 299], [350, 322]]} />
      </g>

      {/* ============================================== PANEL (c) */}
      <Panel x={10} y={308} w={810} h={360} letter="c" title="Knowledge-Graph Construction" tint={PANEL.c} />
      <Note
        x={48}
        y={336}
        size={7.5}
        fill={T.caption}
        text="purple = calls an LLM · blue = touches Neo4j · dashed = optional / read-only"
      />

      <g transform="translate(0,352)">
        {/* ---- row 1: extraction + validation ---- */}
        <NodeBox x={50} y={14} w={64} h={30} title="extract" fill={T.fill.llm} llm />
        <Arrow uid={UID} points={[[114, 29], [128, 29]]} />
        <NodeBox x={128} y={14} w={118} h={30} title="extract_triples" fill={T.fill.llm} llm />
        <Arrow uid={UID} points={[[246, 29], [260, 29]]} />

        <Cluster x={260} y={0} w={322} h={58} label="build_validated" sub="" tint={PANEL.validated} />
        <NodeBox x={274} y={20} w={90} h={30} title="fix_triples" fill={T.fill.llm} llm />
        <Arrow uid={UID} points={[[364, 35], [374, 35]]} />
        <NodeBox x={374} y={20} w={86} h={30} title="anchor_kpi" fill={T.fill.offline} />
        <Arrow uid={UID} points={[[460, 35], [470, 35]]} />
        <NodeBox x={470} y={20} w={98} h={30} title="canonicalize" fill={T.fill.offline} />

        <Arrow uid={UID} points={[[582, 29], [596, 29]]} />
        <NodeBox x={596} y={14} w={60} h={30} title="issuer" fill={T.fill.llm} llm />

        {/* ---- row 2: entity resolution ---- */}
        <Cluster x={50} y={82} w={294} h={58} label="build_resolved" sub="" tint={PANEL.resolved} />
        <NodeBox x={64} y={102} w={72} h={30} title="entities" fill={T.fill.llm} llm />
        <Arrow uid={UID} points={[[136, 117], [146, 117]]} />
        <NodeBox x={146} y={102} w={86} h={30} title="provenance" fill={T.fill.offline} />
        <Arrow uid={UID} points={[[232, 117], [242, 117]]} />
        <NodeBox x={242} y={102} w={88} h={30} title="indicators" fill={T.fill.offline} />

        <Arrow uid={UID} points={[[344, 111], [358, 111]]} />
        <NodeBox x={358} y={96} w={98} h={30} title="align_claims" fill={T.fill.llm} llm dashed />

        {/* export_kgc: read-only side view off the resolved block */}
        <Arrow uid={UID} points={[[197, 140], [197, 156]]} dashed soft />
        <NodeBox x={152} y={158} w={90} h={28} title="export_kgc" fill={T.fill.offline} dashed />

        {/* ---- row 3: load + cross-check + ledger ---- */}
        <NodeBox x={357} y={206} w={86} h={30} title="neo4j_load" fill={T.fill.neo4j} />
        <Arrow uid={UID} points={[[400, 236], [400, 252]]} />

        <NodeBox x={50} y={252} w={132} h={30} title="claims_vs_conduct" fill={T.fill.llm} llm />
        <Arrow uid={UID} points={[[182, 267], [196, 267]]} />
        <NodeBox x={198} y={252} w={86} h={30} title="neo4j_sync" fill={T.fill.neo4j} />
        <Arrow uid={UID} points={[[284, 267], [348, 267]]} />

        <g>
          <path
            d="M 350 252 V 274 a 50 8 0 0 0 100 0 V 252 Z"
            fill={T.fill.neo4j}
            stroke={T.stroke}
            strokeWidth={T.sw}
          />
          <ellipse cx={400} cy={252} rx={50} ry={8} fill="#fff" stroke={T.stroke} strokeWidth={T.sw} />
          <text x={400} y={272} textAnchor="middle" fontFamily={T.sans} fontSize={9.5} fontWeight={700} fill="#111">
            Neo4j
          </text>
        </g>

        <Arrow uid={UID} points={[[450, 267], [464, 267]]} />
        <NodeBox x={464} y={252} w={98} h={30} title="claim_ledger" fill={T.fill.ledger} />
      </g>
    </svg>
  )
})

export default Figure1
