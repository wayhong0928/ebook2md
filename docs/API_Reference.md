# 系統功能 API 參考手冊 (API Reference)

本文檔針對開發者，詳細說明 `src/` 目錄下各核心模組的類別與函式設計。

## 1. 模組：`extractor.py` (讀取與提取)

負責處理 EPUB 檔案的底層讀取與結構提取。

### Class `EpubExtractor`

- **`__init__(self, epub_path)`**
  - **參數**: `epub_path` (str) - EPUB 檔案的絕對路徑。
  - **例外**: 若檔案不存在引發 `FileNotFoundError`，讀取失敗引發 `RuntimeError`。
  - **功能**: 初始化 `EbookLib` 的 book 物件並建構 TOC 對照。manifest 列了但壓縮檔裡沒有的檔案（圖片、CSS、nav、NCX）不會讓讀取失敗，檔名記在 `self.missing_files`。
  - **屬性**: `toc_entries` — `{文件名: [TocEntry(title, depth, fragment), ...]}`，含巢狀的 `Section`，依 TOC 順序；`toc_map` — `{文件名: 第一個條目標題}`（舊介面）。
  - TOC 的 href 若相對於別的目錄（例如 `../OEBPS/Text/01.xhtml`），會依路徑後綴、再依唯一檔名對回實際文件。

- **`get_metadata(self) -> dict`**
  - **回傳**: 字典 `{'title': str, 'author': str}`。
  - **功能**: 從 Dublin Core metadata 提取書名與作者。若無資訊則回傳 "Untitled Book" / "Unknown Author"。

- **`get_spine_documents(self)`**
  - **回傳**: Generator，依 `Spine` 順序產出 `SpineDocument(content, href, toc_entries)`，只含 `ITEM_DOCUMENT`。

- **`get_spine_items(self)`**（舊介面，保留相容）
  - **回傳**: Generator，依序產出 `(content: bytes, title: str|None, file_name: str)`。

---

## 2. 模組：`cleaner.py` (清洗與 ETL)

負責 HTML 內容的雜訊過濾與格式標準化。

### Class `EpubCleaner`

- **`__init__(self, html_content)`**
  - **參數**: `html_content` (bytes | str) - 原始 HTML 內容。
  - **功能**: 處理編碼（先試 UTF-8，失敗時依文件宣告的 charset 偵測，例如 Big5），移除 XML declaration，並建立 BeautifulSoup 物件。

- **`apply_toc_headings(self, toc_entries) -> int`**
  - **功能**: 在 `clean()` 之前呼叫（id 還在）。對帶 `#fragment` 的 TOC 條目，找到錨點：
    - 錨點後第一個有字的區塊已是標題 → 不動（含拆成兩個標題的章名）。
    - 錨點或其後區塊的文字就是 TOC 標題 → 把該區塊改成 `h{depth}`。
    - 文字對不上 → 在錨點前插入 `h{depth}`；錨點在段落中間時不插，避免切斷句子。
    - 找不到錨點的條目記在 `self.unanchored`。
  - **回傳**: 新增的標題數。

- **`clean(self) -> BeautifulSoup`**
  - **回傳**: 清洗後的 `BeautifulSoup` 物件。
  - **功能**: 執行完整的清洗 Pipeline (`_remove_noise_tags` -> `_remove_structural_noise` -> `_process_images` -> `_clean_attributes`)。移除 `nav`／`header`／`footer`，`aside` 保留（EPUB 的註腳放在這裡）。

- **`_process_images(self)`** (Internal)
  - **功能**: 將 `<img>` 標籤替換為文字 `[圖片說明: {alt}]` 或 `[圖片]`；標題裡沒有 alt 的裝飾圖示直接移除。

---

## 3. 模組：`converter.py` (格式轉換)

負責將清洗後的 HTML 轉換為 Markdown。

### Class `CustomMarkdownConverter` (繼承自 `markdownify.MarkdownConverter`)

- **`convert_a(self, el, text, convert_as_inline, **kwargs)`\*\* (Override)
  - **功能**:
    - 若 `href` 是外部連結 (http/https)，保留連結語法 `[text](url)`。
    - 若 `href` 是內部連結 (Anchor)，**移除連結但保留文字**，避免斷鏈。

- **`convert_hr(...)`** (Override)
  - **功能**: `<hr>` 輸出成 `* * *`，讓 `---` 只代表 spine 文件之間的分界（pipeline 依 `---` 切 md）。

### Class `EpubConverter`

- **`convert(self, html_soup) -> str`**
  - **參數**: `html_soup` (BeautifulSoup) - 已清洗的 DOM 物件。
  - **回傳**: 轉換後的 Markdown 字串。
  - **功能**: 呼叫 `CustomMarkdownConverter`（`escape_underscores=False`：填空線與 URL 裡的底線不加反斜線）並執行後處理 (Post-processing)。

- **`_post_process(self, text)`** (Internal)
  - **功能**: 使用 Regex 將連續 3 個以上的換行符號壓縮為 2 個 (`\n\n`)。

---

## 4. 模組：`epub2md.py` (主要控制器)

系統入口與流程控制。

### Function `generate_markdown_content(epub_path, stats=None) -> tuple`

- **參數**: `epub_path` (str)；`stats` (dict，選填) — 會填入 `documents`、`empty_documents`、`failed_documents`、`toc_headings_added`、`file_titles_added`、`missing_files`。
- **回傳**: `(md_content: str, filename: str)`
- **功能**:
  1. 呼叫 `Extractor` 讀取資料。
  2. 生成 Front Matter (Metadata)。
  3. 迴圈處理每個文件：`apply_toc_headings` -> `clean` -> `Converter`。
  4. **TOC 補償邏輯**: 文件開頭連續的標題裡找不到它的 TOC 標題時，補上 `{'#' * depth} {TOC_Title}`。錨點不存在的條目（常見於版權頁、書名頁）視同指向整個檔案。
  5. 組合所有內容，每個文件後接一行 `---`。

### Function `process_epub(epub_path, output_dir, output_name=None)`

- **功能**: CLI 模式的主要執行函式，呼叫上述生成函式並將結果寫入 `output_dir`。`output_name` 指定輸出檔名（CLI 的 `-o/--output-name`），預設 `{書名}_{作者}.md`。
