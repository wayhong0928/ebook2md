# 系統功能 API 參考手冊 (API Reference)

本文檔針對開發者，詳細說明 `src/` 目錄下各核心模組的類別與函式設計。

## 1. 模組：`extractor.py` (讀取與提取)

負責處理 EPUB 檔案的底層讀取與結構提取。

### Class `EpubExtractor`

- **`__init__(self, epub_path)`**
  - **參數**: `epub_path` (str) - EPUB 檔案的絕對路徑。
  - **例外**: 若檔案不存在引發 `FileNotFoundError`，讀取失敗引發 `RuntimeError`。
  - **功能**: 初始化 `EbookLib` 的 book 物件並建構 TOC 映射表。

- **`get_metadata(self) -> dict`**
  - **回傳**: 字典 `{'title': str, 'author': str}`。
  - **功能**: 從 Dublin Core metadata 提取書名與作者。若無資訊則回傳 "Untitled Book" / "Unknown Author"。

- **`get_spine_items(self)`**
  - **回傳**: Generator，依序產出 `(content: bytes, title: str|None, file_name: str)`。
  - **功能**:
    - 依照 EPUB `Spine` 順序遍歷。
    - 僅回傳 `ITEM_DOCUMENT` 類型的項目 (過濾 CSS/Images)。
    - 嘗試透過 `file_name` 對照 TOC 取得該章節標題 (用於後續標題補全)。

---

## 2. 模組：`cleaner.py` (清洗與 ETL)

負責 HTML 內容的雜訊過濾與格式標準化。

### Class `EpubCleaner`

- **`__init__(self, html_content)`**
  - **參數**: `html_content` (bytes | str) - 原始 HTML 內容。
  - **功能**: 處理編碼 (UTF-8 / Latin-1 fallback)，移除 XML declaration，並建立 BeautifulSoup 物件。

- **`clean(self) -> BeautifulSoup`**
  - **回傳**: 清洗後的 `BeautifulSoup` 物件。
  - **功能**: 執行完整的清洗 Pipeline (`_remove_noise_tags` -> `_remove_structural_noise` -> `_process_images` -> `_clean_attributes`)。

- **`_process_images(self)`** (Internal)
  - **功能**: 將 `<img>` 標籤替換為文字 `[圖片說明: {alt}]`，這是為了 NotebookLM 優化的關鍵步驟。

---

## 3. 模組：`converter.py` (格式轉換)

負責將清洗後的 HTML 轉換為 Markdown。

### Class `CustomMarkdownConverter` (繼承自 `markdownify.MarkdownConverter`)

- **`convert_a(self, el, text, convert_as_inline, **kwargs)`\*\* (Override)
  - **功能**:
    - 若 `href` 是外部連結 (http/https)，保留連結語法 `[text](url)`。
    - 若 `href` 是內部連結 (Anchor)，**移除連結但保留文字**，避免斷鏈。

### Class `EpubConverter`

- **`convert(self, html_soup) -> str`**
  - **參數**: `html_soup` (BeautifulSoup) - 已清洗的 DOM 物件。
  - **回傳**: 轉換後的 Markdown 字串。
  - **功能**: 呼叫 `CustomMarkdownConverter` 並執行後處理 (Post-processing)。

- **`_post_process(self, text)`** (Internal)
  - **功能**: 使用 Regex 將連續 3 個以上的換行符號壓縮為 2 個 (`\n\n`)。

---

## 4. 模組：`epub2md.py` (主要控制器)

系統入口與流程控制。

### Function `generate_markdown_content(epub_path) -> tuple`

- **參數**: `epub_path` (str)
- **回傳**: `(md_content: str, filename: str)`
- **功能**:
  1. 呼叫 `Extractor` 讀取資料。
  2. 生成 Front Matter (Metadata)。
  3. 迴圈處理每個章節：`Cleaner` -> `Converter`。
  4. **TOC 補償邏輯**: 若轉換後的 Markdown 開頭無標題，自動補上 `# {TOC_Title}`。
  5. 組合所有內容並回傳。

### Function `process_epub(epub_path, output_dir)`

- **功能**: CLI 模式的主要執行函式，呼叫上述生成函式並將結果寫入 `output_dir`。
