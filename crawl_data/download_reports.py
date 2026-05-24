"""
Tai bao cao thuong nien tu sheet "Xây dựng - VLXD - BĐS".

Su dung:
    python crawl_data/download_reports.py <duong_dan_excel>

Cau truc thu muc dau ra (mac dinh: <repo>/data/annual_report):
    Xây dựng - VLXD - BĐS/
        {Ma CK} - {Ten cong ty}/
            {Ma CK}_{Nam}.{ext}        # file thuong (pdf,...)
            {Ma CK}_{Nam}/             # folder neu nguon la archive (.zip/.rar/.7z)

- Luon tu dong giai nen archive va xoa file nen goc -> dau ra khong con file archive.
- 5 luong song song
- Tu dong bo qua file da tai (cho phep resume)
- Retry 3 lan voi backoff
- Ghi log loi vao download_log.csv canh thu muc dau ra
"""

import argparse
import pandas as pd
import requests
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse
import re
import time
import threading
import sys

# Import logic giai nen tu extract_archives.py (cung thu muc)
sys.path.insert(0, str(Path(__file__).parent))
from extract_archives import EXTRACTORS, ARCHIVE_EXTS, dest_dir, already_extracted

# ---------------- Cau hinh mac dinh ----------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT_ROOT = PROJECT_ROOT / "data" / "annual_report"
TARGET_SHEET = "Xây dựng - VLXD - BĐS"

MAX_WORKERS = 5
TIMEOUT = 90
MAX_RETRIES = 3
RETRY_BACKOFF = 2  # giay, x attempt

# Luon tu dong giai nen .zip/.rar/.7z va xoa file goc -> dau ra khong con archive.
AUTO_EXTRACT = True
DELETE_ARCHIVE_AFTER_EXTRACT = True

# Runtime config (gan trong main() tu CLI)
EXCEL_PATH: Path = Path()
OUT_ROOT: Path = DEFAULT_OUT_ROOT
LOG_PATH: Path = DEFAULT_OUT_ROOT / "download_log.csv"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}

# Windows: cam < > : " / \ | ? * va ky tu dieu khien
_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize(name: str, max_len: int = 120) -> str:
    name = str(name).strip()
    name = _ILLEGAL.sub("_", name)
    name = re.sub(r"\s+", " ", name).rstrip(". ")
    if len(name) > max_len:
        name = name[:max_len].rstrip(". ")
    return name or "unnamed"


def extract_ext(url: str) -> str:
    path = urlparse(url).path.lower()
    m = re.search(r"\.([a-z0-9]{1,5})$", path)
    return m.group(1) if m else "bin"


def load_all() -> pd.DataFrame:
    xl = pd.ExcelFile(EXCEL_PATH)
    if TARGET_SHEET not in xl.sheet_names:
        raise ValueError(
            f"Khong tim thay sheet '{TARGET_SHEET}'. Sheet co trong file: {xl.sheet_names}"
        )
    df = pd.read_excel(EXCEL_PATH, sheet_name=TARGET_SHEET, header=0)
    if df.shape[1] < 5:
        raise ValueError(f"Sheet '{TARGET_SHEET}' khong du 5 cot.")
    df = df.iloc[:, :5]
    df.columns = ["ma_ck", "ten_cty", "ten_tl", "nam", "url"]
    df["ma_ck"] = df["ma_ck"].ffill()
    df["ten_cty"] = df["ten_cty"].ffill()
    df["ten_tl"] = df["ten_tl"].ffill()
    df["sheet"] = TARGET_SHEET
    all_df = df.dropna(subset=["url", "ma_ck"]).copy()
    all_df["url"] = all_df["url"].astype(str).str.strip()
    all_df = all_df[all_df["url"].str.startswith(("http://", "https://"))]
    # Year: NaN -> 'NA', else int
    def fmt_year(y):
        if pd.isna(y):
            return "NA"
        try:
            return str(int(y))
        except (ValueError, TypeError):
            return sanitize(str(y), 10)
    all_df["nam"] = all_df["nam"].apply(fmt_year)
    return all_df.reset_index(drop=True)


def compute_target(row) -> Path:
    sheet_dir = OUT_ROOT / sanitize(row["sheet"])
    company_label = f"{row['ma_ck']} - {row['ten_cty']}" if pd.notna(row["ten_cty"]) else str(row["ma_ck"])
    company_dir = sheet_dir / sanitize(company_label)
    ext = extract_ext(row["url"])
    filename = sanitize(f"{row['ma_ck']}_{row['nam']}", 60) + f".{ext}"
    return company_dir / filename


_lock = threading.Lock()
_counters = {"done": 0, "skipped": 0, "failed": 0, "extracted": 0, "extract_fail": 0}


def _log(msg: str):
    with _lock:
        print(msg, flush=True)


def maybe_extract(archive: Path) -> tuple[bool, str | None]:
    """Neu file la archive, giai nen + xoa file goc. Tra ve (success, err)."""
    if not AUTO_EXTRACT:
        return True, None
    ext = archive.suffix.lower()
    if ext not in ARCHIVE_EXTS:
        return True, None
    dest = dest_dir(archive)
    if already_extracted(dest):
        # Da co folder giai nen tu truoc -> chi xoa archive
        if DELETE_ARCHIVE_AFTER_EXTRACT and archive.exists():
            try:
                archive.unlink()
            except OSError as e:
                return False, f"unlink failed: {e}"
        return True, None
    try:
        EXTRACTORS[ext](archive, dest)
        if DELETE_ARCHIVE_AFTER_EXTRACT:
            archive.unlink(missing_ok=True)
        with _lock:
            _counters["extracted"] += 1
        return True, None
    except Exception as e:
        with _lock:
            _counters["extract_fail"] += 1
        return False, f"{type(e).__name__}: {e}"


def download_one(idx: int, row: dict, target: Path):
    # Neu file da tai roi (con archive hoac da giai nen) -> bo qua
    if target.exists() and target.stat().st_size > 0:
        with _lock:
            _counters["skipped"] += 1
        maybe_extract(target)  # truong hop archive cu chua giai nen
        return ("skipped", idx, row, target, None)
    if target.suffix.lower() in ARCHIVE_EXTS and already_extracted(dest_dir(target)):
        # Folder giai nen da ton tai (archive da bi xoa truoc do)
        with _lock:
            _counters["skipped"] += 1
        return ("skipped", idx, row, target, None)

    target.parent.mkdir(parents=True, exist_ok=True)
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with requests.get(
                row["url"], headers=HEADERS, timeout=TIMEOUT, stream=True, allow_redirects=True
            ) as r:
                r.raise_for_status()
                tmp = target.with_suffix(target.suffix + ".part")
                size = 0
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(chunk_size=64 * 1024):
                        if chunk:
                            f.write(chunk)
                            size += len(chunk)
                if size == 0:
                    tmp.unlink(missing_ok=True)
                    raise IOError("Empty response body")
                tmp.replace(target)
            with _lock:
                _counters["done"] += 1
            ok, ex_err = maybe_extract(target)
            if not ok:
                _log(f"  [EXTRACT-FAIL] {target.name}: {ex_err}")
            return ("ok", idx, row, target, None)
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF * attempt)
    with _lock:
        _counters["failed"] += 1
    return ("failed", idx, row, target, last_err)


def parse_args():
    p = argparse.ArgumentParser(
        description="Tai bao cao thuong nien tu file Excel. Tu dong giai nen archive."
    )
    p.add_argument(
        "excel",
        type=Path,
        help="Duong dan toi file Excel chua danh sach URL (cot: Ma CK, Ten cty, Ten TL, Nam, URL).",
    )
    p.add_argument(
        "-o", "--out",
        type=Path,
        default=DEFAULT_OUT_ROOT,
        help=f"Thu muc dau ra (mac dinh: {DEFAULT_OUT_ROOT}).",
    )
    p.add_argument(
        "--log",
        type=Path,
        default=None,
        help="Duong dan file log loi (mac dinh: <out>/download_log.csv).",
    )
    return p.parse_args()


def main():
    global EXCEL_PATH, OUT_ROOT, LOG_PATH
    args = parse_args()

    EXCEL_PATH = args.excel.expanduser().resolve()
    if not EXCEL_PATH.is_file():
        sys.exit(f"Khong tim thay file Excel: {EXCEL_PATH}")
    OUT_ROOT = args.out.expanduser().resolve()
    LOG_PATH = args.log.expanduser().resolve() if args.log else OUT_ROOT / "download_log.csv"

    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    _log(f"Excel:  {EXCEL_PATH}")
    _log(f"Sheet:  {TARGET_SHEET}")
    _log(f"Output: {OUT_ROOT}")

    df = load_all()
    _log(f"Tong so URL hop le: {len(df)}")

    # Dedupe duong dan dich (cung Ma CK + Nam co the co nhieu URL)
    targets = []
    seen = {}
    for _, row in df.iterrows():
        base = compute_target(row)
        key = str(base).lower()
        if key in seen:
            seen[key] += 1
            base = base.with_name(f"{base.stem}_v{seen[key]}{base.suffix}")
        else:
            seen[key] = 1
        targets.append(base)
    df["target"] = targets

    total = len(df)
    failures = []
    start = time.time()

    rows_as_dicts = df.to_dict("records")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {
            ex.submit(download_one, i, r, r["target"]): i
            for i, r in enumerate(rows_as_dicts)
        }
        for n, fut in enumerate(as_completed(futures), 1):
            status, idx, row, target, err = fut.result()
            if status == "failed":
                failures.append({
                    "sheet": row["sheet"],
                    "ma_ck": row["ma_ck"],
                    "ten_cty": row["ten_cty"],
                    "nam": row["nam"],
                    "url": row["url"],
                    "target": str(target),
                    "error": err,
                })
            if n % 25 == 0 or n == total:
                elapsed = time.time() - start
                rate = n / elapsed if elapsed > 0 else 0
                eta = (total - n) / rate if rate > 0 else 0
                _log(
                    f"[{n}/{total}] ok={_counters['done']} "
                    f"skip={_counters['skipped']} fail={_counters['failed']} "
                    f"extract={_counters['extracted']} xf={_counters['extract_fail']} "
                    f"| {rate:.1f} file/s | ETA ~{eta/60:.1f} phut"
                )

    if failures:
        pd.DataFrame(failures).to_csv(LOG_PATH, index=False, encoding="utf-8-sig")
        _log(f"\nDa ghi {len(failures)} link loi vao: {LOG_PATH}")
    else:
        _log("\nKhong co loi.")

    _log(
        f"\nHOAN TAT - Tai moi: {_counters['done']} | "
        f"Bo qua (da co): {_counters['skipped']} | "
        f"Loi tai: {_counters['failed']} | "
        f"Giai nen: {_counters['extracted']} | "
        f"Loi giai nen: {_counters['extract_fail']} | "
        f"Tong thoi gian: {(time.time()-start)/60:.1f} phut"
    )


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
