# 技術堆疊與依賴套件說明 (Technical Stack & Dependencies)

本文檔詳細列出 `Epub2NotebookLM-Converter` 專案所使用的關鍵技術與第三方套件，以及選擇它們的原因。

## 核心語言

- **Python 3.10+**: 專案基礎語言。選擇 3.10 以上版本是為了獲得更好的型別提示 (Type Hinting) 支援與效能優化 (如 Match-Case 語法)，並確保依賴套件的相容性。

## 關鍵相依套件 (Key Dependencies)

這些套件定義在 `requirements.txt` 中，是專案運行的基礎。

### 1. EbookLib

- **用途**: EPUB 檔案讀取與解析。
- **版本**: `0.18+`
- **選用原因**:
  - 相比於直接將 `.epub` 當作 ZIP 解壓縮，`EbookLib` 提供了抽象層 (`EpubBook`, `EpubHtml`) 來處理 EPUB 的複雜結構。
  - 最重要的是能正確讀取 **Spine (閱讀順序)**，這是本專案「RAG 優化」的核心需求，確保輸出的順序與書籍邏輯一致，而非依照檔案名稱排序。

### 2. BeautifulSoup4

- **用途**: HTML DOM 解析 (`Parsing`) 與清洗 (`Sanitization`)。
- **版本**: `4.12+`
- **選用原因**:
  - 強大的 DOM 操作能力，允許我們精準定位並刪除雜訊標籤 (如 `<nav>`, `<script>`, `<footer>`)。
  - 容錯率高，能處理格式不嚴謹的 HTML/XHTML 內容。

### 3. Markdownify

- **用途**: 將清洗後的 HTML 轉換為 Markdown 格式。
- **版本**: `0.11+`
- **選用原因**:
  - 高度可客製化。本專案繼承了其 `MarkdownConverter` 類別，重寫了 `convert_a` 等方法，以實現「移除內部連結但保留文字」的特殊需求。
  - 支援表格 (`<table>`) 到 Markdown Table 的轉換。

### 4. Streamlit

- **用途**: 網頁使用者介面 (Web UI)。
- **版本**: Latest included
- **選用原因**:
  - **快速開發**: 允許使用純 Python 語法構建互動式網頁，無需撰寫 HTML/CSS/JS。
  - **內建元件**: 已經包含檔案上傳 (`file_uploader`)、載入轉圈 (`spinner`) 與檔案下載 (`download_button`) 等必要功能，非常適合本專案的單頁應用 (SPA) 需求。

## 開發與測試工具

### 1. Unittest

- **用途**: 單元測試框架 (Python內建)。
- **說明**: `tests/` 目錄下的所有測試皆基於此框架，確保清洗與轉換邏輯在修改後仍能正確運作。

### 2. Argparse

- **用途**: 命令列參數解析 (Python內建)。
- **說明**: 用於 `src/epub2md.py` 的 CLI 介面，處理檔案路徑與輸出目錄參數。
