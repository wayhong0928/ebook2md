"""Library-wide numbers, so a change that makes real books worse is caught.

    python scripts/baseline.py measure RUN.json [--md-dir DIR] [--jobs N]
    python scripts/baseline.py check RUN.json
    python scripts/baseline.py update RUN.json --reason "..." [--allow KEY ...]

measure converts every book in the pipeline manifest (EPUB if there is one,
else a PDF that has an md) and slices it, without touching the library. With
--md-dir the converted md files are kept there, named by key.

Books are keyed by a hash of their manifest id: the numbers file holds no
titles. It lives in tests/local_baseline/ (gitignored); it describes the
owner's library and is never pushed.

Guards (check fails, update refuses unless the key is passed with --allow):
- body_chars may not drop below the baseline (text lost)
- number_lines may not rise above the baseline (page numbers left in the text)
- a book whose slice self-check passed must still pass
Everything else is reported as a difference only.
"""
import argparse
import contextlib
import datetime
import hashlib
import io
import json
import multiprocessing
import re
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "tests" / "local_baseline" / "baselines.json"
GUARDS = {"body_chars": "min", "number_lines": "max"}


def _paths():
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))


def key_of(book_id):
    return hashlib.sha256(book_id.encode("utf-8")).hexdigest()[:12]


# date and converter lines (with the blank line after them) differ between runs and versions
HEADER = re.compile(r"^# (轉換日期|轉換器)：.*\n(\n)?", re.M)


def md_numbers(md):
    """Numbers of one converted md (header block not counted)."""
    norm = HEADER.sub("", md)
    parts = re.split(r"\n---+\n", md, maxsplit=1)
    body = parts[1] if len(parts) > 1 else md
    lines = body.splitlines()
    return {
        "md_sha": hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16],
        "md_chars": len(md),
        "body_chars": sum(ch.isalnum() for ch in body),
        "sections": len(re.findall(r"^---+$", body, re.M)) + 1,
        "headings": sum(bool(re.match(r"#{1,6} ", l)) for l in lines),
        "number_lines": sum(bool(re.fullmatch(r"\s*\d{1,4}\s*", l)) for l in lines),
    }


def slice_numbers(chapters, report):
    return {
        "slice_chapters": len(chapters),
        "slice_self_check": bool(report.get("self_check")),
        "slice_back_matter": len(report.get("back_matter", [])),
        "slice_oversize_split": sum(report.get("oversize_split", {}).values()),
        "slice_chapter_chars": report.get("chapter_chars", 0),
    }


def measure_one(job):
    """(key, numbers, md text or None). Runs in a worker process."""
    _paths()
    book_id, kind, src, md_dir = job
    key = key_of(book_id)
    out = {"kind": kind}
    sink = io.StringIO()
    try:
        with contextlib.redirect_stdout(sink):
            if kind == "epub":
                from ebook2md import slicing
                from ebook2md.epub import epub2md
                stats = {}
                md, _ = epub2md.generate_markdown_content(src, stats)
                out.update({f"conv_{k}": v for k, v in stats.items()})
                chapters, report = slicing.slice_epub(Path(src))
            else:
                from ebook2md import slicing
                from ebook2md.pdf import pdf2md
                ok, why = pdf2md.text_layer(src)
                if not ok:
                    return key, {"kind": kind, "skipped": why}, None
                with tempfile.TemporaryDirectory() as tmp:
                    path, stats = pdf2md.convert(src, tmp, out_name="x.md")
                    md = path.read_text(encoding="utf-8")
                out.update({f"conv_{k}": v for k, v in stats.items() if k != "chars"})
                chapters, report = slicing.slice_md(md)
        out.update(md_numbers(md))
        out.update(slice_numbers(chapters, report))
        if md_dir:
            (Path(md_dir) / f"{key}.md").write_text(md, encoding="utf-8")
        return key, out, None
    except Exception as e:  # one broken book must not stop the run
        return key, {"kind": kind, "error": f"{type(e).__name__}: {e}"}, None


def jobs_from_manifest(md_dir):
    books = json.loads((ROOT / "pipeline" / "manifest.json").read_text(encoding="utf-8"))["books"]
    jobs = []
    for bid, e in books.items():
        if e.get("epub_path") and Path(e["epub_path"]).exists():
            jobs.append((bid, "epub", e["epub_path"], md_dir))
        elif e.get("pdf_path") and e.get("md_path") and Path(e["pdf_path"]).exists():
            jobs.append((bid, "pdf", e["pdf_path"], md_dir))
    return jobs


def commit():
    import subprocess
    r = subprocess.run(["git", "-C", str(ROOT), "describe", "--tags", "--always", "--dirty"],
                       capture_output=True, text=True)
    return r.stdout.strip()


def cmd_measure(args):
    if args.md_dir:
        Path(args.md_dir).mkdir(parents=True, exist_ok=True)
    jobs = jobs_from_manifest(args.md_dir)
    t0 = time.time()
    books = {}
    with multiprocessing.Pool(args.jobs) as pool:
        for n, (key, nums, _) in enumerate(pool.imap_unordered(measure_one, jobs, chunksize=1), 1):
            books[key] = nums
            if n % 50 == 0:
                print(f"  {n}/{len(jobs)}  {time.time() - t0:.0f}s", flush=True)
    run = {"measured": datetime.datetime.now().isoformat(timespec="seconds"), "code": commit(),
           "books": dict(sorted(books.items()))}
    Path(args.run).parent.mkdir(parents=True, exist_ok=True)
    Path(args.run).write_text(json.dumps(run, ensure_ascii=False, indent=1), encoding="utf-8")
    err = [k for k, v in books.items() if "error" in v]
    skip = [k for k, v in books.items() if "skipped" in v]
    print(f"measured {len(books)} books in {time.time() - t0:.0f}s ({run['code']}); "
          f"errors {len(err)}, skipped (no usable text layer) {len(skip)} -> {args.run}")
    for k in err:
        print("  error", k, books[k]["error"])


def compare(base, run):
    """(violations, differences): lists of (key, metric, old, new)."""
    bad, diff = [], []
    for key, b in base["books"].items():
        r = run["books"].get(key)
        if r is None:
            diff.append((key, "(book)", "present", "missing"))
            continue
        if "error" in r and "error" not in b:
            bad.append((key, "error", "", r["error"]))
            continue
        for m, how in GUARDS.items():
            if m in b and m in r and ((how == "min" and r[m] < b[m]) or (how == "max" and r[m] > b[m])):
                bad.append((key, m, b[m], r[m]))
        if b.get("slice_self_check") and not r.get("slice_self_check"):
            bad.append((key, "slice_self_check", True, r.get("slice_self_check")))
        for m in sorted(set(b) | set(r)):
            if m in GUARDS or m == "slice_self_check":
                continue
            if b.get(m) != r.get(m):
                diff.append((key, m, b.get(m), r.get(m)))
    for key in run["books"].keys() - base["books"].keys():
        diff.append((key, "(book)", "missing", "new"))
    return bad, diff


def load_base():
    if not BASELINE.exists():
        sys.exit(f"no baseline yet: {BASELINE} (run measure, then update)")
    return json.loads(BASELINE.read_text(encoding="utf-8"))


def cmd_check(args):
    base = load_base()
    run = json.loads(Path(args.run).read_text(encoding="utf-8"))
    bad, diff = compare(base, run)
    changed = sorted({k for k, _, _, _ in diff})
    by_metric = {}
    for _, m, _, _ in diff:
        by_metric[m] = by_metric.get(m, 0) + 1
    print(f"baseline {base['code']} vs run {run['code']}: {len(base['books'])} books")
    print(f"  books with any difference: {len(changed)}")
    for m, n in sorted(by_metric.items(), key=lambda x: -x[1]):
        print(f"    {m}: {n}")
    if bad:
        print(f"  GUARD VIOLATIONS: {len(bad)}")
        for v in bad:
            print("   ", *v)
        sys.exit(1)
    print("  guards: ok")


def cmd_update(args):
    run = json.loads(Path(args.run).read_text(encoding="utf-8"))
    if BASELINE.exists():
        base = json.loads(BASELINE.read_text(encoding="utf-8"))
        bad, _ = compare(base, run)
        refused = [v for v in bad if v[0] not in args.allow]
        if refused:
            print("refused: these would loosen a guard (pass the key with --allow if intended):")
            for v in refused:
                print("   ", *v)
            sys.exit(1)
        history = base.get("history", [])
    else:
        history = []
    history.append({"date": run["measured"], "code": run["code"], "reason": args.reason,
                    "allowed": sorted(set(args.allow))})
    out = {"code": run["code"], "measured": run["measured"], "history": history, "books": run["books"]}
    BASELINE.parent.mkdir(parents=True, exist_ok=True)
    BASELINE.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"baseline written: {len(run['books'])} books, code {run['code']}")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("measure")
    m.add_argument("run")
    m.add_argument("--md-dir")
    m.add_argument("--jobs", type=int, default=max(1, multiprocessing.cpu_count() // 2))
    c = sub.add_parser("check")
    c.add_argument("run")
    u = sub.add_parser("update")
    u.add_argument("run")
    u.add_argument("--reason", required=True)
    u.add_argument("--allow", nargs="*", default=[])
    args = ap.parse_args()
    {"measure": cmd_measure, "check": cmd_check, "update": cmd_update}[args.cmd](args)


if __name__ == "__main__":
    main()
