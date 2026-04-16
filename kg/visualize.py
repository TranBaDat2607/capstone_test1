"""
kg/visualize.py

Interactive KG visualization using pyvis.
Loads sample_instances.json via GraphBuilder, then renders an HTML file.

Usage
-----
    python -m kg.visualize
    python -m kg.visualize --out output/kg_graph.html
    python -m kg.visualize --instances ontology/sample_instances.json
"""
from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

# Project root (code/)
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

from kg.graph_builder import GraphBuilder
from kg.graph_store import KnowledgeGraph

# ---------------------------------------------------------------------------
# Node styling by type
# ---------------------------------------------------------------------------
NODE_STYLES: dict[str, dict] = {
    "Regulation": {"color": "#e74c3c", "shape": "diamond", "size": 30},
    "Company":    {"color": "#3498db", "shape": "star",    "size": 35},
    "Report":     {"color": "#9b59b6", "shape": "square",  "size": 25},
    "Indicator":  {"color": "#2ecc71", "shape": "dot",     "size": 15},
    "Claim":      {"color": "#f39c12", "shape": "triangle","size": 20},
    "NewsEvent":  {"color": "#1abc9c", "shape": "dot",     "size": 18},
}
DEFAULT_STYLE = {"color": "#95a5a6", "shape": "dot", "size": 15}

# Edge colors by relation type
EDGE_COLORS: dict[str, str] = {
    "amended_by":      "#e74c3c",
    "complies_with":   "#3498db",
    "extracted_from":  "#9b59b6",
    "requires":        "#2ecc71",
    "supports":        "#f39c12",
    "maps_to":         "#bdc3c7",
    "contradicted_by": "#e74c3c",
    "mentions":        "#1abc9c",
}
DEFAULT_EDGE_COLOR = "#7f8c8d"


def _node_label(node_id: str, node_type: str, props: dict) -> str:
    """Build a short display label for a node."""
    if node_type == "Regulation":
        return props.get("name", node_id)[:30]
    if node_type == "Company":
        return props.get("name", node_id)
    if node_type == "Report":
        return f"{props.get('source_file', node_id)[:25]}"
    if node_type == "Indicator":
        code = props.get("code", "")
        title = props.get("title", "")[:30]
        return f"{code} {title}".strip() or node_id
    if node_type == "Claim":
        ind = props.get("indicator_id", "")
        ctype = props.get("claim_type", "")
        return f"{ind}\n({ctype})"
    if node_type == "NewsEvent":
        return props.get("headline", node_id)[:30]
    return node_id


def _node_title(node_id: str, node_type: str, props: dict) -> str:
    """Build hover tooltip HTML for a node."""
    lines = [f"<b>{node_id}</b>", f"Type: {node_type}", "---"]
    for k, v in props.items():
        val = str(v)
        if len(val) > 120:
            val = val[:120] + "..."
        lines.append(f"{k}: {val}")
    return "<br>".join(lines)


def build_pyvis(kg: KnowledgeGraph, height: str = "900px") -> "Network":
    """Convert a KnowledgeGraph into a pyvis Network."""
    try:
        from pyvis.network import Network
    except ImportError:
        sys.exit("pyvis not installed. Run: pip install pyvis")

    net = Network(
        height=height,
        width="100%",
        directed=True,
        bgcolor="#1a1a2e",
        font_color="#ffffff",
        notebook=False,
    )

    # Physics settings for readable layout
    net.set_options("""{
        "physics": {
            "forceAtlas2Based": {
                "gravitationalConstant": -80,
                "centralGravity": 0.01,
                "springLength": 150,
                "springConstant": 0.02,
                "damping": 0.4
            },
            "solver": "forceAtlas2Based",
            "stabilization": {"iterations": 200}
        },
        "edges": {
            "arrows": {"to": {"enabled": true, "scaleFactor": 0.5}},
            "smooth": {"type": "curvedCW", "roundness": 0.15},
            "font": {"size": 9, "color": "#cccccc", "strokeWidth": 0}
        },
        "nodes": {
            "font": {"size": 11, "face": "arial"}
        },
        "interaction": {
            "hover": true,
            "tooltipDelay": 100,
            "navigationButtons": true,
            "keyboard": true
        }
    }""")

    # Add nodes
    graph_dict = kg.to_dict()
    for node in graph_dict["nodes"]:
        nid = node["node_id"]
        ntype = node["node_type"]
        props = node["properties"]
        style = NODE_STYLES.get(ntype, DEFAULT_STYLE)

        net.add_node(
            nid,
            label=_node_label(nid, ntype, props),
            title=_node_title(nid, ntype, props),
            color=style["color"],
            shape=style["shape"],
            size=style["size"],
            group=ntype,
        )

    # Add edges
    for edge in graph_dict["edges"]:
        color = EDGE_COLORS.get(edge["rel_type"], DEFAULT_EDGE_COLOR)
        net.add_edge(
            edge["source_id"],
            edge["target_id"],
            label=edge["rel_type"],
            title=f"{edge['rel_type']}<br>{edge.get('rel_id', '')}",
            color=color,
        )

    return net


def main() -> None:
    p = argparse.ArgumentParser(description="Visualize the ESG Knowledge Graph")
    p.add_argument(
        "--instances", type=Path,
        default=ROOT / "ontology" / "sample_instances.json",
        help="Path to sample_instances.json",
    )
    p.add_argument(
        "--out", type=Path,
        default=ROOT / "output" / "kg_graph.html",
        help="Output HTML file path",
    )
    p.add_argument(
        "--no-open", action="store_true",
        help="Don't auto-open the browser",
    )
    args = p.parse_args()

    if not args.instances.exists():
        sys.exit(f"ERROR: instances file not found: {args.instances}")

    # Build KG
    builder = GraphBuilder()
    builder.load_from_instances_json(args.instances)
    kg = builder.get_kg()
    stats = kg.stats()
    print(f"Loaded KG: {stats['total_nodes']} nodes, {stats['total_edges']} edges")
    print(f"  Nodes by type: {stats['nodes_by_type']}")
    print(f"  Edges by type: {stats['edges_by_type']}")

    # Build visualization
    net = build_pyvis(kg)

    # Write HTML
    args.out.parent.mkdir(parents=True, exist_ok=True)
    net.save_graph(str(args.out))
    print(f"\nWrote → {args.out}")

    if not args.no_open:
        webbrowser.open(str(args.out.resolve()))


if __name__ == "__main__":
    main()
