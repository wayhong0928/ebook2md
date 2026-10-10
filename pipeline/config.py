import json
import os
import sys
from pathlib import Path

PIPELINE_DIR = Path(__file__).parent
REPO_ROOT = PIPELINE_DIR.parent
# the converter and the slicer live in the ebook2md package at the repo root
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
MANIFEST_PATH = PIPELINE_DIR / "manifest.json"

# === Root paths ===
# Where the library and the Obsidian vault are is personal, so it is not in
# this file: set EBOOK2MD_EBOOKS_ROOT / EBOOK2MD_VAULT_ROOT, or write
# pipeline/local_config.json (gitignored):
#   {"ebooks_root": "D:/Books/Ebooks", "vault_root": "D:/Notes/Ebook"}
# Without either, folders inside the repo are used (books/, vault/).
_LOCAL_CONFIG = PIPELINE_DIR / "local_config.json"
_local = json.loads(_LOCAL_CONFIG.read_text(encoding="utf-8")) if _LOCAL_CONFIG.exists() else {}


def _root(name: str, default: Path) -> Path:
    value = os.environ.get(f"EBOOK2MD_{name.upper()}") or _local.get(name)
    return Path(value) if value else default


EBOOKS_ROOT = _root("ebooks_root", REPO_ROOT / "books")
MARKDOWN_ROOT = EBOOKS_ROOT / "markdown"
VAULT_ROOT = _root("vault_root", REPO_ROOT / "vault")

# === Vault subfolder paths ===
VAULT_INBOX = VAULT_ROOT / "00_Inbox"
VAULT_BOOKS = VAULT_ROOT / "10_Books"
VAULT_CONCEPTS = VAULT_ROOT / "20_Concepts"
VAULT_MOC = VAULT_ROOT / "30_MOC"
VAULT_REFLECTIONS = VAULT_ROOT / "40_Reflections"
VAULT_TEMPLATES = VAULT_ROOT / "90_Templates"

# === Ebooks staging area for unconverted books ===
MARKDOWN_STAGING = MARKDOWN_ROOT / "待分類"

# === Classification categories ===
VALID_CATEGORIES = [
    "人物傳記", "個人成長", "商業管理", "工作技能",
    "心理學", "思考方法", "投資理財", "文學小說",
    "歷史政治", "社會科學", "自然科普", "資訊科技", "運動科學",
    "醫療專業", "生活風格", "尚未歸檔",
]

# === Claude API settings ===
CLAUDE_MODEL = "claude-haiku-4-5-20251001"
CLASSIFY_MAX_CHARS = 3000
CLASSIFY_CONFIDENCE_THRESHOLD = 0.7

# === Series/author subfolder threshold ===
SERIES_SUBFOLDER_THRESHOLD = 5
