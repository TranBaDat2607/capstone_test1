#!/usr/bin/env python3
"""Generate the synthetic graph fixtures used when the real corpus is absent.

Why these exist. ``data/``, ``graph_output/`` and ``kpi_output/`` are git-ignored
and distributed through a **private** Hugging Face dataset repo, so someone who
only has a clone of this public repository cannot obtain them. Roughly twenty
real-corpus assertions across the test suite were therefore silently skipping:
the suite reported "all pass" while a meaningful slice of it had never run.

These two files are a small, wholly synthetic stand-in — no company data, no
scraped text, nothing derived from the private snapshot. They exist so those
assertions actually execute on a bare clone.

What they are NOT: a substitute for the real corpus. Three assertions elsewhere
deliberately require real *scale* (``len(nodes) > 1000``, ``claims > 100``,
``candidates > 100``) and must keep skipping rather than be weakened to fit a
20-node graph — see ``test/_fixture_paths.py`` for that boundary.

Two artifacts are produced, and they have genuinely different shapes:

``validated_triples.json``
    A flat ``List[dict]`` of ``{subject, predicate, object, temporal_metadata}``
    — the shape ``fix_triples``/``build_validated`` write and ``entities`` reads
    (a ``{nodes, edges}`` dict here is a hard error, not an accepted variant;
    see ``test_esg_kg_issuer.py`` §4). EVERY node carries ``valid_from`` /
    ``valid_to`` / ``is_current``, because ``core.schema.validate_triple``
    requires them on both endpoints at this stage.

``resolved_graph.json``
    ``{"nodes": [...], "edges": [...]}`` where each edge references nodes by
    **integer array index** — ``neo4j_load``'s ``_node_key`` and the dossier
    ``node_index`` are positional, so node order is load-bearing and must never
    be permuted. Here time has moved (P2): T1 entities are timeless and carry
    ``temporal_versions``; only T2/T3 observation classes keep ``valid_from`` /
    ``valid_to`` / ``is_current`` on the node itself.

The graph spans 2 issuers x 2 years so multi-issuer and temporal arms are
exercised rather than merely present.

Regenerate (offline, no LLM/network/Neo4j):

    python test/fixtures/build_fixtures.py

The script validates its own output against ``config/schema.json`` and exits
non-zero if anything it emits would be rejected by the real pipeline.
"""

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

OUT_DIR = Path(__file__).resolve().parent

AAA, ACC = "AAA", "ACC"


def _t(valid_from, valid_to=None, is_current=True):
    return {"valid_from": valid_from, "valid_to": valid_to, "is_current": is_current}


def _tm(valid_from, valid_to=None, recorded_at=None):
    return {"valid_from": valid_from, "valid_to": valid_to,
            "recorded_at": recorded_at or valid_from}


def _src(ticker, year, page, sent):
    """source_id in the form REPORT_STEM_RE expects: <TICKER>_<YEAR>_pNN_sNN."""
    return f"{ticker}_{year}_p{page:02d}_s{sent:02d}"


ORG = {
    AAA: {"name": "Công ty Cổ phần Vật liệu Xanh Alpha", "ticker": AAA},
    ACC: {"name": "Công ty Cổ phần Bê tông Chí Công", "ticker": ACC},
}
FACILITY = {
    AAA: {"name": "Nhà máy Alpha Số 1"},
    ACC: {"name": "Trạm trộn Chí Công Miền Bắc"},
}

INDICATORS = [
    {"indicator_id": "TT96-6.1.1", "name": "Tổng phát thải khí nhà kính (Scope 1 + Scope 2)",
     "pillar": "Môi trường"},
    {"indicator_id": "GRI 305-1", "name": "Direct (Scope 1) GHG emissions",
     "pillar": "Môi trường"},
    {"indicator_id": "TT96-6.6.4", "name": "Tổng số giờ đào tạo cho người lao động",
     "pillar": "Xã hội"},
]


def build_validated_triples():
    """Flat triple list, pre-resolution: every endpoint carries its own time."""
    T = []

    def add(subj_cls, subj_props, pred, obj_cls, obj_props, tm):
        T.append({
            "subject": {"class": subj_cls, "properties": subj_props},
            "predicate": pred,
            "object": {"class": obj_cls, "properties": obj_props},
            "temporal_metadata": tm,
        })

    for ticker in (AAA, ACC):
        org = {**ORG[ticker], **_t("2019-01-01")}
        fac = {**FACILITY[ticker], **_t("2019-01-01")}
        add("Organization", org, "ownsFacility", "Facility", fac, _tm("2019-01-01"))
        add("Facility", fac, "locatedIn", "Location",
            {"name": "Hai Duong" if ticker == AAA else "Bac Ninh", **_t("2019-01-01")},
            _tm("2019-01-01"))

        for year in (2023, 2024):
            kpi = {
                "kpi_type": "Phát thải khí nhà kính",
                "kpi_id": "TT96-6.1.1",
                "value": 1250.5 if ticker == AAA else 880.0,
                "unit": "tCO2e",
                "unit_normalized": "tCO2e",
                "value_normalized": 1250.5 if ticker == AAA else 880.0,
                "period": str(year),
                "source_id": _src(ticker, year, 12, 3),
                "source_doc": f"{ticker}_{year}.pdf",
                "source_page": 12,
                "sentence_index": 3,
                "source_type": "report",
                "date_uncertain": False,
                **_t(f"{year}-01-01", f"{year}-12-31", is_current=(year == 2024)),
            }
            add("Organization", org, "reportsKPI", "KPIObservation", kpi,
                _tm(f"{year}-01-01", f"{year}-12-31"))
            add("KPIObservation", kpi, "observedAtFacility", "Facility", fac,
                _tm(f"{year}-01-01", f"{year}-12-31"))
            add("KPIObservation", kpi, "measuredUnder", "StandardIndicator",
                {**INDICATORS[0], **_t("2020-01-01")},
                _tm(f"{year}-01-01", f"{year}-12-31"))

        claim = {
            "claim_id": f"claim_{ticker.lower()}_2024_p07_s11",
            "claim_text": ("Chúng tôi cam kết giảm phát thải khí nhà kính 30% vào năm 2030."
                           if ticker == AAA else
                           "Nhà máy của chúng tôi bảo đảm an toàn lao động cho toàn bộ người lao động."),
            "source_id": _src(ticker, 2024, 7, 11),
            "source_doc": f"{ticker}_2024.pdf",
            "source_page": 7,
            "sentence_index": 11,
            "source_type": "report",
            **_t("2024-01-01"),
        }
        add("Organization", org, "claims", "SustainabilityClaim", claim, _tm("2024-01-01"))
        add("SustainabilityClaim", claim, "alignsWithIndicator", "StandardIndicator",
            {**INDICATORS[0 if ticker == AAA else 2], **_t("2020-01-01")},
            _tm("2024-01-01"))

    goal = {"name": "Giảm phát thải khí nhà kính 30% vào năm 2030", "target_date": "2030-12-31",
            "source_id": _src(AAA, 2024, 7, 12), **_t("2024-01-01")}
    org_aaa = {**ORG[AAA], **_t("2019-01-01")}
    T.append({"subject": {"class": "Organization", "properties": org_aaa},
              "predicate": "setsGoal",
              "object": {"class": "Goal", "properties": goal},
              "temporal_metadata": _tm("2024-01-01")})
    T.append({"subject": {"class": "Goal", "properties": goal},
              "predicate": "alignsWithIndicator",
              "object": {"class": "StandardIndicator",
                         "properties": {**INDICATORS[0], **_t("2020-01-01")}},
              "temporal_metadata": _tm("2024-01-01")})

    emission = {"scope": "Scope 1", "value": 1250.5, "unit": "tCO2e",
                "source_id": _src(AAA, 2024, 13, 2), "source_type": "report",
                **_t("2024-01-01", "2024-12-31")}
    T.append({"subject": {"class": "Organization", "properties": org_aaa},
              "predicate": "generatesEmission",
              "object": {"class": "Emission", "properties": emission},
              "temporal_metadata": _tm("2024-01-01", "2024-12-31")})
    T.append({"subject": {"class": "Emission", "properties": emission},
              "predicate": "measuredUnder",
              "object": {"class": "StandardIndicator",
                         "properties": {**INDICATORS[1], **_t("2020-01-01")}},
              "temporal_metadata": _tm("2024-01-01", "2024-12-31")})

    reg = {"name": "Thông tư 96/2020/TT-BTC", **_t("2020-01-01")}
    std = {"name": "GRI Standards", **_t("2016-01-01")}
    for ind in (INDICATORS[0], INDICATORS[2]):
        T.append({"subject": {"class": "StandardIndicator",
                              "properties": {**ind, **_t("2020-01-01")}},
                  "predicate": "partOf",
                  "object": {"class": "Regulation", "properties": reg},
                  "temporal_metadata": _tm("2020-01-01")})
    T.append({"subject": {"class": "StandardIndicator",
                          "properties": {**INDICATORS[1], **_t("2016-01-01")}},
              "predicate": "partOf",
              "object": {"class": "Standard", "properties": std},
              "temporal_metadata": _tm("2016-01-01")})
    T.append({"subject": {"class": "StandardIndicator",
                          "properties": {**INDICATORS[0], **_t("2020-01-01")}},
              "predicate": "equivalentTo",
              "object": {"class": "StandardIndicator",
                         "properties": {**INDICATORS[1], **_t("2016-01-01")}},
              "temporal_metadata": _tm("2020-01-01")})
    T.append({"subject": {"class": "Organization", "properties": org_aaa},
              "predicate": "adoptsStandard",
              "object": {"class": "Standard", "properties": std},
              "temporal_metadata": _tm("2022-01-01")})

    org_acc = {**ORG[ACC], **_t("2019-01-01")}
    media = {"title": "Trạm trộn bị phản ánh gây bụi tại khu dân cư",
             "url": "https://example.invalid/news/1", "domain": "example.invalid",
             "publish_date_normalized": "2024-05-02", "publish_year": 2024,
             "source_id": "news_acc_2024_0001", "source_type": "news",
             "date_uncertain": True, **_t("2024-05-02")}
    penalty = {"reason": "Vi phạm quy định về bụi và tiếng ồn", "amount": 120000000,
               "currency": "VND", "source_id": "news_acc_2024_0002",
               "source_type": "news", "date_uncertain": False,
               **_t("2024-05-10")}
    T.append({"subject": {"class": "Organization", "properties": org_acc},
              "predicate": "publishesReport",
              "object": {"class": "MediaReport", "properties": media},
              "temporal_metadata": _tm("2024-05-02")})
    T.append({"subject": {"class": "MediaReport", "properties": media},
              "predicate": "mentionsFacility",
              "object": {"class": "Facility",
                         "properties": {**FACILITY[ACC], **_t("2019-01-01")}},
              "temporal_metadata": _tm("2024-05-02")})
    T.append({"subject": {"class": "Organization", "properties": org_acc},
              "predicate": "subjectToPenalty",
              "object": {"class": "Penalty", "properties": penalty},
              "temporal_metadata": _tm("2024-05-10")})

    penalty_zero = {"reason": "Không bị xử phạt vi phạm môi trường trong năm",
                    "amount": 0, "currency": "VND",
                    "source_id": _src(AAA, 2024, 21, 4), "source_type": "report",
                    "date_uncertain": False, **_t("2024-01-01", "2024-12-31")}
    T.append({"subject": {"class": "Organization", "properties": org_aaa},
              "predicate": "subjectToPenalty",
              "object": {"class": "Penalty", "properties": penalty_zero},
              "temporal_metadata": _tm("2024-01-01", "2024-12-31")})

    T.append({"subject": {"class": "Organization", "properties": org_aaa},
              "predicate": "ownsFacility",
              "object": {"class": "Facility",
                         "properties": {"name": "Nhà máy sản xuất", **_t("2019-01-01")}},
              "temporal_metadata": _tm("2019-01-01")})

    cert_old = {"name": "ISO 14001", "issuer": "Bureau Veritas",
                **_t("2019-01-01", "2022-12-31", is_current=False)}
    cert_new = {"name": "ISO 14001", "issuer": "Bureau Veritas",
                **_t("2023-01-01", None, is_current=True)}
    T.append({"subject": {"class": "Certification", "properties": cert_new},
              "predicate": "supersedes",
              "object": {"class": "Certification", "properties": cert_old},
              "temporal_metadata": _tm("2023-01-01")})
    return T


def build_resolved_graph():
    """Post-resolution graph: integer-indexed edges, T1 timeless (P2)."""
    nodes, edges = [], []

    def node(cls, props, versions=None):
        n = {"class": cls, "properties": props}
        if versions:
            n["temporal_versions"] = versions
        nodes.append(n)
        return len(nodes) - 1

    def edge(s, pred, o, tm):
        edges.append({"subject": s, "predicate": pred, "object": o,
                      "temporal_metadata": tm})

    i_org = {t: node("Organization", dict(ORG[t])) for t in (AAA, ACC)}
    i_fac = {t: node("Facility", dict(FACILITY[t])) for t in (AAA, ACC)}
    i_fac_generic = node("Facility", {"name": "Nhà máy sản xuất"})
    i_loc = {AAA: node("Location", {"name": "Hai Duong"}),
             ACC: node("Location", {"name": "Bac Ninh"})}
    i_reg = node("Regulation", {"name": "Thông tư 96/2020/TT-BTC"})
    i_std = node("Standard", {"name": "GRI Standards"})
    i_ind = [node("StandardIndicator", dict(ind)) for ind in INDICATORS]

    i_cert = node(
        "Certification", {"name": "ISO 14001", "issuer": "Bureau Veritas"},
        versions=[
            {"valid_from": "2019-01-01", "valid_to": "2022-12-31", "is_current": False,
             "properties": {"name": "ISO 14001", "valid_from": "2019-01-01",
                            "valid_to": "2022-12-31", "is_current": False}},
            {"valid_from": "2023-01-01", "valid_to": None, "is_current": True,
             "properties": {"name": "ISO 14001", "valid_from": "2023-01-01",
                            "valid_to": None, "is_current": True}},
        ])

    i_kpi = {}
    for ticker in (AAA, ACC):
        for year in (2023, 2024):
            i_kpi[(ticker, year)] = node("KPIObservation", {
                "kpi_type": "Phát thải khí nhà kính", "kpi_id": "TT96-6.1.1",
                "value": 1250.5 if ticker == AAA else 880.0, "unit": "tCO2e",
                "unit_normalized": "tCO2e", "period": str(year),
                "source_id": _src(ticker, year, 12, 3),
                "source_doc": f"{ticker}_{year}.pdf", "source_page": 12,
                "sentence_index": 3, "source_type": "report", "date_uncertain": False,
                **_t(f"{year}-01-01", f"{year}-12-31", is_current=(year == 2024)),
            })

    i_claim = {}
    for ticker in (AAA, ACC):
        i_claim[ticker] = node("SustainabilityClaim", {
            "claim_id": f"claim_{ticker.lower()}_2024_p07_s11",
            "claim_text": ("Chúng tôi cam kết giảm phát thải khí nhà kính 30% vào năm 2030."
                           if ticker == AAA else
                           "Nhà máy của chúng tôi bảo đảm an toàn lao động cho toàn bộ người lao động."),
            "source_id": _src(ticker, 2024, 7, 11),
            "source_doc": f"{ticker}_2024.pdf", "source_page": 7,
            "sentence_index": 11, "source_type": "report", **_t("2024-01-01"),
        })

    i_goal = node("Goal", {"name": "Giảm phát thải khí nhà kính 30% vào năm 2030",
                           "target_date": "2030-12-31",
                           "source_id": _src(AAA, 2024, 7, 12), **_t("2024-01-01")})
    i_emis = node("Emission", {"scope": "Scope 1", "value": 1250.5, "unit": "tCO2e",
                               "source_id": _src(AAA, 2024, 13, 2),
                               "source_type": "report",
                               **_t("2024-01-01", "2024-12-31")})
    i_media = node("MediaReport", {
        "title": "Trạm trộn bị phản ánh gây bụi tại khu dân cư",
        "url": "https://example.invalid/news/1", "domain": "example.invalid",
        "article_title": "Trạm trộn bị phản ánh gây bụi tại khu dân cư",
        "publish_date_normalized": "2024-05-02", "publish_year": 2024,
        "source_id": "news_acc_2024_0001", "source_type": "news",
        "date_uncertain": True, **_t("2024-05-02")})
    i_pen_zero = node("Penalty", {
        "reason": "Không bị xử phạt vi phạm môi trường trong năm", "amount": 0,
        "currency": "VND", "source_id": _src(AAA, 2024, 21, 4),
        "source_type": "report", "date_uncertain": False,
        **_t("2024-01-01", "2024-12-31")})
    i_pen = node("Penalty", {"reason": "Vi phạm quy định về bụi và tiếng ồn",
                             "amount": 120000000, "currency": "VND",
                             "source_id": "news_acc_2024_0002", "source_type": "news",
                             "date_uncertain": False, **_t("2024-05-10")})

    for t in (AAA, ACC):
        edge(i_org[t], "ownsFacility", i_fac[t], _tm("2019-01-01"))
        if t == AAA:
            edge(i_org[t], "ownsFacility", i_fac_generic, _tm("2019-01-01"))
        edge(i_fac[t], "locatedIn", i_loc[t], _tm("2019-01-01"))
        for year in (2023, 2024):
            k = i_kpi[(t, year)]
            edge(i_org[t], "reportsKPI", k, _tm(f"{year}-01-01", f"{year}-12-31"))
            edge(k, "observedAtFacility", i_fac[t], _tm(f"{year}-01-01", f"{year}-12-31"))
            edge(k, "measuredUnder", i_ind[0], _tm(f"{year}-01-01", f"{year}-12-31"))
        edge(i_org[t], "claims", i_claim[t], _tm("2024-01-01"))
    edge(i_claim[AAA], "alignsWithIndicator", i_ind[0], _tm("2024-01-01"))
    edge(i_claim[ACC], "alignsWithIndicator", i_ind[2], _tm("2024-01-01"))
    edge(i_org[AAA], "setsGoal", i_goal, _tm("2024-01-01"))
    edge(i_goal, "alignsWithIndicator", i_ind[0], _tm("2024-01-01"))
    edge(i_org[AAA], "generatesEmission", i_emis, _tm("2024-01-01", "2024-12-31"))
    edge(i_emis, "measuredUnder", i_ind[1], _tm("2024-01-01", "2024-12-31"))
    edge(i_ind[0], "partOf", i_reg, _tm("2020-01-01"))
    edge(i_ind[2], "partOf", i_reg, _tm("2020-01-01"))
    edge(i_ind[1], "partOf", i_std, _tm("2016-01-01"))
    edge(i_ind[0], "equivalentTo", i_ind[1], _tm("2020-01-01"))
    edge(i_org[AAA], "adoptsStandard", i_std, _tm("2022-01-01"))
    edge(i_org[AAA], "holdsCertification", i_cert, _tm("2023-01-01"))
    edge(i_org[ACC], "publishesReport", i_media, _tm("2024-05-02"))
    edge(i_media, "mentionsFacility", i_fac[ACC], _tm("2024-05-02"))
    edge(i_org[ACC], "subjectToPenalty", i_pen, _tm("2024-05-10"))
    edge(i_org[AAA], "subjectToPenalty", i_pen_zero, _tm("2024-01-01", "2024-12-31"))
    edge(i_pen, "measuredUnder", i_ind[2], _tm("2024-05-10"))

    return {"nodes": nodes, "edges": edges}


def validate(triples, graph) -> int:
    from esg_kg.core.schema import load_schema_sets, validate_triple

    schema = json.loads((REPO / "config" / "schema.json").read_text(encoding="utf-8"))
    entity_classes, edge_labels, edge_directions = load_schema_sets(schema)

    problems = []
    for i, t in enumerate(triples):
        ok, errs = validate_triple(t, entity_classes, edge_labels, edge_directions)
        if not ok:
            problems.append(f"validated_triples[{i}]: {errs}")

    n = len(graph["nodes"])
    for i, node in enumerate(graph["nodes"]):
        if node["class"] not in entity_classes:
            problems.append(f"resolved node[{i}]: unknown class {node['class']}")
        versions = node.get("temporal_versions") or []
        open_current = [v for v in versions if v.get("is_current") is True]
        if versions and len(open_current) != 1:
            problems.append(
                f"resolved node[{i}]: P4 violation, {len(open_current)} is_current versions")
    for i, e in enumerate(graph["edges"]):
        if not (0 <= e["subject"] < n and 0 <= e["object"] < n):
            problems.append(f"resolved edge[{i}]: index out of range")
            continue
        pred, sc = e["predicate"], graph["nodes"][e["subject"]]["class"]
        tc = graph["nodes"][e["object"]]["class"]
        if pred not in edge_labels:
            problems.append(f"resolved edge[{i}]: unknown predicate {pred}")
        else:
            pairs = edge_directions.get(pred, [])
            if pairs and not any(s == sc and t == tc for s, t in pairs):
                problems.append(f"resolved edge[{i}]: illegal {sc} -{pred}-> {tc}")
        if "temporal_metadata" not in e:
            problems.append(f"resolved edge[{i}]: missing temporal_metadata")

    for p in problems:
        print(f"  INVALID: {p}")
    return len(problems)


def main():
    triples = build_validated_triples()
    graph = build_resolved_graph()

    bad = validate(triples, graph)
    if bad:
        print(f"\n{bad} problem(s) — fixtures NOT written.")
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, payload in (("validated_triples.json", triples),
                          ("resolved_graph.json", graph)):
        path = OUT_DIR / name
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
        print(f"wrote {path.relative_to(REPO)}  ({path.stat().st_size:,} bytes)")

    print(f"\nvalidated triples : {len(triples)}")
    print(f"resolved nodes    : {len(graph['nodes'])}")
    print(f"resolved edges    : {len(graph['edges'])}")
    print("all schema-valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
