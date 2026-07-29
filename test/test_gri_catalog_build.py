#!/usr/bin/env python3
"""`gri/build_gri_catalog.py` — each disclosure belongs to ITS OWN standard.

Two defects, measured on the real corpus before this file existed:

  1. **Provenance collision — 80/136 entries cited the wrong document.** The sector
     standards (GRI 11/12/13/14) and the 2024/25 rewrites (GRI 101/102/103) re-list
     other standards' disclosures. `build_catalog()` walked `sorted(glob(...))` and
     kept the FIRST occurrence, and "gri_101" sorts before "gri_2" — so
     `GRI 2-27` (Compliance with laws and regulations) was recorded as coming from
     "GRI 101_ Biodiversity 2024 - English.pdf", carrying that PDF's sha256 and a
     `versions[0]` of GRI_101_2024.

  2. **Pillar guessed by substring instead of read from the source.** Every source
     JSON carries the real pillar ("E — Environmental", "S — Social", "Universal",
     ...) and the file already defines `PILLAR_MAP` to translate it — but both the
     value and the table were dead code, replaced by `any(k in indicator_key for k
     in ("GRI 3", "GRI 301", ...))`. `GRI 101-1` (Biodiversity) matched neither the
     environmental nor the social list and fell through to "Quản trị".

The two are entangled, which is why they are fixed together: pillar is a property
of the STANDARD, so reading it from the source while the wrong standard is still
attributed just moves the error. Measured, fixing (2) alone would have taken the
live graph from 7 wrong indicator nodes to 14 — the 8 social GRI codes attributed
to GRI 11 (`pillar: "Sector"`) would have become "Môi trường".

Fixtures reproduce the collision exactly: `gri_101` sorts first and lists a
foreign `2-27`; `gri_11` sorts before `gri_404` and lists a foreign `404-1`.

Offline, no network. Run from the repo root:

    python test/test_gri_catalog_build.py
"""

import json
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "gri"))  # gri/ has no __init__.py; it is a flat script dir

import build_gri_catalog as bgc  # noqa: E402


# --------------------------------------------------------------------------- #
# Fixtures — shaped like the real gri/full_gri/json/*.json files.
# --------------------------------------------------------------------------- #
def standard(std_id, pillar, title_en, disclosures, year=2016, pdf=None):
    return {
        "standard_id": std_id,
        "title_en": title_en,
        "pillar": pillar,
        "temporal_validity": {
            "version_id": f"{std_id.replace(' ', '_')}_{year}",
            "version_year": year,
            "effective_date": f"{year + 2}-01-01",
            "status": "Active",
        },
        "provenance": {
            "relative_pdf_path": pdf or f"pdfs/{std_id} - {title_en}.pdf",
            "sha256": f"sha-of-{std_id.replace(' ', '')}",
            "page_count": 40,
        },
        "disclosures": [
            {"disclosure_id": d, "title_en": f"Title of {d}", "title_vi": f"Tiêu đề {d}",
             "requirements": [{"requirement_type": "Quantitative", "unit_of_measure": ["tấn"]}]}
            for d in disclosures
        ],
    }


def crosswalk_doc():
    return {"confirmed": [{"tt96": "TT96-6.1.1", "gri": ["GRI 305-1"], "status": "confirmed"}],
            "needs_review": []}


class Workspace:
    """Temp json_dir + crosswalk + out path, mirroring test_indicator_axis.py."""

    def __init__(self, standards=None):
        self.dir = Path(tempfile.mkdtemp(prefix="esgkg_gri_"))
        self.json_dir = self.dir / "json"
        self.json_dir.mkdir()
        self.crosswalk_path = self.dir / "crosswalk.json"
        self.out_path = self.dir / "gri_catalog.json"
        self._write(self.crosswalk_path, crosswalk_doc())
        for fname, doc in (standards if standards is not None else default_standards()).items():
            self._write(self.json_dir / fname, doc)

    @staticmethod
    def _write(path, obj):
        path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")

    def build(self):
        bgc.build_catalog(json_dir=self.json_dir, crosswalk_path=self.crosswalk_path,
                          out_path=self.out_path)
        return json.loads(self.out_path.read_text(encoding="utf-8"))

    def close(self):
        shutil.rmtree(self.dir, ignore_errors=True)


def default_standards():
    """Filenames chosen so sorted() puts the WRONG claimant first, as in the real dir.

    sorted() -> gri_101_2024, gri_11_2021, gri_2_2021, gri_404_2016
    so `GRI 101` sees `2-27` first and `GRI 11` sees `404-1` first.
    """
    return {
        "gri_101_2024.json": standard("GRI 101", "E — Environmental", "Biodiversity 2024",
                                      ["101-1", "2-27"], year=2024),
        "gri_11_2021.json": standard("GRI 11", "Sector", "Oil and Gas Sector 2021",
                                     ["404-1", "2-27"], year=2021),
        "gri_2_2021.json": standard("GRI 2", "Universal", "General Disclosures 2021",
                                    ["2-1", "2-27"], year=2021),
        "gri_404_2016.json": standard("GRI 404", "S — Social", "Training and Education 2016",
                                      ["404-1", "404-2"], year=2016),
    }


# --------------------------------------------------------------------------- #
# 1. Attribution
# --------------------------------------------------------------------------- #
def test_standard_of_picks_the_owning_standard():
    known = {"GRI 2", "GRI 101", "GRI 404", "GRI 305", "GRI 3"}
    assert bgc.standard_of("GRI 2-27", known) == "GRI 2"
    assert bgc.standard_of("GRI 404-1", known) == "GRI 404"
    assert bgc.standard_of("GRI 101-1", known) == "GRI 101"
    assert bgc.standard_of("GRI 3-3", known) == "GRI 3"
    assert bgc.standard_of("GRI 305-1", known) == "GRI 305"
    assert bgc.standard_of("GRI 999-1", known) is None, "an unknown standard must not be invented"


def test_a_disclosure_is_attributed_to_its_own_standard():
    """The headline bug: GRI 2-27 belongs to GRI 2, not to whichever file sorts first."""
    ws = Workspace()
    try:
        cat = ws.build()
        assert cat["GRI 2-27"]["gri_standard"] == "GRI 2", (
            f"GRI 2-27 attributed to {cat['GRI 2-27']['gri_standard']!r}")
        assert cat["GRI 404-1"]["gri_standard"] == "GRI 404"
        assert cat["GRI 101-1"]["gri_standard"] == "GRI 101"
    finally:
        ws.close()


def test_provenance_fields_match_the_attributed_standard():
    """source_pdf / sha256 / versions must describe the SAME document as gri_standard."""
    ws = Workspace()
    try:
        cat = ws.build()
        e = cat["GRI 2-27"]
        assert e["standard_title_en"] == "General Disclosures 2021", e["standard_title_en"]
        assert "GRI 2" in e["source_pdf"] and "Biodiversity" not in e["source_pdf"], e["source_pdf"]
        assert e["sha256"] == "sha-of-GRI2", e["sha256"]
        years = [v["version_year"] for v in e["versions"]]
        assert years == [2021], f"versions must be GRI 2's own, got {years}"
    finally:
        ws.close()


def test_a_disclosure_whose_standard_is_absent_is_still_kept():
    """Fallback, not data loss: if no file owns the code, the first sighting stands."""
    stds = default_standards()
    stds["gri_11_2021.json"]["disclosures"].append(
        {"disclosure_id": "999-1", "title_en": "Orphan", "title_vi": "Mồ côi", "requirements": []})
    ws = Workspace(standards=stds)
    try:
        cat = ws.build()
        assert "GRI 999-1" in cat, "an orphan disclosure must not be dropped"
        assert cat["GRI 999-1"]["gri_standard"] == "GRI 11"
    finally:
        ws.close()


def test_multiple_versions_of_one_standard_are_merged():
    """GRI 306 really does ship as 2016 and 2020 — both versions belong on the entry."""
    stds = {
        "gri_306_2016.json": standard("GRI 306", "E — Environmental", "Effluents and Waste 2016",
                                      ["306-4"], year=2016),
        "gri_306_2020.json": standard("GRI 306", "E — Environmental", "Waste 2020",
                                      ["306-4"], year=2020),
    }
    ws = Workspace(standards=stds)
    try:
        cat = ws.build()
        years = sorted(v["version_year"] for v in cat["GRI 306-4"]["versions"])
        assert years == [2016, 2020], f"expected both versions, got {years}"
        assert cat["GRI 306-4"]["pillar"] == "Môi trường"
    finally:
        ws.close()


# --------------------------------------------------------------------------- #
# 2. Pillar
# --------------------------------------------------------------------------- #
def test_pillar_comes_from_the_source_not_a_substring_guess():
    """GRI 101 is Biodiversity — Environmental. The substring chain said Quản trị."""
    ws = Workspace()
    try:
        cat = ws.build()
        assert cat["GRI 101-1"]["pillar"] == "Môi trường", cat["GRI 101-1"]["pillar"]
        assert cat["GRI 2-1"]["pillar"] == "Quản trị", "Universal maps to Quản trị"
    finally:
        ws.close()


def test_social_disclosures_are_not_swallowed_by_sector_files():
    """The 14-node regression this ordering prevents: GRI 404-1 is Social, and the
    sector file that also lists it is `pillar: "Sector"`."""
    ws = Workspace()
    try:
        cat = ws.build()
        assert cat["GRI 404-1"]["pillar"] == "Xã hội", (
            f"GRI 404-1 got {cat['GRI 404-1']['pillar']!r} — the GRI 11 'Sector' pillar leaked in")
        assert cat["GRI 404-2"]["pillar"] == "Xã hội"
    finally:
        ws.close()


def test_every_pillar_is_one_of_the_three_labels():
    ws = Workspace()
    try:
        cat = ws.build()
        allowed = {"Môi trường", "Xã hội", "Quản trị"}
        bad = {k: v.get("pillar") for k, v in cat.items() if v.get("pillar") not in allowed}
        assert not bad, f"entries with an unusable pillar: {bad}"
    finally:
        ws.close()


# --------------------------------------------------------------------------- #
# 3. Injectability — the test above cannot exist without it
# --------------------------------------------------------------------------- #
def test_build_writes_only_to_the_given_out_path():
    """build_catalog() used to write the real config/gri_catalog.json unconditionally,
    which is why it had no tests. Paths must be injectable."""
    real = REPO / "config" / "gri_catalog.json"
    before = real.read_bytes() if real.exists() else None
    ws = Workspace()
    try:
        ws.build()
        assert ws.out_path.exists(), "nothing written to the requested path"
        after = real.read_bytes() if real.exists() else None
        assert after == before, "build_catalog() wrote to the REAL config/gri_catalog.json"
    finally:
        ws.close()


def test_defaults_still_point_at_the_real_files():
    """The CLI form must keep working unchanged."""
    import inspect
    sig = inspect.signature(bgc.build_catalog)
    assert Path(sig.parameters["json_dir"].default) == Path(bgc.JSON_DIR)
    assert Path(sig.parameters["out_path"].default) == Path(bgc.OUTPUT_CATALOG_PATH)
    assert Path(sig.parameters["crosswalk_path"].default) == Path(bgc.CROSSWALK_PATH)


def main():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL {t.__name__}\n     {exc}")
        except Exception as exc:  # noqa: BLE001 - a broken test is a failure too
            failed += 1
            print(f"ERROR {t.__name__}\n     {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} test(s) passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
