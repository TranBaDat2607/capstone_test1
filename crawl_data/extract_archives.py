"""
Giai nen toan bo file .zip / .rar / .7z trong mot thu muc (mac dinh: BĐS).

Moi archive duoc giai vao folder cung ten (bo extension), cung cap thu muc.
Vi du:  AAA_2025.zip  ->  AAA_2025/
        AAA_2024.rar  ->  AAA_2024/

- Giu nguyen file nen goc
- Bo qua neu folder dich da ton tai va co noi dung
- Ghi log loi vao extract_log.csv
"""

import sys
import subprocess
import zipfile
import threading
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd

# ---------------- Cau hinh ----------------
ROOT = Path(r"B:\capstone\data2\data\Xây dựng - VLXD - BĐS")
LOG_PATH = Path(r"B:\capstone\data2\extract_log.csv")
MAX_WORKERS = 4

UNRAR_EXE = Path(r"C:\Program Files\WinRAR\UnRAR.exe")
SEVENZIP_EXE = Path(r"C:\Program Files\7-Zip\7z.exe")  # fallback cho .7z

ARCHIVE_EXTS = {".zip", ".rar", ".7z"}

# -----------------------------------------

_lock = threading.Lock()
_counters = {"ok": 0, "skipped": 0, "failed": 0}


def _log(msg: str):
    with _lock:
        print(msg, flush=True)


def dest_dir(archive: Path) -> Path:
    return archive.with_suffix("")


def already_extracted(d: Path) -> bool:
    if not d.exists():
        return False
    try:
        return any(d.iterdir())
    except OSError:
        return False


def extract_zip(archive: Path, dest: Path):
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zf:
        # Try to fix Vietnamese filenames encoded as cp437 (common on Windows-zipped files)
        for info in zf.infolist():
            name = info.filename
            if not (info.flag_bits & 0x800):
                # Tieng Viet ZIP cu thuong duoc encode bang cp437, can dich lai sang utf-8
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


def extract_rar(archive: Path, dest: Path):
    if not UNRAR_EXE.exists():
        raise FileNotFoundError(f"Khong tim thay UnRAR.exe tai {UNRAR_EXE}")
    dest.mkdir(parents=True, exist_ok=True)
    # x: extract voi cau truc thu muc, -o+: overwrite, -y: yes to all
    result = subprocess.run(
        [str(UNRAR_EXE), "x", "-o+", "-y", str(archive), str(dest) + "\\"],
        capture_output=True,
        timeout=600,
    )
    if result.returncode != 0:
        err = (result.stderr or result.stdout or b"").decode("utf-8", errors="replace")
        raise RuntimeError(f"UnRAR exit code {result.returncode}: {err[:300]}")


def extract_7z(archive: Path, dest: Path):
    if not SEVENZIP_EXE.exists():
        raise FileNotFoundError(f"Khong tim thay 7z.exe tai {SEVENZIP_EXE}")
    dest.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [str(SEVENZIP_EXE), "x", "-y", f"-o{dest}", str(archive)],
        capture_output=True,
        timeout=600,
    )
    if result.returncode != 0:
        err = (result.stderr or result.stdout or b"").decode("utf-8", errors="replace")
        raise RuntimeError(f"7z exit code {result.returncode}: {err[:300]}")


EXTRACTORS = {".zip": extract_zip, ".rar": extract_rar, ".7z": extract_7z}


def process(archive: Path):
    dest = dest_dir(archive)
    rel = archive.relative_to(ROOT)
    if already_extracted(dest):
        with _lock:
            _counters["skipped"] += 1
        return ("skipped", archive, dest, None)
    try:
        EXTRACTORS[archive.suffix.lower()](archive, dest)
        with _lock:
            _counters["ok"] += 1
        return ("ok", archive, dest, None)
    except Exception as e:
        # Don du gon folder dich neu loi
        try:
            if dest.exists() and not any(dest.iterdir()):
                dest.rmdir()
        except OSError:
            pass
        with _lock:
            _counters["failed"] += 1
        return ("failed", archive, dest, f"{type(e).__name__}: {e}")


def main():
    if not ROOT.exists():
        sys.exit(f"Khong tim thay thu muc: {ROOT}")

    archives = [
        p for p in ROOT.rglob("*")
        if p.is_file() and p.suffix.lower() in ARCHIVE_EXTS
    ]
    archives.sort()
    total = len(archives)
    _log(f"Tim thay {total} archive trong {ROOT}")
    if total == 0:
        return

    by_ext = {}
    for a in archives:
        by_ext[a.suffix.lower()] = by_ext.get(a.suffix.lower(), 0) + 1
    _log(f"Phan bo: {by_ext}")

    start = time.time()
    failures = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(process, a): a for a in archives}
        for n, fut in enumerate(as_completed(futures), 1):
            status, archive, dest, err = fut.result()
            rel = archive.relative_to(ROOT)
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
        pd.DataFrame(failures).to_csv(LOG_PATH, index=False, encoding="utf-8-sig")
        _log(f"\nDa ghi {len(failures)} loi vao: {LOG_PATH}")

    _log(
        f"\nHOAN TAT - Giai nen: {_counters['ok']} | "
        f"Bo qua: {_counters['skipped']} | "
        f"Loi: {_counters['failed']} | "
        f"Thoi gian: {(time.time()-start)/60:.1f} phut"
    )


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
