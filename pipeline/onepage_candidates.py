"""一頁版佳句候選池（2026-09-27 定案用方案 B）。

用法：python pipeline/onepage_candidates.py <epub 路徑> [書籍筆記路徑] > <scratchpad>/候選.json
來源三種：
  bold     epub 原檔的 <strong>/<b>，以及 CSS 設成 font-weight:bold 的 class（轉 md 時會消失）
  summary  標題含 小結／重點／摘要／結論／總結／回顧 的段落
  phase2   書籍筆記（notes_generated）各章「重點擷取」的引文
過濾：去掉 12 字以下的片段（單詞強調）、跟章節標題相同的文字、沒有句讀又短於 20 字的（多半是小標題）。
"""
import json, re, sys, zipfile
from html import unescape
from pathlib import Path

SUMMARY_HEAD = re.compile(r"(小結|重點|摘要|結論|總結|回顧|Key ?Takeaways?|Summary)", re.I)
PUNCT = re.compile(r"[，。；：！？、,.;:!?]")


def text_of(fragment: str) -> str:
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", "", fragment))).strip()


def bold_classes(css: str) -> set[str]:
    out = set()
    for sel, body in re.findall(r"([^{}]+)\{([^}]*)\}", css):
        if re.search(r"font-weight\s*:\s*(bold|[6-9]00)", body, re.I):
            out |= set(re.findall(r"\.([\w-]+)", sel))
    return out


def keep(t: str, headings: set[str]) -> bool:
    t = t.strip()
    if len(t) < 12 or t in headings or t.endswith(("，", ",")):
        return False
    # 推薦序的作者介紹「（本文作者為…）」與署名「──某某（頭銜）」
    if (t.startswith(("（", "(")) and t.endswith(("）", ")"))) or t.startswith(("──", "——", "—")):
        return False
    if not PUNCT.search(t) and len(t) < 20:
        return False
    return True


def from_epub(epub: Path) -> list[dict]:
    with zipfile.ZipFile(epub) as z:
        names = sorted(n for n in z.namelist() if n.lower().endswith((".xhtml", ".html", ".htm")))
        pages = {n: z.read(n).decode("utf-8", "ignore") for n in names}
        css = "".join(z.read(n).decode("utf-8", "ignore") for n in z.namelist() if n.lower().endswith(".css"))
    bc = bold_classes(css)
    headings = {
        text_of(h).strip()
        for html in pages.values()
        for h in re.findall(r"<h[1-6]\b[^>]*>(.*?)</h[1-6]\s*>", html, re.S | re.I)
    }
    out, seen = [], set()
    for n, html in pages.items():
        # 內嵌 <style> 也算
        bc_local = bc | bold_classes("".join(re.findall(r"<style[^>]*>(.*?)</style>", html, re.S)))
        spans = re.findall(r"<(?:strong|b)(?:\s[^>]*)?>(.*?)</(?:strong|b)>", html, re.S | re.I)
        if bc_local:
            cls_pat = "|".join(map(re.escape, bc_local))
            spans += re.findall(
                rf'<(span|p|div|em)[^>]*class="[^"]*\b(?:{cls_pat})\b[^"]*"[^>]*>(.*?)</\1>', html, re.S)
            spans = [s[1] if isinstance(s, tuple) else s for s in spans]
        for s in spans:
            t = text_of(s)
            if keep(t, headings) and t not in seen:
                seen.add(t)
                out.append({"source": "bold", "file": n, "text": t})
        # 小結類段落：標題命中後，收該檔接下來的段落（最多 6 段）
        for m in re.finditer(r"<h[1-6]\b[^>]*>(.*?)</h[1-6]\s*>", html, re.S | re.I):
            if SUMMARY_HEAD.search(text_of(m.group(1))):
                rest = html[m.end():]
                nxt = re.search(r"<h[1-6]\b[^>]*>", rest, re.I)
                block = rest[: nxt.start()] if nxt else rest
                for p in re.findall(r"<p[^>]*>(.*?)</p>", block, re.S)[:6]:
                    t = text_of(p)
                    if keep(t, headings) and t not in seen:
                        seen.add(t)
                        out.append({"source": "summary", "file": n, "heading": text_of(m.group(1)), "text": t})
    return out


def from_phase2(note: Path) -> list[dict]:
    t = note.read_text(encoding="utf-8")
    if 'status: "notes_generated"' not in t:
        return []
    out = []
    for chap, body in re.findall(r"^### (.+?)\n(.*?)(?=^### |^## |\Z)", t, re.S | re.M):
        q = re.search(r"#### 重點擷取\n(.*?)(?=\n#### )", body, re.S)
        if q:
            for line in re.findall(r"^> (.+)$", q.group(1), re.M):
                if len(line) >= 12 and not line.rstrip().endswith(("，", ",")):
                    out.append({"source": "phase2", "chapter": chap.strip(), "text": line.strip()})
    return out


def generate_candidates(epub: Path, note: Path | None = None) -> dict:
    cands = from_epub(epub)
    if note is not None:
        cands += from_phase2(note)
    summary = {s: sum(1 for c in cands if c["source"] == s) for s in ("bold", "summary", "phase2")}
    return {"epub": str(epub), "counts": summary, "candidates": cands}


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    epub = Path(sys.argv[1])
    if epub.exists():
        result = generate_candidates(epub, Path(sys.argv[2]) if len(sys.argv) > 2 else None)
    else:
        result = {"epub": str(epub), "counts": {s: 0 for s in ("bold", "summary", "phase2")}, "candidates": []}
    print(json.dumps(result, ensure_ascii=False, indent=1))
