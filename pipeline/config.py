from pathlib import Path

# === Root paths ===
EBOOKS_ROOT = Path(r"D:\wayhong-data\Ebooks")
MARKDOWN_ROOT = EBOOKS_ROOT / "markdown"
VAULT_ROOT = Path(r"D:\github-repo\Obsidian Vault\Ebook")
EPUB2MD_SCRIPT = Path(r"D:\github-repo\epub_to_markdown\src\epub2md.py")
PIPELINE_DIR = Path(__file__).parent
MANIFEST_PATH = PIPELINE_DIR / "manifest.json"

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
SERIES_SUBFOLDER_THRESHOLD = 6
