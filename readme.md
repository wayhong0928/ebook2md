# Epub2Markdown-Converter

**專案版本： v1.0**

這是一個專注於高品質輸出的 EPUB 轉 Markdown 工具 (Pure Python Converter)。它不依賴任何外部 AI API，而是透過精心的程式邏輯，將電子書轉換為乾淨、結構化且無雜訊的 Markdown 檔案。

雖然這是一個純轉檔工具，但其輸出的格式經過特別優化，非常適合作為 **Google NotebookLM**、**ChatGPT** 或 **RAG (Retrieval-Augmented Generation)** 系統的高品質輸入素材。

---

## ✨ 核心特色 (Key Features)

1.  **結構精準 (Structure First)**：
    - 嚴格依照 EPUB 的 `Spine` (閱讀順序) 讀取，而非檔案名稱，確保文章順序正確。
    - **TOC 補償機制 (Smart Headers)**：若章節內容缺失標題 (只有 `<p>`)，系統會自動從目錄 (TOC) 抓取對應標題並補上，確保上下文 (Context) 結構完整。

2.  **極致乾淨 (Noise Reduction)**：
    - **智慧清洗**：自動移除 `<script>`, `<style>`, `<nav>`, `<footer>` 以及 XML 宣告等雜訊。
    - **連結優化**：移除所有內部跳轉連結 (Anchor Links) 避免斷鍊，但保留外部參考連結。
    - **圖片處理**：將 `<img>` 轉換為純文字標註 `[圖片說明: Alt Text]`，保留圖像語意並保持版面整潔。

3.  **格式優化 (Format Optimization)**：
    - 保留 Markdown 表格結構。
    - 保留程式碼區塊 (`pre/code`)。
    - 自動壓縮多餘的連續換行。
    - 自動注入書籍 Metadata (書名、作者、轉換日期) 於檔案開頭。

4.  **雙重介面 (Dual Interface)**：
    - 🖥️ **GUI (Web UI)**：基於 Streamlit 的圖形化介面，支援拖曳上傳與即時預覽。
    - ⌨️ **CLI (Command Line)**：適合批次處理或整合至自動化流程。

---

## 🛠️ 技術架構

- **Python 3.10+**
- **EbookLib**: 處理 EPUB 容器與 Spine 解析。
- **BeautifulSoup4**: HTML DOM 清洗與去噪。
- **Markdownify**: HTML 轉 Markdown 核心。
- **Streamlit**: 網頁介面框架。

---

## 🚀 快速開始

### 1. 環境安裝

```bash
# 建立虛擬環境
python -m venv venv

# 啟動虛擬環境 (Windows)
.\venv\Scripts\Activate

# 安裝依賴
pip install -r requirements.txt
```

### 2. 使用網頁介面 (推薦)

啟動後會自動開啟瀏覽器，支援拖曳上傳與一鍵轉換。

```bash
streamlit run src/web_ui.py
```

### 3. 使用命令列 (CLI)

適合進階使用者或批次轉換。

```bash
# 基本用法 (輸出到當前目錄)
python src/epub2md.py "books/bookName.epub"

# 指定輸出目錄
python src/epub2md.py "books/bookName.epub" "output_folder"
```

---

## 📁 專案結構

```text
epub_to_markdown/
├── src/
│   ├── cleaner.py      # HTML 清洗與去噪邏輯
│   ├── converter.py    # Markdown 轉換與格式微調
│   ├── epub2md.py      # CLI 入口與轉換流程控制
│   ├── extractor.py    # EPUB 檔案讀取與 Metadata 提取
│   └── web_ui.py       # Streamlit 網頁介面
├── tests/              # 單元測試與測試樣本生成
├── output/             # 預設輸出目錄
├── docs/               # 系統設計文件
└── requirements.txt    # 專案依賴清單
```

---

## 📚 測試樣本


1.  **Standard Ebooks**：
    - **特色**：極高品質的標準化 HTML/CSS 結構，重新排版過。
    - **用圖**：測試語意結構轉換 (H1/H2 階層) 與 Metadata 提取的精準度。
    - **下載**：[Alice's Adventures in Wonderland](https://standardebooks.org/ebooks/lewis-carroll/alices-adventures-in-wonderland)

2.  **Project Gutenberg**：
    - **特色**：結構較舊且雜亂，包含許多非語意化標籤。
    - **用途**：作為「壓力測試」，驗證清洗雜訊 (Cleaner) 的能力。
    - **下載**：[Frankenstein](https://www.gutenberg.org/ebooks/84)

3.  **WikiSource**：
    - **特色**：中文古籍，多語言編碼。
    - **用途**：測試 UTF-8 中文編碼處理與特殊排版相容性。
    - **下載**：[阿Q正傳 (The True Story of Ah Q)](https://zh.wikisource.org/wiki/%E9%98%BFQ%E6%AD%A3%E5%82%B3)

---

## ⚠️ 免責聲明

本專案僅供技術研究與個人學習使用。使用者在使用本工具轉換檔案時，應自行確認擁有該檔案之合法使用權限。開發者不對任何因使用本工具而產生的版權爭議負責。請支持正版書籍。

This tool is for educational and personal use only. Users are responsible for complying with copyright laws in their jurisdiction. Please support the authors by purchasing original copies.

---

MIT License
