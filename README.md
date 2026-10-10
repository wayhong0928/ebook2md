# ebook2md

**專案版本： v1.6.0**

把 EPUB 與有文字層的 PDF 電子書轉成 Markdown 的純 Python 工具，不呼叫任何外部 AI API，靠程式邏輯把電子書轉成乾淨、結構化的 Markdown；也能把書切成章節（JSON），給摘要或筆記流程使用。PDF 支援直排中文（見下方「PDF 書」）。

輸出的格式適合作為 **Google NotebookLM**、**ChatGPT** 或 **RAG (Retrieval-Augmented Generation)** 系統的輸入素材。md 的格式寫在 [`docs/output_format.md`](docs/output_format.md)。

---

## ✨ 核心特色 (Key Features)

1. **結構精準 (Structure First)**：
    - 嚴格依照 EPUB 的 `Spine` (閱讀順序) 讀取，而非檔案名稱，確保文章順序正確。
    - **TOC 補償機制 (Smart Headers)**：若章節內容缺失標題 (只有 `<p>`)，系統會自動從目錄 (TOC) 抓取對應標題並補上，確保上下文 (Context) 結構完整。指向檔案內錨點（`chap.xhtml#sec3`）的子章節，也會在錨點位置轉成對應層級的標題。整頁只有圖片的篇章頁、封面（例如以圖片呈現的「第一部」扉頁）也保留其 TOC 標題。錨點落在句子中間時不插標題，避免把一句話切開。

2. **極致乾淨 (Noise Reduction)**：
    - **智慧清洗**：自動移除 `<script>`, `<style>`, `<nav>`, `<footer>` 以及 XML 宣告等雜訊；`<aside>` 裡的註腳保留。
    - **連結優化**：移除所有內部跳轉連結 (Anchor Links) 避免斷鍊，但保留外部參考連結。
    - **圖片處理**：將 `<img>` 轉換為純文字標註 `[圖片說明: Alt Text]`，保留圖像語意並保持版面整潔。

3. **格式優化 (Format Optimization)**：
    - 保留 Markdown 表格結構。
    - 保留程式碼區塊 (`pre/code`)。
    - 自動壓縮多餘的連續換行。
    - 檔案開頭記書名、作者、轉換日期，以及轉出這份 md 的轉換器版本。

4. **可追溯 (Traceable)**：
    - 相依套件版本釘死，同一份程式轉同一本書，除了轉換日期以外逐位元相同。
    - 每份 md 記著是哪一版、哪個 commit 轉出來的，看到檔案就知道要不要重轉。

---

## 🛠️ 技術架構

- **Python 3.10+**
- **EbookLib**: 處理 EPUB 容器與 Spine 解析。
- **BeautifulSoup4**: HTML DOM 清洗與去噪。
- **Markdownify**: HTML 轉 Markdown 核心。
- **PyMuPDF**（PDF 轉檔使用）：PDF 文字與版面座標。注意 PyMuPDF 採 AGPL-3.0／商業雙授權，與本專案的 MIT 授權不同。

---

## 📄 PDF 書

- 有書籤就照書籤分章；沒書籤的橫排書用字級判斷標題。
- 合併排版斷行、跨頁段落；依版面位置與跨頁重複刪掉頁首、頁尾、頁碼（直排書的側邊書眉也算）。
- 支援直排中文，包含每個字各自一行的直排 PDF；橫放的數字、英文、括號放回所在的欄。雙欄頁先讀左欄再讀右欄。
- 掃描檔與字型缺少 Unicode 對照的 PDF 判斷後跳過，不做 OCR。
- 已知限制見下方「已知限制」。

---

## 🚀 快速開始

### 1. 環境安裝

```bash
# 建立虛擬環境
python -m venv venv

# 啟動虛擬環境 (Windows)
.\venv\Scripts\Activate

# 安裝依賴（版本釘死）
pip install -r requirements.txt

# 選用：安裝成指令 ebook2md（不裝也能用 python -m ebook2md）
pip install -e .
```

`requirements.txt` 的版本都釘死，同一份程式才會轉出同一份 md；升級套件前先跑全書庫基準（見下方第 4 節）。每次 push，GitHub Actions 會在 Linux（Python 3.10、3.12）與 Windows（Python 3.11）跑一次版本庫裡的測試。

### 2. 轉檔

```bash
# 依副檔名走 EPUB 或 PDF，可一次給多本（輸出到當前目錄）
python -m ebook2md convert "books/bookName.epub" "books/other.pdf"

# 指定輸出目錄
python -m ebook2md convert "books/bookName.epub" -o "output_folder"

# 指定輸出檔名（只能給一本；預設 EPUB 是「書名_作者.md」、PDF 是「檔名.md」）
python -m ebook2md convert "books/bookName.epub" -o "output_folder" --name "bookName.md"
```

有書轉檔失敗或被跳過時（例如掃描檔），結束碼是 1，其他書照轉。

### 3. 切章節

```bash
# EPUB 依 spine 與 TOC 切；md 依 --- 與標題切。輸出 JSON（預設寫在書旁邊，副檔名 .chapters.json）
python -m ebook2md slice "books/bookName.epub" -o chapters.json
python -m ebook2md slice "output_folder/bookName.md"
```

超過 40,000 字的章依序用 TOC 小節、標題、段落再拆，不丟字；注釋、書目、索引列在 `report.back_matter`，不放進章節。切完會把章節與書末附屬拼回原文比對，不一致就失敗、不寫檔。

> v1.5 以前的入口 `python src/epub2md.py` 在 v1.7 移除，改用 `python -m ebook2md convert`。網頁介面（Streamlit）在 v1.6 移除。

### 4. 執行測試

```bash
python -m pytest tests -q
```

版本庫裡的測試都用合成資料（程式現場產生的小型 EPUB／PDF 或 HTML 片段），不含任何真實書籍內容；拿真書做的測試只留在本機，已列入 `.gitignore`。`tests/test_pdf2md.py` 涵蓋段落合併、跨頁接段、頁首頁碼刪除、書籤標題、直排與掃描檔判斷；`tests/test_slicing_invariants.py` 用隨機產生的書檢查章節切分：正文不遺失、章節順序不變、注釋與書目不進章節、只在段落之間切；`tests/test_cli.py` 檢查命令列、版本行，以及同一本書轉兩次逐位元相同。

全書庫數字基準（本機，需要 `pipeline/` 的書庫設定）：

```bash
python scripts/baseline.py measure run.json      # 轉換並切分書庫裡每一本書，記下數字
python scripts/baseline.py check run.json        # 跟基準比較
python scripts/baseline.py update run.json --reason "..."
```

每本書記正文字數、分節數、標題數、只有數字的行數（殘留頁碼）、刪掉的頁首頁尾數、跨頁接段數、切章數與切片自檢結果。書以雜湊代號記錄，不存書名；基準檔放在 `tests/local_baseline/`，不進版本庫。`check` 在正文字數比基準少、殘留頁碼比基準多、切片自檢由通過變失敗、或原本轉得出來的書這次轉檔出錯時失敗；`update` 不會放寬這些下限與上限，除非用 `--allow` 指名那本書並寫明理由。

---

## ⚠️ 已知限制

PDF 轉檔只求盡力：遇到轉壞而且要用的書，才針對那本修，修完把檢查條目加進本機的頁面事實測試，再跑全書庫基準確認其他書沒被影響。以下問題目前都只記錄、不修。

**PDF**

- 掃描檔與字型缺少 Unicode 對照的 PDF 不轉檔（不做 OCR）。
- 以圖為主的書（食譜、圖解、教材）：圖說、側邊標籤、灰底框的文字可能混進正文，表格不還原、欄序可能錯。
- 沒有書籤的 PDF：橫排書從字級猜標題，只有一層；直排書不猜標題。
- 條列：偶爾在句中斷段；跨頁的清單項目會接成一行；英文步驟或清單裡，同一項換行後沒有接回。
- 英文：行尾剛好斷在複合詞的連字號時，連字號會被吃掉（self-driving 變成 selfdriving）；段落剛好在頁尾句點結束時會被切成兩段。
- 直排：條列只部分分行；跨頁的縮排新段偶爾沒斷開；目錄頁的斜體頁碼順序可能錯；OCR 文字層的英文單字之間沒有空白。
- OCR 文字層：偶有書眉殘留；掉了句號時，相鄰的注釋會接成一段。

**EPUB**

- 約 0.4% 的 TOC 條目指向句子中間的頁碼錨點，這些地方刻意不插標題，md 會少掉這些小節標題（正文不缺）。
- 正文裡的注釋編號直接接在句尾（例如「……的結果。12」），只影響閱讀。
- 少數書每一行都是一個獨立段落，轉出來的段落會很碎。

---

## 📁 專案結構

```text
ebook2md/                  # repo 根目錄
├── ebook2md/              # 套件
│   ├── cli.py             # 命令列：convert、slice
│   ├── slicing.py         # 章節切分
│   ├── epub/
│   │   ├── extractor.py   # EPUB 讀取、Spine 與 TOC
│   │   ├── cleaner.py     # HTML 清洗與去噪、TOC 標題補償
│   │   ├── converter.py   # HTML 轉 Markdown 與格式微調
│   │   └── epub2md.py     # EPUB 轉檔流程
│   └── pdf/
│       └── pdf2md.py      # 有文字層的 PDF 轉 Markdown（PyMuPDF）
├── pipeline/              # 個人書庫的分類、讀書筆記流程（見 pipeline/README.md）
├── scripts/baseline.py    # 全書庫數字基準（本機）
├── tests/                 # 測試（合成資料）
├── docs/                  # 輸出格式與系統設計文件
├── pyproject.toml
└── requirements.txt       # 釘死版本的相依套件
```

---

## 📚 測試樣本

1. **Standard Ebooks**：
    - **特色**：極高品質的標準化 HTML/CSS 結構，重新排版過。
    - **用途**：測試語意結構轉換 (H1/H2 階層) 與 Metadata 提取的精準度。
    - **下載**：[Alice's Adventures in Wonderland](https://standardebooks.org/ebooks/lewis-carroll/alices-adventures-in-wonderland)

2. **Project Gutenberg**：
    - **特色**：結構較舊且雜亂，包含許多非語意化標籤。
    - **用途**：作為「壓力測試」，驗證清洗雜訊 (Cleaner) 的能力。
    - **下載**：[Frankenstein](https://www.gutenberg.org/ebooks/84)

3. **WikiSource**：
    - **特色**：中文古籍，多語言編碼。
    - **用途**：測試 UTF-8 中文編碼處理與特殊排版相容性。
    - **下載**：[阿Q正傳 (The True Story of Ah Q)](https://zh.wikisource.org/wiki/%E9%98%BFQ%E6%AD%A3%E5%82%B3)

---

## ⚠️ 免責聲明

本專案僅供技術研究與個人學習使用。使用者在使用本工具轉換檔案時，應自行確認擁有該檔案之合法使用權限。開發者不對任何因使用本工具而產生的版權爭議負責。請支持正版書籍。

This tool is for educational and personal use only. Users are responsible for complying with copyright laws in their jurisdiction. Please support the authors by purchasing original copies.
