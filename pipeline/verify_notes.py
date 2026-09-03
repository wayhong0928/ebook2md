"""Ebook 筆記生成 pipeline 的輸出驗證腳本。

只偵測、不修改任何檔案；偵測到的問題交給人／Claude 決定怎麼修。
涵蓋的已知失敗模式（見 Obsidian Vault\\Ebook\\claude-notes\\SPEC_03_知識管理推進.md）：
- 空白 wikilink（[[]]）
- 斷 link（wikilink 指向不存在的檔案）
- CJK / Unicode 編碼損毀
- 內容疑似截斷（長度啟發式，非精確判斷，可能有誤報）
- 概念卡「## 原文」引言與標題完全相同（疑似捏造引言，SPEC_03:35 明講的既有事故模式）

用法：
    python verify_notes.py                # 全庫掃描，人類可讀報告
    python verify_notes.py --json          # 全庫掃描，輸出 JSON
    python verify_notes.py --book 深度工作  # 只掃書名含這個關鍵字的書
"""
import re
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime

# Windows 終端機常見 cp950/big5 codepage 印不出部分中文字元（如「〇」）會直接
# UnicodeEncodeError 崩潰；強制 stdout/stderr 用 UTF-8，不依賴終端機的 codepage。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

VAULT_ROOT = Path(r"D:\github-repo\Obsidian Vault\Ebook")
BOOKS_DIR = VAULT_ROOT / "10_Books"
CONCEPTS_DIR = VAULT_ROOT / "20_Concepts"
MOC_DIR = VAULT_ROOT / "30_MOC"

WIKILINK_RE = re.compile(r"\[\[([^\[\]]*)\]\]")
EMPTY_WIKILINK_RE = re.compile(r"\[\[\s*\]\]")
REPLACEMENT_CHAR = "�"

# 啟發式閾值，不是 pipeline 已知的精確截斷點；跑過一輪後如果誤報多，調這個數字。
TRUNCATION_THRESHOLD = 7500
TERMINAL_PUNCT = ("。", "」", "』", "”", '"', ".", "!", "?", "！", "？", "）", ")", "…", "、")


def find_md_files(root: Path):
    return sorted(root.rglob("*.md")) if root.exists() else []


def line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def check_empty_wikilinks(path: Path, text: str, issues: list):
    for m in EMPTY_WIKILINK_RE.finditer(text):
        issues.append({
            "file": str(path), "line": line_of(text, m.start()),
            "type": "empty_wikilink", "detail": "空白 wikilink [[]]",
        })


def check_broken_links(path: Path, text: str, issues: list, known_targets: set):
    for m in WIKILINK_RE.finditer(text):
        target = m.group(1).strip()
        if not target:
            continue  # 已由 check_empty_wikilinks 涵蓋
        target = target.split("|")[0].strip()
        if target not in known_targets:
            issues.append({
                "file": str(path), "line": line_of(text, m.start()),
                "type": "broken_link", "detail": f"連結目標「{target}」找不到對應檔案",
            })


def check_encoding_corruption(path: Path, text: str, issues: list):
    if REPLACEMENT_CHAR in text:
        idx = text.index(REPLACEMENT_CHAR)
        issues.append({
            "file": str(path), "line": line_of(text, idx),
            "type": "encoding_corruption", "detail": "含 Unicode 替代字元（U+FFFD），疑似編碼損毀",
        })


def check_truncation(path: Path, text: str, issues: list):
    # notes.py 的書籍筆記樣板固定以結構性收尾：每章結尾是空白的「#### 我的想法\n\n\n---」，
    # 全書結尾是「## 全書概念連結」（wikilink清單）→「## MOC 連結建議」（固定樣板）
    # →「## 整體心得」（空白佔位標題）。這些本來就不是散文、不會以句號等終止標點結束，
    # 拿檔案原始結尾判斷截斷幾乎必然誤判。改成檢查「最後一段原文摘錄（> 開頭的引言）」
    # 是否斷在句子中間——引言是直接從書中擷取的文字，正常情況下一定是完整句子收尾。
    quote_lines = re.findall(r"^> (.+)$", text, re.MULTILINE)
    tail = quote_lines[-1].rstrip() if quote_lines else text.rstrip()
    if len(text) >= TRUNCATION_THRESHOLD and tail and not tail.endswith(TERMINAL_PUNCT):
        issues.append({
            "file": str(path), "line": None, "type": "possible_truncation",
            "detail": f"內容長度 {len(text)} 字，結尾不像完整句子，疑似被截斷（啟發式判斷，人工確認）",
        })


def check_concept_quote_equals_title(path: Path, text: str, issues: list):
    title_m = re.search(r'^title:\s*"?([^"\n]+)"?\s*$', text, re.MULTILINE)
    if not title_m:
        return
    title = title_m.group(1).strip()
    quote_m = re.search(r"## 原文\s*\n+((?:^>.*\n?)+)", text, re.MULTILINE)
    if not quote_m:
        issues.append({
            "file": str(path), "line": None, "type": "missing_quote",
            "detail": "找不到「## 原文」區塊",
        })
        return
    quote_lines = [l.lstrip(">").strip() for l in quote_m.group(1).splitlines()]
    quote = " ".join(l for l in quote_lines if l).strip()
    if not quote:
        issues.append({
            "file": str(path), "line": None, "type": "missing_quote",
            "detail": "「## 原文」區塊內容為空",
        })
    elif quote == title:
        issues.append({
            "file": str(path), "line": None, "type": "quote_equals_title",
            "detail": f"原文引言與標題完全相同（「{title}」），疑似捏造引言，SPEC_03:35 記過的事故模式",
        })


def main():
    parser = argparse.ArgumentParser(description="Ebook 筆記生成 pipeline 驗證腳本（只偵測不修改）")
    parser.add_argument("--json", action="store_true", help="輸出 JSON 而非人類可讀報告")
    parser.add_argument("--book", default=None, help="只檢查書名含此關鍵字的書（10_Books 下的檔名）")
    args = parser.parse_args()

    all_book_files = find_md_files(BOOKS_DIR)
    concept_files = find_md_files(CONCEPTS_DIR)
    book_files = all_book_files
    if args.book:
        book_files = [f for f in all_book_files if args.book in f.stem]

    known_targets = {f.stem for f in all_book_files} | {f.stem for f in concept_files}
    known_targets |= {f.stem for f in find_md_files(MOC_DIR)}

    issues = []
    for f in book_files:
        try:
            text = f.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            issues.append({"file": str(f), "line": None, "type": "encoding_corruption",
                            "detail": "檔案無法以 UTF-8 讀取"})
            continue
        check_empty_wikilinks(f, text, issues)
        check_broken_links(f, text, issues, known_targets)
        check_encoding_corruption(f, text, issues)
        check_truncation(f, text, issues)

    for f in concept_files:
        try:
            text = f.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            issues.append({"file": str(f), "line": None, "type": "encoding_corruption",
                            "detail": "檔案無法以 UTF-8 讀取"})
            continue
        check_empty_wikilinks(f, text, issues)
        check_broken_links(f, text, issues, known_targets)
        check_encoding_corruption(f, text, issues)
        check_concept_quote_equals_title(f, text, issues)

    if args.json:
        print(json.dumps({
            "generated_at": datetime.now().isoformat(),
            "book_count": len(book_files), "concept_count": len(concept_files),
            "issue_count": len(issues), "issues": issues,
        }, ensure_ascii=False, indent=2))
    else:
        print(f"掃描 {len(book_files)} 本書筆記、{len(concept_files)} 張概念卡，發現 {len(issues)} 個問題\n")
        by_type = {}
        for i in issues:
            by_type.setdefault(i["type"], []).append(i)
        for t, items in by_type.items():
            print(f"## {t}（{len(items)} 筆）")
            for i in items[:50]:
                loc = f":{i['line']}" if i["line"] else ""
                print(f"  {i['file']}{loc} — {i['detail']}")
            if len(items) > 50:
                print(f"  ...還有 {len(items) - 50} 筆，用 --json 看完整清單")
            print()

    sys.exit(1 if issues else 0)


if __name__ == "__main__":
    main()
