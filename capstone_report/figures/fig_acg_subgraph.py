"""Render the ACG dividend cross-check subgraph exactly as it stands in Neo4j.

Backs Figure 4.1 of capstone_report/main.tex, the graph companion to
Table~\\ref{tab:crosscheck-acg-pair}: two SustainabilityClaim nodes extracted from
the same page of ACG's 2022 annual report, read in opposite directions by the same
independent cafef.vn conduct evidence.

NOT offline -- this is the one figure builder that needs the live database, because
its whole point is that the picture is the graph the running system serves, not a
redrawing of it. Requires the step06 base graph plus the step08 advisory layer:

    docker compose up -d
    python src/run.py neo4j_load --clear
    python src/run.py neo4j_sync

Run from the repo root:

    python capstone_report/figures/fig_acg_subgraph.py

Nodes, labels, relationship types and every property value in the callouts are read
from Neo4j; only the layout is fixed here, so the crossing structure is legible
instead of force-directed. Node fills follow Neo4j Browser's convention of colouring
by label; relationship colour is the one deliberate deviation (Browser draws every
relationship grey), since supports-versus-contradicts is the entire content of the
figure. Asserts the shape it expects, so a re-run against a changed graph fails
loudly rather than emitting a quietly wrong figure.
"""

from __future__ import annotations

import os
import sys
import textwrap
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyArrowPatch, FancyBboxPatch

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from esg_kg.core.paths import load_env  # noqa: E402

OUT_PATH = REPO_ROOT / "capstone_report" / "images" / "fig_acg_subgraph.png"

CLAIM_SUPPORTED = "claim_e81c8caa49ae05cd"
CLAIM_CONTRADICTED = "claim_1a45c50c5da6b99e"

# Neo4j Browser's default categorical node palette, assigned per label.
LABEL_FILL = {
    "Organization": "#C990C0",
    "SustainabilityClaim": "#4C8EDA",
    "KPIObservation": "#F79767",
    "MediaReport": "#8DCC93",
}
LABEL_RING = {
    "Organization": "#B261AA",
    "SustainabilityClaim": "#2870C2",
    "KPIObservation": "#F36924",
    "MediaReport": "#5DB665",
}

REL_STYLE = {
    "claims": {"color": "#9AA5B1", "lw": 1.6},
    "llm_supports": {"color": "#2E8B57", "lw": 2.2},
    "llm_contradicts": {"color": "#C0392B", "lw": 2.2},
}

# Layout only. Shared evidence sits between the two claims so the edges that make
# both readings land on one event cross in the middle of the figure. Kept near
# square and horizontally tight: the figure is placed at \linewidth (16cm text
# block), so every inch of canvas width shrinks the printed annotation type.
POS = {
    "n503": (0.0, 0.0),
    "n6924": (2.30, 2.35),
    "n6925": (2.30, -2.35),
    "n8534": (5.60, 3.60),
    "n8535": (5.60, 1.20),
    "n8536": (5.60, -1.20),
    "n8524": (5.60, -3.60),
}
RADIUS = 0.62


def fetch(session):
    """Pull the two dossiers' full neighbourhood back out of Neo4j."""
    nodes, edges = {}, []
    seen = set()
    for cid in (CLAIM_SUPPORTED, CLAIM_CONTRADICTED):
        rows = session.run(
            """
            MATCH (c:SustainabilityClaim {claim_id: $cid})
            MATCH (c)-[rel]-(o)
            RETURN c._node_key           AS ckey,
                   labels(c)             AS clabels,
                   properties(c)         AS cprops,
                   type(rel)             AS rtype,
                   startNode(rel)._node_key AS src,
                   endNode(rel)._node_key   AS tgt,
                   o._node_key           AS okey,
                   labels(o)             AS olabels,
                   properties(o)         AS oprops
            """,
            cid=cid,
        )
        got = False
        for r in rows:
            got = True
            for key, labels, props in (
                (r["ckey"], r["clabels"], r["cprops"]),
                (r["okey"], r["olabels"], r["oprops"]),
            ):
                if key not in nodes:
                    label = next(l for l in labels if l != "_Entity")
                    nodes[key] = {"key": key, "label": label, "props": dict(props)}
            sig = (r["src"], r["rtype"], r["tgt"])
            if sig not in seen:
                seen.add(sig)
                edges.append({"src": r["src"], "type": r["rtype"], "tgt": r["tgt"]})
        if not got:
            raise SystemExit(f"claim {cid} not found in Neo4j -- run neo4j_load + neo4j_sync")
    return nodes, edges


def check(nodes, edges):
    """Fail loudly if the graph no longer has the shape this figure describes."""
    missing = set(POS) - set(nodes)
    if missing:
        raise SystemExit(f"expected nodes absent from Neo4j: {sorted(missing)}")
    extra = set(nodes) - set(POS)
    if extra:
        raise SystemExit(
            f"Neo4j has neighbours this layout does not place: {sorted(extra)} -- "
            "the subgraph changed, update POS deliberately"
        )
    kinds = {e["type"] for e in edges}
    if not {"claims", "llm_supports", "llm_contradicts"} <= kinds:
        raise SystemExit(f"expected claims/llm_supports/llm_contradicts, got {sorted(kinds)}")
    shared = {e["tgt"] for e in edges if e["type"] == "llm_supports"} & {
        e["tgt"] for e in edges if e["type"] == "llm_contradicts"
    }
    if len(shared) < 2:
        raise SystemExit(
            "the figure's whole point is evidence cited both ways; found "
            f"{len(shared)} such node(s)"
        )
    print(f"  shared-both-ways evidence nodes: {sorted(shared)}")
    return shared


def caption_of(node):
    """The caption Neo4j Browser shows inside the circle.

    Browser truncates a caption to what the circle can hold; the same constraint
    applies here, so this is the node key plus an abbreviated class rather than the
    full claim_id or class name. Both appear in full in the callout or the caption.
    """
    short = {
        "Organization": "Org",
        "SustainabilityClaim": "Claim",
        "KPIObservation": "KPIObs",
        "MediaReport": "Media",
    }[node["label"]]
    return f"{node['key']}\n{short}"


def callout_of(node, shared):
    """The property detail placed beside the circle, all of it read from Neo4j.

    Deliberately lean. Both claims' full Vietnamese text and both cited evidence
    descriptions are already given verbatim in Table~\\ref{tab:crosscheck-acg-pair};
    repeating them here would only force the canvas wider and the printed type
    smaller. What stays is what the table cannot show: which node holds what, and
    which node is cited twice.
    """
    p, label = node["props"], node["label"]
    if label == "Organization":
        return "\n".join([_wrap(p.get("name", ""), 18), f"ticker: {p.get('ticker','')}"])
    if label == "SustainabilityClaim":
        return "\n".join(
            [
                f"assessment: {p.get('assessment','')}",
                f"source: {p.get('source_doc','')} p.{p.get('source_page','')}",
                f"valid_from: {p.get('valid_from','')}",
            ]
        )
    if label == "KPIObservation":
        val = p.get("value")
        val = f"{val:g}" if isinstance(val, (int, float)) else str(val)
        lines = [
            _wrap(p.get("kpi_type", ""), 20),
            f"{val} {p.get('unit','')}  ·  period {p.get('period','')}",
            f"{p.get('source_domain','')}  ·  date_uncertain: {p.get('date_uncertain')}",
        ]
        if node["key"] in shared:
            lines.append("$\\bf{cited\\ both\\ ways}$")
        return "\n".join(lines)
    return "\n".join(
        [
            f"publisher: {p.get('publisher','')}",
            f"date: {p.get('date','')}",
            f"date_uncertain: {p.get('date_uncertain')}",
        ]
    )


def _wrap(s, width):
    return "\n".join(textwrap.wrap(s, width)) or ""


def draw(nodes, edges, shared):
    # figsize is chosen against the 16cm (6.30in) text block the figure is placed
    # into: printed type = mpl point size x 6.30/width, so a wider canvas is
    # directly a smaller printed annotation. At 7.2in the scale is 0.875.
    fig, ax = plt.subplots(figsize=(7.5, 6.6))
    ax.set_xlim(-2.7, 8.7)
    ax.set_ylim(-4.8, 4.8)
    ax.set_aspect("equal")
    ax.axis("off")

    for e in edges:
        x1, y1 = POS[e["src"]]
        x2, y2 = POS[e["tgt"]]
        st = REL_STYLE[e["type"]]
        dx, dy = x2 - x1, y2 - y1
        dist = (dx * dx + dy * dy) ** 0.5
        ux, uy = dx / dist, dy / dist
        # stop the line on each circle's rim, not its centre
        sx, sy = x1 + ux * RADIUS, y1 + uy * RADIUS
        tx, ty = x2 - ux * (RADIUS + 0.09), y2 - uy * (RADIUS + 0.09)
        ax.add_patch(
            FancyArrowPatch(
                (sx, sy),
                (tx, ty),
                arrowstyle="-|>",
                mutation_scale=15,
                color=st["color"],
                lw=st["lw"],
                zorder=1,
                shrinkA=0,
                shrinkB=0,
            )
        )
        # relationship type in a rounded box on the line, Browser-style
        # The two long crossing edges (each claim to the far shared evidence node)
        # would otherwise park their label exactly where the other one's arrowhead
        # lands, so they carry theirs nearer the source instead.
        frac = 0.40 if dist > 4.0 else 0.52
        lx, ly = sx + (tx - sx) * frac, sy + (ty - sy) * frac
        ax.text(
            lx,
            ly,
            e["type"],
            fontsize=8.4,
            color=st["color"],
            ha="center",
            va="center",
            zorder=3,
            fontweight="bold" if e["type"] != "claims" else "normal",
            bbox=dict(
                boxstyle="round,pad=0.24",
                facecolor="white",
                edgecolor=st["color"],
                linewidth=0.8,
            ),
        )

    for key, (x, y) in POS.items():
        node = nodes[key]
        label = node["label"]
        ax.add_patch(
            Circle(
                (x, y),
                RADIUS,
                facecolor=LABEL_FILL[label],
                edgecolor=LABEL_RING[label],
                linewidth=2.4,
                zorder=4,
            )
        )
        ax.text(
            x,
            y,
            caption_of(node),
            fontsize=8.0,
            color="white",
            ha="center",
            va="center",
            zorder=5,
            fontweight="bold",
            linespacing=1.25,
        )

        # Callouts must not land in the middle band, where the claim->evidence
        # edge fan and its relationship labels live: claims go vertically outward
        # (above the upper claim, below the lower one), everything else sideways.
        if label == "SustainabilityClaim":
            cx, cy = x, y + (RADIUS + 0.92) * (1 if y > 0 else -1)
            ha, va = "center", "center"
        else:
            right = x > 0.5
            cx = x + (RADIUS + 0.34) if right else x - (RADIUS + 0.34)
            cy = y
            ha, va = ("left" if right else "right"), "center"
        ax.text(
            cx,
            cy,
            callout_of(node, shared),
            fontsize=8.4,
            ha=ha,
            va=va,
            color="#2B2B2B",
            zorder=6,
            linespacing=1.5,
            bbox=dict(
                boxstyle="round,pad=0.34",
                facecolor="#FBFBFC",
                edgecolor="#D3D8DE",
                linewidth=0.7,
            ),
        )

    handles = [
        plt.Line2D(
            [], [], marker="o", linestyle="none", markersize=11,
            markerfacecolor=LABEL_FILL[l], markeredgecolor=LABEL_RING[l],
            markeredgewidth=1.6, label=l,
        )
        for l in ("Organization", "SustainabilityClaim", "KPIObservation", "MediaReport")
    ] + [
        plt.Line2D([], [], color=REL_STYLE["llm_supports"]["color"], lw=2.4, label="llm_supports"),
        plt.Line2D([], [], color=REL_STYLE["llm_contradicts"]["color"], lw=2.4, label="llm_contradicts"),
        plt.Line2D([], [], color=REL_STYLE["claims"]["color"], lw=1.8, label="claims"),
    ]
    ax.legend(
        handles=handles,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.008),
        ncol=4,
        fontsize=8.6,
        frameon=True,
        framealpha=1.0,
        edgecolor="#D3D8DE",
        handletextpad=0.5,
        columnspacing=1.5,
    )

    fig.tight_layout()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT_PATH, dpi=300, facecolor="white", bbox_inches="tight")
    plt.close(fig)


def main():
    load_env()
    from neo4j import GraphDatabase

    uri = os.environ["NEO4J_URI"]
    auth = (os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"])
    database = os.environ.get("NEO4J_DATABASE") or "neo4j"
    print(f"reading {uri} db={database}")

    driver = GraphDatabase.driver(uri, auth=auth)
    try:
        with driver.session(database=database) as session:
            nodes, edges = fetch(session)
    finally:
        driver.close()

    print(f"  {len(nodes)} nodes / {len(edges)} relationships read from Neo4j")
    shared = check(nodes, edges)
    draw(nodes, edges, shared)
    print(f"wrote {OUT_PATH.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
