"""
Giai nen toan bo file .zip / .rar / .7z trong mot thu muc.

Moi archive duoc giai vao folder cung ten (bo extension), cung cap thu muc.
Vi du:  AAA_2025.zip  ->  AAA_2025/
        AAA_2024.rar  ->  AAA_2024/

- Giu nguyen file nen goc
- Bo qua neu folder dich da ton tai va co noi dung
- Ghi log loi vao --log

Su dung:
    python crawl_data/extract_archives.py                      # mac dinh: <repo>/data/raw/annual_report
    python crawl_data/extract_archives.py --root /path/to/corpus --workers 8
    python crawl_data/extract_archives.py --unrar /usr/bin/unrar --7z /usr/bin/7z

.rar va .7z can binary ngoai (unrar / 7z). Thu tu tim: --unrar/--7z ->
bien moi truong UNRAR_EXE/SEVENZIP_EXE -> PATH -> duong dan cai dat mac dinh
theo he dieu hanh. Xem test/test_extract_archives_portable.py.
"""

import argparse
import os
import shutil
import subprocess
import sys
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_ROOT = REPO_ROOT / "data" / "raw" / "annual_report"
DEFAULT_LOG_PATH = REPO_ROOT / "data" / "raw" / "extract_log.csv"
DEFAULT_MAX_WORKERS = 4

ARCHIVE_EXTS = {".zip", ".rar", ".7z"}

ARCHIVER_BINARIES = {
    "unrar": ("unrar", "unrar-free"),
    "7z": ("7z", "7za", "7zz", "7zr"),
}

PLATFORM_ARCHIVER_PATHS = {
    "unrar": (
        r"C:\Program Files\WinRAR\UnRAR.exe",
        r"C:\Program Files (x86)\WinRAR\UnRAR.exe",
        "/usr/bin/unrar",
        "/usr/local/bin/unrar",
        "/opt/homebrew/bin/unrar",
    ),
    "7z": (
        r"C:\Program Files\7-Zip\7z.exe",
        r"C:\Program Files (x86)\7-Zip\7z.exe",
        "/usr/bin/7z",
        "/usr/local/bin/7z",
        "/opt/homebrew/bin/7z",
    ),
}

ARCHIVER_ENV_VARS = {"unrar": "UNRAR_EXE", "7z": "SEVENZIP_EXE"}


_lock = threading.Lock()
_counters = {"ok": 0, "skipped": 0, "failed": 0}


def _log(msg: str):
    with _lock:
        print(msg, flush=True)


def resolve_archiver(kind, explicit=None, which=shutil.which, platform_candidates=None):
    """Tim binary giai nen cho ``kind`` ("unrar" hoac "7z").

    Thu tu: ``explicit`` -> bien moi truong -> PATH -> ``platform_candidates``.
    Tra ve ``Path`` neu tim thay, ``None`` neu khong -- de caller in ra thong
    bao huong dan cai dat thay vi nem traceback.
    """
    if explicit:
        candidate = Path(explicit)
        if candidate.exists():
            return candidate
        return None

    env_value = os.environ.get(ARCHIVER_ENV_VARS.get(kind, ""), "")
    if env_value and Path(env_value).exists():
        return Path(env_value)

    for binary in ARCHIVER_BINARIES.get(kind, ()):
        found = which(binary)
        if found:
            return Path(found)

    if platform_candidates is None:
        platform_candidates = PLATFORM_ARCHIVER_PATHS.get(kind, ())
    for candidate in platform_candidates:
        if Path(candidate).exists():
            return Path(candidate)

    return None


def _missing_archiver_message(kind: str) -> str:
    how = {
        "unrar": "cai WinRAR (Windows) hoac `apt install unrar` / `brew install unrar`",
        "7z": "cai 7-Zip (Windows) hoac `apt install p7zip-full` / `brew install p7zip`",
    }[kind]
    return (
        f"Khong tim thay {kind}. Hay {how}, "
        f"hoac chi dinh bang --{'unrar' if kind == 'unrar' else '7z'} /duong/dan/toi/binary "
        f"(hoac bien moi truong {ARCHIVER_ENV_VARS[kind]})."
    )


def dest_dir(archive: Path) -> Path:
    return archive.with_suffix("")


def already_extracted(d: Path) -> bool:
    if not d.exists():
        return False
    try:
        return any(d.iterdir())
    except OSError:
        return False


def extract_zip(archive: Path, dest: Path, _exe=None):
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            name = info.filename
            if not (info.flag_bits & 0x800):
                try:
                    name = name.encode("cp437").decode("utf-8")
                except (UnicodeDecodeError, UnicodeEncodeError):
                    try:
                        name = name.encode("cp437").decode("cp1258")
                    except (UnicodeDecodeError, UnicodeEncodeError):
                        pass
            target = dest / name
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as out:
                while True:
                    chunk = src.read(64 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)


def extract_rar(archive: Path, dest: Path, unrar_exe=None):
    if not unrar_exe:
        raise FileNotFoundError(_missing_archiver_message("unrar"))
    dest.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [str(unrar_exe), "x", "-o+", "-y", str(archive), str(dest) + os.sep],
        capture_output=True,
        timeout=600,
    )
    if result.returncode != 0:
        err = (result.stderr or result.stdout or b"").decode("utf-8", errors="replace")
        raise RuntimeError(f"UnRAR exit code {result.returncode}: {err[:300]}")


def extract_7z(archive: Path, dest: Path, sevenzip_exe=None):
    if not sevenzip_exe:
        raise FileNotFoundError(_missing_archiver_message("7z"))
    dest.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [str(sevenzip_exe), "x", "-y", f"-o{dest}", str(archive)],
        capture_output=True,
        timeout=600,
    )
    if result.returncode != 0:
        err = (result.stderr or result.stdout or b"").decode("utf-8", errors="replace")
        raise RuntimeError(f"7z exit code {result.returncode}: {err[:300]}")


EXTRACTORS = {".zip": extract_zip, ".rar": extract_rar, ".7z": extract_7z}


def process(archive: Path, root: Path, archivers=None):
    """Giai nen mot archive. ``root`` chi dung de bao cao duong dan tuong doi."""
    archivers = archivers or {}
    dest = dest_dir(archive)
    if already_extracted(dest):
        with _lock:
            _counters["skipped"] += 1
        return ("skipped", archive, dest, None)
    try:
        ext = archive.suffix.lower()
        exe = {".rar": archivers.get("unrar"), ".7z": archivers.get("7z")}.get(ext)
        EXTRACTORS[ext](archive, dest, exe)
        with _lock:
            _counters["ok"] += 1
        return ("ok", archive, dest, None)
    except Exception as e:
        try:
            if dest.exists() and not any(dest.iterdir()):
                dest.rmdir()
        except OSError:
            pass
        with _lock:
            _counters["failed"] += 1
        return ("failed", archive, dest, f"{type(e).__name__}: {e}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Giai nen .zip/.rar/.7z trong mot thu muc (de quy).",
    )
    p.add_argument("--root", type=Path, default=DEFAULT_ROOT,
                   help=f"Thu muc chua archive (mac dinh: {DEFAULT_ROOT})")
    p.add_argument("--log", type=Path, default=DEFAULT_LOG_PATH,
                   help=f"Duong dan file CSV ghi loi (mac dinh: {DEFAULT_LOG_PATH})")
    p.add_argument("--workers", type=int, default=DEFAULT_MAX_WORKERS,
                   help=f"So luong thread (mac dinh: {DEFAULT_MAX_WORKERS})")
    p.add_argument("--unrar", type=Path, default=None,
                   help="Duong dan toi binary unrar (mac dinh: tu dong tim)")
    p.add_argument("--7z", dest="sevenzip", type=Path, default=None,
                   help="Duong dan toi binary 7z (mac dinh: tu dong tim)")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    root = Path(args.root)

    if not root.exists():
        sys.exit(
            f"Khong tim thay thu muc: {root}\n"
            f"Dung --root de chi dinh thu muc chua archive."
        )

    archives = [
        p for p in root.rglob("*")
        if p.is_file() and p.suffix.lower() in ARCHIVE_EXTS
    ]
    archives.sort()
    total = len(archives)
    _log(f"Tim thay {total} archive trong {root}")
    if total == 0:
        return 0

    by_ext = {}
    for a in archives:
        by_ext[a.suffix.lower()] = by_ext.get(a.suffix.lower(), 0) + 1
    _log(f"Phan bo: {by_ext}")

    archivers = {}
    for kind, ext in (("unrar", ".rar"), ("7z", ".7z")):
        if by_ext.get(ext):
            explicit = args.unrar if kind == "unrar" else args.sevenzip
            archivers[kind] = resolve_archiver(kind, explicit=explicit)
            if archivers[kind] is None:
                _log(f"  [WARN] {_missing_archiver_message(kind)}")
            else:
                _log(f"  {kind}: {archivers[kind]}")

    start = time.time()
    failures = []

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        futures = {ex.submit(process, a, root, archivers): a for a in archives}
        for n, fut in enumerate(as_completed(futures), 1):
            status, archive, dest, err = fut.result()
            rel = archive.relative_to(root)
            if status == "failed":
                failures.append({
                    "archive": str(rel),
                    "dest": str(dest),
                    "error": err,
                })
                _log(f"  [FAIL] {rel} -- {err}")
            if n % 10 == 0 or n == total:
                _log(
                    f"[{n}/{total}] ok={_counters['ok']} "
                    f"skip={_counters['skipped']} fail={_counters['failed']}"
                )

    if failures:
        log_path = Path(args.log)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(failures).to_csv(log_path, index=False, encoding="utf-8-sig")
        _log(f"\nDa ghi {len(failures)} loi vao: {log_path}")

    _log(
        f"\nHOAN TAT - Giai nen: {_counters['ok']} | "
        f"Bo qua: {_counters['skipped']} | "
        f"Loi: {_counters['failed']} | "
        f"Thoi gian: {(time.time()-start)/60:.1f} phut"
    )
    return 1 if _counters["failed"] else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
