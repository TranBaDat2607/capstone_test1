import { useRef, type ReactNode, type RefObject } from 'react'
import Figure1 from './figures/Figure1'
import Figure2 from './figures/Figure2'
import { downloadPng, downloadSvg } from './lib/download'

const BUTTON =
  'border border-hairline px-3 py-1.5 font-mono text-[11px] tracking-[0.12em] text-ink-dim transition-colors hover:border-signal hover:text-signal focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-signal'

type SheetProps = {
  index: string
  title: string
  caption: string
  slug: string
  sizeNote: string
  svgRef: RefObject<SVGSVGElement | null>
  children: ReactNode
}

function Sheet({ index, title, caption, slug, sizeNote, svgRef, children }: SheetProps) {
  return (
    <section className="grid grid-cols-1 gap-6 lg:grid-cols-[9rem_1fr]">
      <div className="lg:sticky lg:top-10 lg:self-start">
        <div className="font-mono text-[11px] tracking-[0.18em] text-signal">FIG. {index}</div>
        <h2 className="mt-2 text-[15px] leading-snug font-semibold text-ink">{title}</h2>
        <div className="mt-2 font-mono text-[10px] tracking-[0.1em] text-ink-dim">{sizeNote}</div>
        <div className="mt-5 flex gap-2 lg:flex-col lg:items-start">
          <button type="button" className={BUTTON} onClick={() => downloadSvg(svgRef.current, `${slug}.svg`)}>
            SVG ↓
          </button>
          {/* 4× of an 820-unit canvas ≈ 490 dpi across a 170mm column — print-safe. */}
          <button type="button" className={BUTTON} onClick={() => downloadPng(svgRef.current, `${slug}@4x.png`, 4)}>
            PNG ↓ 4×
          </button>
        </div>
      </div>

      <figure className="m-0 max-w-[860px]">
        <div className="border border-hairline bg-white p-2">{children}</div>
        <figcaption className="mt-3 text-[12.5px] leading-relaxed text-ink-dim">{caption}</figcaption>
      </figure>
    </section>
  )
}

export default function App() {
  const fig1 = useRef<SVGSVGElement>(null)
  const fig2 = useRef<SVGSVGElement>(null)

  return (
    <main className="mx-auto max-w-[1560px] px-6 py-16 lg:px-12">
      <header className="grid grid-cols-1 gap-6 border-b border-hairline pb-10 lg:grid-cols-[9rem_1fr]">
        <div className="font-mono text-[11px] tracking-[0.18em] text-ink-dim">ESG-KG</div>
        <div>
          <h1 className="max-w-3xl text-3xl leading-[1.15] font-bold tracking-tight text-ink lg:text-[40px]">
            Pipeline architecture &amp; block diagrams
          </h1>
          <p className="mt-5 max-w-2xl text-[13.5px] leading-relaxed text-ink-dim">
            Two paper figures read directly off <span className="font-mono text-ink">src/esg_kg</span>,{' '}
            <span className="font-mono text-ink">crawl_data/</span> and{' '}
            <span className="font-mono text-ink">data_processing/</span> — not off{' '}
            <span className="font-mono text-ink">docs/</span>, which may describe a legacy pipeline shape. The
            news-crawling upstream stays an opaque external box, and no schema class names or node counts are
            invented. Both are drawn on an 820-unit canvas calibrated to the 170&nbsp;mm A4 text column, so they
            drop in at 100% scale without shrinking the type.
          </p>
        </div>
      </header>

      <div className="mt-16 flex flex-col gap-24">
        <Sheet
          index="1"
          title="End-to-End Pipeline Architecture"
          slug="figure-1-pipeline-architecture"
          sizeNote="174 × 145 mm at A4 scale"
          svgRef={fig1}
          caption="Figure 1. (a) report ingestion and ESG labeling, (b) ESG record extraction with the parallel news channel, (c) a compact schematic of the knowledge-graph construction modules — module names only, grouped into the two blocks that each write their shared artifact once. See Figure 2 for the stage-by-stage detail behind panel (c)."
        >
          <Figure1 ref={fig1} />
        </Sheet>

        <Sheet
          index="2"
          title="Temporal Knowledge-Graph Construction"
          slug="figure-2-kg-construction"
          sizeNote="170 × 211 mm — full A4 column width"
          svgRef={fig2}
          caption="Figure 2. The stage pipeline inside src/esg_kg, invoked as python src/run.py <stage>. Stages 03–03c and 05–05c collapse into the build_validated and build_resolved blocks, each writing its shared artifact exactly once. Dashed grey paths are optional, read-only, or advisory write-backs."
        >
          <Figure2 ref={fig2} />
        </Sheet>
      </div>

      <footer className="mt-24 border-t border-hairline pt-6 font-mono text-[11px] tracking-[0.12em] text-ink-dim">
        SOURCE — src/imports/pasted_text/pipeline-architecture.md
      </footer>
    </main>
  )
}
