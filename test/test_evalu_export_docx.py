#!/usr/bin/env python3
"""
Offline unit checks for evalu/export_docx.py — the Markdown -> .docx converter.

Only the PARSING is tested here, not python-docx itself. Parsing is where a
converter goes wrong silently: a mis-detected table turns a results grid into a
wall of pipe characters, and nobody notices until it is in the appendix.

Run from the repo root:

    python test/test_evalu_export_docx.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evalu.export_docx import parse_blocks, split_row, strip_inline  # noqa: E402


def kinds(md):
    return [b["kind"] for b in parse_blocks(md)]


def test_headings_carry_their_level():
    blocks = parse_blocks("# A\n\n## B\n\n### C\n")
    assert [b["kind"] for b in blocks] == ["heading"] * 3
    assert [b["level"] for b in blocks] == [1, 2, 3]
    assert [b["text"] for b in blocks] == ["A", "B", "C"]


def test_table_is_detected_and_separator_row_dropped():
    md = ("| Mã | Giá trị |\n"
          "|---|---:|\n"
          "| M2.2 | 100.00% |\n"
          "| M5.1 | 73.49% |\n")
    (block,) = parse_blocks(md)
    assert block["kind"] == "table"
    assert block["header"] == ["Mã", "Giá trị"]
    assert block["rows"] == [["M2.2", "100.00%"], ["M5.1", "73.49%"]]


def test_table_ends_at_a_blank_line():
    md = "| a | b |\n|---|---|\n| 1 | 2 |\n\nĐoạn văn sau bảng.\n"
    assert kinds(md) == ["table", "para"]


def test_pipe_inside_a_code_fence_is_not_a_table():
    md = "```\n| not | a | table |\n```\n"
    (block,) = parse_blocks(md)
    assert block["kind"] == "code", block


def test_blockquote_and_bullets():
    md = "> Lưu ý quan trọng\n\n- một\n- hai\n"
    assert kinds(md) == ["quote", "bullet", "bullet"]
    blocks = parse_blocks(md)
    assert blocks[0]["text"] == "Lưu ý quan trọng"
    assert blocks[1]["text"] == "một"


def test_split_row_handles_escaped_and_empty_cells():
    assert split_row("| a | b |") == ["a", "b"]
    assert split_row("| a |  | c |") == ["a", "", "c"]
    # a trailing pipe must not produce a phantom empty column
    assert len(split_row("| x | y |")) == 2


def test_strip_inline_removes_markup_but_keeps_text():
    assert strip_inline("**đậm** và `mã`") == ("đậm và mã", [(0, 3)])
    plain, bolds = strip_inline("không có gì")
    assert plain == "không có gì" and bolds == []


def test_strip_inline_reports_bold_spans_in_order():
    plain, bolds = strip_inline("a **b** c **d**")
    assert plain == "a b c d"
    assert [plain[s:e] for s, e in bolds] == ["b", "d"]


def test_horizontal_rule_and_blank_lines_are_dropped():
    assert kinds("A\n\n---\n\nB\n") == ["para", "para"]


def test_multiline_paragraph_is_one_block():
    blocks = parse_blocks("dòng một\ndòng hai\n\ndòng ba\n")
    assert len(blocks) == 2
    assert blocks[0]["text"] == "dòng một dòng hai"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} test group(s) passed.")
