import type { ReactNode } from 'react'

/**
 * Flat academic-figure primitives, sized for A4.
 *
 * The coordinate system is calibrated so that a figure ~820 units wide fills the
 * 170mm text column of an A4 page: 1 unit ≈ 0.21mm. That makes a 7.5-unit caption
 * ≈ 4.5pt and a 10.5-unit title ≈ 6.4pt in print — the reason every size here looks
 * small relative to the canvas. Do not widen the canvas without rescaling type.
 *
 * System font stacks on purpose: the PNG export rasterises the serialised SVG
 * through a canvas, where a webfont would silently fall back.
 */

export const T = {
  stroke: '#111111',
  sw: 1,
  radius: 5,
  sans: "'Helvetica Neue', Helvetica, Arial, sans-serif",
  mono: "ui-monospace, Menlo, Consolas, 'Courier New', monospace",
  serif: "Georgia, 'Times New Roman', serif",
  caption: '#555555',
  soft: '#9a9a9a',
  fill: {
    artifact: '#EEEEEE',
    script: '#E3F0FF',
    model: '#E6F5E9',
    llm: '#F0E6FA',
    neo4j: '#DCEAFB',
    offline: '#FAFAFB',
    ledger: '#EEF2F7',
    badge: '#FFD580',
  },
} as const

export const PANEL = {
  a: { fill: '#FFF9E0', stroke: '#C9A73C' },
  b: { fill: '#FDEDF3', stroke: '#C97A9B' },
  c: { fill: '#EAF1F7', stroke: '#6E93B0' },
  validated: { fill: '#FFF1E0', stroke: '#D48F3C' },
  resolved: { fill: '#E6F5E9', stroke: '#5E9E70' },
} as const

const PAD = 8
const CAP_SIZE = 7.5
const CAP_LEAD = 9.2
const CAP_ADVANCE = 3.72

export function wrap(text: string, maxChars: number): string[] {
  const words = text.split(/\s+/)
  const lines: string[] = []
  let line = ''
  for (const word of words) {
    const next = line ? `${line} ${word}` : word
    if (next.length > maxChars && line) {
      lines.push(line)
      line = word
    } else {
      line = next
    }
  }
  if (line) lines.push(line)
  return lines
}

function captionLines(text: string, boxWidth: number): string[] {
  return wrap(text, Math.max(10, Math.floor((boxWidth - PAD * 2) / CAP_ADVANCE)))
}

/* -------------------------------------------------------------- icons */

export type IconKind =
  | 'sheet'
  | 'pdf'
  | 'folder'
  | 'json'
  | 'db'
  | 'graph'
  | 'news'
  | 'chart'
  | 'md'
  | 'model'

/** 14x14 line glyphs, drawn from (x, y) top-left. Typed to the data they label. */
export function Icon({ kind, x, y, s = 14 }: { kind: IconKind; x: number; y: number; s?: number }) {
  const u = s / 14
  const p = (n: number) => n * u
  const base = { fill: 'none', stroke: T.stroke, strokeWidth: 0.9, strokeLinejoin: 'round' as const }
  const doc = `M ${p(1.5)} 0 L ${p(1.5)} ${p(14)} L ${p(12.5)} ${p(14)} L ${p(12.5)} ${p(4)} L ${p(8.5)} 0 Z`
  const fold = `M ${p(8.5)} 0 L ${p(8.5)} ${p(4)} L ${p(12.5)} ${p(4)}`

  return (
    <g transform={`translate(${x} ${y})`}>
      {kind === 'sheet' && (
        <g {...base}>
          <rect x={p(1)} y={p(1)} width={p(12)} height={p(12)} rx={p(1)} fill="#fff" />
          <path d={`M ${p(1)} ${p(5)} H ${p(13)} M ${p(1)} ${p(9)} H ${p(13)} M ${p(5.5)} ${p(1)} V ${p(13)}`} />
        </g>
      )}
      {kind === 'pdf' && (
        <g {...base}>
          <path d={doc} fill="#fff" />
          <path d={fold} />
          <path d={`M ${p(4)} ${p(7.5)} H ${p(10)} M ${p(4)} ${p(10)} H ${p(10)} M ${p(4)} ${p(12)} H ${p(8)}`} />
        </g>
      )}
      {kind === 'md' && (
        <g {...base}>
          <path d={doc} fill="#fff" />
          <path d={fold} />
          <path d={`M ${p(4)} ${p(8)} H ${p(10)} M ${p(4)} ${p(10.5)} H ${p(10)}`} />
        </g>
      )}
      {kind === 'folder' && (
        <g {...base}>
          <path
            d={`M ${p(0.5)} ${p(12.5)} L ${p(0.5)} ${p(2)} L ${p(5)} ${p(2)} L ${p(6.5)} ${p(4)} L ${p(13.5)} ${p(4)} L ${p(13.5)} ${p(12.5)} Z`}
            fill="#fff"
          />
        </g>
      )}
      {kind === 'json' && (
        <g>
          <path d={doc} {...base} fill="#fff" />
          <text
            x={p(7)}
            y={p(11)}
            textAnchor="middle"
            fontFamily={T.mono}
            fontSize={p(8)}
            fontWeight={700}
            fill={T.stroke}
          >
            {'{}'}
          </text>
        </g>
      )}
      {kind === 'db' && (
        <g {...base} fill="#fff">
          <path d={`M ${p(1)} ${p(3)} V ${p(11)} a ${p(6)} ${p(2.4)} 0 0 0 ${p(12)} 0 V ${p(3)} Z`} />
          <ellipse cx={p(7)} cy={p(3)} rx={p(6)} ry={p(2.4)} />
          <path d={`M ${p(1)} ${p(7)} a ${p(6)} ${p(2.4)} 0 0 0 ${p(12)} 0`} />
        </g>
      )}
      {kind === 'graph' && (
        <g {...base}>
          <path d={`M ${p(3)} ${p(4)} L ${p(11)} ${p(3)} M ${p(3)} ${p(4)} L ${p(7)} ${p(11)} M ${p(11)} ${p(3)} L ${p(7)} ${p(11)}`} />
          <circle cx={p(3)} cy={p(4)} r={p(2)} fill="#fff" />
          <circle cx={p(11)} cy={p(3)} r={p(2)} fill="#fff" />
          <circle cx={p(7)} cy={p(11)} r={p(2)} fill="#fff" />
        </g>
      )}
      {kind === 'news' && (
        <g {...base}>
          <rect x={p(0.5)} y={p(2)} width={p(13)} height={p(10.5)} rx={p(1)} fill="#fff" />
          <rect x={p(2.5)} y={p(4)} width={p(4)} height={p(3.5)} />
          <path
            d={`M ${p(8)} ${p(4.5)} H ${p(11.5)} M ${p(8)} ${p(7)} H ${p(11.5)} M ${p(2.5)} ${p(9.5)} H ${p(11.5)} M ${p(2.5)} ${p(11)} H ${p(9)}`}
          />
        </g>
      )}
      {kind === 'chart' && (
        <g {...base}>
          <path d={`M ${p(1)} ${p(1)} V ${p(13)} H ${p(13)}`} />
          <rect x={p(3)} y={p(8)} width={p(2.4)} height={p(5)} fill="#fff" />
          <rect x={p(6.6)} y={p(5)} width={p(2.4)} height={p(8)} fill="#fff" />
          <rect x={p(10.2)} y={p(2.5)} width={p(2.4)} height={p(10.5)} fill="#fff" />
        </g>
      )}
      {kind === 'model' && (
        <g {...base}>
          <path
            d={`M ${p(2.5)} ${p(3.5)} L ${p(7)} ${p(2)} M ${p(2.5)} ${p(3.5)} L ${p(7)} ${p(7)} M ${p(2.5)} ${p(10.5)} L ${p(7)} ${p(7)} M ${p(2.5)} ${p(10.5)} L ${p(7)} ${p(12)} M ${p(7)} ${p(2)} L ${p(11.5)} ${p(7)} M ${p(7)} ${p(7)} L ${p(11.5)} ${p(7)} M ${p(7)} ${p(12)} L ${p(11.5)} ${p(7)}`}
          />
          <circle cx={p(2.5)} cy={p(3.5)} r={p(1.5)} fill="#fff" />
          <circle cx={p(2.5)} cy={p(10.5)} r={p(1.5)} fill="#fff" />
          <circle cx={p(7)} cy={p(2)} r={p(1.5)} fill="#fff" />
          <circle cx={p(7)} cy={p(7)} r={p(1.5)} fill="#fff" />
          <circle cx={p(7)} cy={p(12)} r={p(1.5)} fill="#fff" />
          <circle cx={p(11.5)} cy={p(7)} r={p(1.5)} fill="#fff" />
        </g>
      )}
    </g>
  )
}

/* -------------------------------------------------------------- arrows */

export function Defs({ uid }: { uid: string }) {
  return (
    <defs>
      {[
        ['head', T.stroke],
        ['head-soft', T.soft],
      ].map(([id, color]) => (
        <marker
          key={id}
          id={`${uid}-${id}`}
          viewBox="0 0 10 10"
          refX="9"
          refY="5"
          markerWidth="5"
          markerHeight="5"
          orient="auto-start-reverse"
        >
          <path d="M 0 0 L 10 5 L 0 10 z" fill={color} />
        </marker>
      ))}
    </defs>
  )
}

type Pt = [number, number]

export function Arrow({
  uid,
  points,
  dashed = false,
  soft = false,
}: {
  uid: string
  points: Pt[]
  dashed?: boolean
  soft?: boolean
}) {
  const d = points.map(([x, y], i) => `${i === 0 ? 'M' : 'L'} ${x} ${y}`).join(' ')
  return (
    <path
      d={d}
      fill="none"
      stroke={soft ? T.soft : T.stroke}
      strokeWidth={soft ? 0.85 : T.sw}
      strokeDasharray={dashed ? '3.5 3' : undefined}
      markerEnd={`url(#${uid}-head${soft ? '-soft' : ''})`}
    />
  )
}

/* -------------------------------------------------------------- containers */

export function Panel({
  x,
  y,
  w,
  h,
  letter,
  title,
  tint,
  children,
}: {
  x: number
  y: number
  w: number
  h: number
  letter: string
  title: string
  tint: { fill: string; stroke: string }
  children?: ReactNode
}) {
  return (
    <g>
      <rect
        x={x}
        y={y}
        width={w}
        height={h}
        rx={7}
        fill={tint.fill}
        stroke={tint.stroke}
        strokeWidth={1.2}
        strokeDasharray="5 3.5"
      />
      <text x={x + 9} y={y + 16} fontFamily={T.serif} fontSize={11} fontWeight={700} fill="#000">
        ({letter})
      </text>
      <text x={x + 28} y={y + 16} fontFamily={T.sans} fontSize={10} fontWeight={700} fill="#111">
        {title}
      </text>
      {children}
    </g>
  )
}

export function Cluster({
  x,
  y,
  w,
  h,
  label,
  sub,
  tint,
}: {
  x: number
  y: number
  w: number
  h: number
  label: string
  sub: string
  tint: { fill: string; stroke: string }
}) {
  return (
    <g>
      <rect
        x={x}
        y={y}
        width={w}
        height={h}
        rx={7}
        fill={tint.fill}
        stroke={tint.stroke}
        strokeWidth={1.2}
        strokeDasharray="5 3.5"
      />
      <text x={x + 10} y={y + 14} fontFamily={T.sans} fontSize={9} fontWeight={700} fill="#111">
        {label}
      </text>
      <text x={x + w - 10} y={y + 14} textAnchor="end" fontFamily={T.sans} fontSize={7} fill={T.caption}>
        {sub}
      </text>
    </g>
  )
}

/* -------------------------------------------------------------- nodes */

function Badge({ x, y, label }: { x: number; y: number; label: string }) {
  const w = label.length * 4.4 + 8
  return (
    <g>
      <rect x={x - w} y={y} width={w} height={10} rx={5} fill={T.fill.badge} stroke={T.stroke} strokeWidth={0.7} />
      <text
        x={x - w / 2}
        y={y + 7.3}
        textAnchor="middle"
        fontFamily={T.sans}
        fontSize={6.2}
        fontWeight={700}
        fill="#5c3d00"
      >
        {label}
      </text>
    </g>
  )
}

export function NodeBox({
  x,
  y,
  w,
  h,
  title,
  sub,
  caption,
  fill = T.fill.script,
  dashed = false,
  llm = false,
  badge,
  icon,
}: {
  x: number
  y: number
  w: number
  h: number
  title: string
  sub?: string
  caption?: string
  fill?: string
  dashed?: boolean
  llm?: boolean
  badge?: string
  icon?: IconKind
}) {
  const lines = caption ? captionLines(caption, w - (icon ? 4 : 0)) : []
  const tx = x + PAD + (icon ? 18 : 0)
  // A box carrying only a module name centres it; there is nothing to align it against.
  const bare = !caption && !sub && !icon
  return (
    <g>
      <rect
        x={x}
        y={y}
        width={w}
        height={h}
        rx={T.radius}
        fill={fill}
        stroke={T.stroke}
        strokeWidth={T.sw}
        strokeDasharray={dashed ? '4 3' : undefined}
      />
      {icon && <Icon kind={icon} x={x + PAD} y={y + PAD} />}
      <text
        x={bare ? x + w / 2 : tx}
        y={bare ? y + h / 2 + 3.4 : y + PAD + 9}
        textAnchor={bare ? 'middle' : 'start'}
        fontFamily={T.sans}
        fontSize={9.5}
        fontWeight={700}
        fill="#111"
      >
        {title}
      </text>
      {sub && (
        <text x={tx} y={y + PAD + 19} fontFamily={T.mono} fontSize={7} fill={T.caption}>
          {sub}
        </text>
      )}
      {lines.length > 0 && (
        <text
          x={x + PAD}
          y={y + PAD + (sub ? 30 : 21)}
          fontFamily={T.sans}
          fontSize={CAP_SIZE}
          fill={T.caption}
        >
          {lines.map((line, i) => (
            <tspan key={i} x={x + PAD} dy={i === 0 ? 0 : CAP_LEAD}>
              {line}
            </tspan>
          ))}
        </text>
      )}
      {(llm || badge) && <Badge x={x + w - 5} y={y - 5} label={badge ?? 'LLM'} />}
    </g>
  )
}

/** Artifact node: typed icon plus its bare name — no path, no description. */
export function IconNode({
  x,
  y,
  size = 34,
  icon,
  label,
  labelSide = 'bottom',
  fill = T.fill.artifact,
}: {
  x: number
  y: number
  size?: number
  icon: IconKind
  label?: string
  labelSide?: 'bottom' | 'right'
  fill?: string
}) {
  const glyph = size * 0.53
  return (
    <g>
      <rect x={x} y={y} width={size} height={size} rx={4} fill={fill} stroke={T.stroke} strokeWidth={T.sw} />
      <Icon kind={icon} x={x + (size - glyph) / 2} y={y + (size - glyph) / 2} s={glyph} />
      {label && (
        <text
          x={labelSide === 'right' ? x + size + 6 : x + size / 2}
          y={labelSide === 'right' ? y + size / 2 + 2.6 : y + size + 8}
          textAnchor={labelSide === 'right' ? 'start' : 'middle'}
          fontFamily={T.mono}
          fontSize={6.8}
          fill="#111"
        >
          {label}
        </text>
      )}
    </g>
  )
}

/** Single-line artifact chip: icon typed to the payload + monospace path. */
export function Chip({
  x,
  y,
  w,
  h = 22,
  icon,
  label,
  note,
  fill = T.fill.artifact,
}: {
  x: number
  y: number
  w: number
  h?: number
  icon: IconKind
  label: string
  note?: string
  fill?: string
}) {
  return (
    <g>
      <rect x={x} y={y} width={w} height={h} rx={4} fill={fill} stroke={T.stroke} strokeWidth={T.sw} />
      <Icon kind={icon} x={x + 6} y={y + (h - 14) / 2} />
      <text x={x + 25} y={y + (note ? h / 2 - 0.5 : h / 2 + 3)} fontFamily={T.mono} fontSize={7.6} fill="#111">
        {label}
      </text>
      {note && (
        <text x={x + 25} y={y + h / 2 + 8.5} fontFamily={T.sans} fontSize={6.8} fill={T.caption}>
          {note}
        </text>
      )}
    </g>
  )
}

export function Note({
  x,
  y,
  text,
  size = 7.5,
  anchor = 'start',
  italic = false,
  weight = 400,
  fill = T.caption,
  mono = false,
}: {
  x: number
  y: number
  text: string
  size?: number
  anchor?: 'start' | 'middle' | 'end'
  italic?: boolean
  weight?: number
  fill?: string
  mono?: boolean
}) {
  return (
    <text
      x={x}
      y={y}
      textAnchor={anchor}
      fontFamily={mono ? T.mono : T.sans}
      fontSize={size}
      fontStyle={italic ? 'italic' : undefined}
      fontWeight={weight}
      fill={fill}
    >
      {text}
    </text>
  )
}

export function Chevron({ x, y, size = 11 }: { x: number; y: number; size?: number }) {
  const half = size / 2
  return (
    <path
      d={`M ${x} ${y - half} L ${x + size * 0.66} ${y} L ${x} ${y + half}`}
      fill="none"
      stroke={T.stroke}
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  )
}
