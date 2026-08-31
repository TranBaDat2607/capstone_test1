#!/usr/bin/env python3
"""`crawl_data/extract_archives.py` must be runnable by someone who is not its author.

Why this file exists. The script shipped with four hardcoded absolute paths baked in
as module-level constants::

    ROOT         = Path(r"B:\\capstone\\data2\\data\\Xây dựng - VLXD - BĐS")
    LOG_PATH     = Path(r"B:\\capstone\\data2\\extract_log.csv")
    UNRAR_EXE    = Path(r"C:\\Program Files\\WinRAR\\UnRAR.exe")
    SEVENZIP_EXE = Path(r"C:\\Program Files\\7-Zip\\7z.exe")

and no ``argparse`` at all, so ``main()`` exited on the very first line for every
machine on earth except the one it was written on -- including other Windows
machines, since ``B:`` is a drive letter, not a convention. For a public
repository that is a script nobody can run.

The fix is not "make it Linux-only": ``.rar`` genuinely needs an external binary,
and WinRAR's install path is a legitimate place to look *on Windows*. What the
script must stop doing is treating one machine's layout as the only possibility.
So the Windows paths survive as the LAST tier of a lookup, never as the value.

Four behaviours are pinned:

  1. the corpus root and log path default to something inside this repo and are
     overridable from the CLI -- no foreign drive letter is reachable as a default;
  2. archiver lookup is a three-tier fallback (explicit argument -> ``PATH`` via
     ``shutil.which`` -> platform default install locations), so ``unrar``/``7z``
     installed by a package manager are found on Linux and macOS;
  3. a missing archiver returns ``None`` rather than raising, so the caller can
     emit an actionable message naming what to install instead of a traceback;
  4. the extraction destination is joined with ``os.sep``, not a literal
     backslash, which silently produced ``/path/to/dest\\`` on POSIX.

Offline, no LLM/Neo4j/network/subprocess. Run from the repo root:

    python test/test_extract_archives_portable.py
"""

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

MODULE_PATH = REPO / "crawl_data" / "extract_archives.py"

# Drive-letter prefixes that must never appear as a *default*. Kept as separate
# fragments so this file does not itself trip a future "no absolute paths" grep.
_FOREIGN_ROOT = "B:" + chr(92)


def _module():
    import importlib

    import crawl_data.extract_archives as mod

    return importlib.reload(mod)


# --------------------------------------------------------------------------- #
# 1. Defaults live in the repo, and the CLI can override them.
# --------------------------------------------------------------------------- #

def test_default_root_and_log_are_inside_the_repo():
    mod = _module()
    for name in ("DEFAULT_ROOT", "DEFAULT_LOG_PATH"):
        assert hasattr(mod, name), f"extract_archives must expose {name}"
        value = Path(getattr(mod, name)).resolve()
        assert REPO in value.parents or value == REPO, (
            f"{name}={value} is outside the repo; a default must not point at "
            f"one developer's machine")


def test_no_foreign_drive_letter_survives_as_a_default():
    src = MODULE_PATH.read_text(encoding="utf-8")
    assert _FOREIGN_ROOT not in src, (
        f"a {_FOREIGN_ROOT!r} path is still present; the corpus root must come "
        f"from --root, not from the author's drive")


def test_cli_exposes_root_log_and_workers():
    mod = _module()
    assert hasattr(mod, "build_parser"), "extract_archives must expose build_parser()"
    parser = mod.build_parser()

    args = parser.parse_args([])
    assert Path(args.root) == Path(mod.DEFAULT_ROOT), "--root must default to DEFAULT_ROOT"

    args = parser.parse_args(
        ["--root", "/tmp/corpus", "--log", "/tmp/out.csv", "--workers", "2"]
    )
    assert Path(args.root) == Path("/tmp/corpus")
    assert Path(args.log) == Path("/tmp/out.csv")
    assert args.workers == 2


# --------------------------------------------------------------------------- #
# 2. Archiver lookup is a three-tier fallback, not a fixed path.
# --------------------------------------------------------------------------- #

def test_resolve_archiver_prefers_an_explicit_path(tmp_file=None):
    mod = _module()
    assert hasattr(mod, "resolve_archiver"), "must expose resolve_archiver()"

    explicit = MODULE_PATH  # any file that certainly exists
    got = mod.resolve_archiver("unrar", explicit=explicit, which=lambda _n: "/usr/bin/unrar")
    assert Path(got) == explicit, (
        "an explicitly supplied archiver path must win over PATH lookup")


def test_resolve_archiver_falls_back_to_path_lookup():
    mod = _module()
    got = mod.resolve_archiver("unrar", explicit=None, which=lambda n: f"/usr/bin/{n}")
    assert got is not None and "unrar" in str(got), (
        "an archiver on PATH must be found -- this is what makes the script work "
        "on Linux/macOS where unrar and 7z come from a package manager")


def test_resolve_archiver_returns_none_when_nothing_is_installed():
    mod = _module()
    got = mod.resolve_archiver(
        "unrar", explicit=None, which=lambda _n: None, platform_candidates=()
    )
    assert got is None, (
        "a missing archiver must return None so the caller can name what to "
        "install; raising here produced a bare traceback for the user")


def test_windows_install_paths_are_a_last_tier_not_the_value():
    mod = _module()
    assert hasattr(mod, "PLATFORM_ARCHIVER_PATHS"), (
        "the Windows install locations must live in a lookup table, not in a "
        "module-level UNRAR_EXE/SEVENZIP_EXE constant")
    table = mod.PLATFORM_ARCHIVER_PATHS
    assert "unrar" in table and "7z" in table, "both archivers need candidates"
    for key in ("unrar", "7z"):
        assert isinstance(table[key], (list, tuple)), (
            f"{key} candidates must be a sequence so more locations can be added")

    src = MODULE_PATH.read_text(encoding="utf-8")
    for dead in ("UNRAR_EXE = Path(", "SEVENZIP_EXE = Path("):
        assert dead not in src, f"{dead!r} is still a fixed module-level constant"


# --------------------------------------------------------------------------- #
# 3. Path joining is not Windows-only.
# --------------------------------------------------------------------------- #

def test_destination_is_joined_with_os_sep():
    src = MODULE_PATH.read_text(encoding="utf-8")
    literal_backslash_join = 'str(dest) + "' + chr(92) + chr(92) + '"'
    assert literal_backslash_join not in src, (
        "the UnRAR destination was joined with a literal backslash, which yields "
        "'/path/to/dest\\\\' on POSIX; use os.sep")
    assert "os.sep" in src, "expected os.sep to be used for the destination suffix"


def test_process_takes_its_root_as_a_parameter():
    """``process()`` read the module-level ROOT, so --root could not reach it."""
    import inspect

    mod = _module()
    params = list(inspect.signature(mod.process).parameters)
    assert "root" in params, (
        "process() must accept the root explicitly; reading a module global made "
        "the --root flag a no-op for relative-path reporting")


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
