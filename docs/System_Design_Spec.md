# 系統開發規格書 (System Design Specification)

## 專案名稱：Epub2NotebookLM-Converter

### 1. 簡介 (Introduction)

#### 1.1 目的

本文件旨在定義 `Epub2NotebookLM-Converter` 的系統架構與功能規格。本專案核心目標為開發一自動化工具，將 EPUB 電子書轉換為針對 Google NotebookLM RAG (Retrieval-Augmented Generation) 優化的 Markdown 格式。

#### 1.2 範圍

系統將接受標準 EPUB (`.epub`) 檔案作為輸入，輸出單一 Markdown (`.md`) 檔案。系統不涉及 EPUB 的 DRM 解密功能。

---

### 2. 系統架構 (System Architecture)

系統採用單向資料流管道 (Pipeline) 架構：

```mermaid
graph LR
    A[Input .epub] --> B[Extractor]
    B --> C[Cleaner]
    C --> D[Converter]
    D --> E[Integrator]
    E --> F[Output .md]
```

#### 2.1 技術棧 (Tech Stack)

- **語言**: Python 3.10+
- **核心依賴**:
  - `EbookLib`: 處理 EPUB 容器與 Spine 读取。
  - `BeautifulSoup4`: HTML 解析與 DOM 操作 (Sanitization)。
  - `markdownify`: HTML 到 Markdown 的轉換。

---

### 3. 功能模組詳細規格 (Module Specifications)

#### 3.1 讀取模組 (Extractor Module)

- **職責**: 解析 EPUB 結構，按正確順序提取內容。
- **輸入**: EPUB 檔案路徑。
- **輸出**: 已排序的 HTML 內容列表與 Metadata。
- **關鍵邏輯**:
  - 使用 `ebooklib` 開啟檔案。
  - 讀取 Dublin Core Metadata (標題、作者)。
  - **Spine 遍歷**: 嚴格依照 `book.spine` 的順序迭代 `item`。
  - **過濾**: 僅處理 `item.get_type() == ebooklib.ITEM_DOCUMENT` (通常為 XHTML/HTML)。

#### 3.2 清洗模組 (Cleaner Module - ETL)

- **職責**: 移除雜訊，保留語意，處理圖片。
- **輸入**: 原始 HTML string。
- **輸出**: 清洗後的 HTML DOM (BeautifulSoup Object)。
- **清洗規則**:
  1. **移除標籤**: `script`, `style`, `meta`, `link`, `noscript`。
  2. **移除導航元素**: `nav`, `footer`, `header` (需根據常見 class name 或 tag 判斷)。
  3. **圖片處理**: 將 `<img>` 標籤替換為純文字 `[圖片說明: {alt_text}]`。若無 alt text 則標註 `[圖片]`.
  4. **屬性移除**: 移除所有標籤的 `style`, `class`, `id` 屬性 (除特定保留外)，減少 Token 消耗。

#### 3.3 轉換模組 (Converter Module)

- **職責**: 將 HTML 轉換為 Markdown。
- **輸入**: 清洗後的 HTML。
- **輸出**: Markdown 片段 (String)。
- **轉換規則 (Markdownify 配置)**:
  - **標題**: 強制 `<h1>` - `<h6>` 對應 `#` - `######`。
  - **連結**:
    - 內部連結 (href 以 `#` 開頭或相對路徑): 移除連結標籤，保留連結文字。
    - 外部連結 (http/https): 保留完整 `[text](url)` 格式。
  - **程式碼**: 強制保留 `pre`, `code` 區塊結構。
  - **空白處理**: 壓縮多餘換行，將 `\n\n\n+` 替換為 `\n\n`。
  - **表格**: 盡量還原表格結構。若遇到過於複雜的表格 (含大量 colspan/rowspan) 且無法正確轉換時，才考慮降級為純文字列表，優先保持表格語意。

#### 3.4 整合輸出模組 (Integrator & Writer)

- **職責**: 組合章節，注入 Metadata，寫入檔案。
- **處理邏輯**:
  1. **TOC 補償 (核心需求)**: 當章節內容中未偵測到 Header (`#`) 時，**必須**查詢 NCX/TOC 獲取該章節名稱，並強制插入 `# 章節名稱`，確保結構完整。
  2. **分隔線**: 每個 Spine Item 轉換後的內容之間插入 `---`。
  3. **Front Matter**: 檔案首部插入：

     ```markdown
     # 書名：{title}

     # 作者：{creator}

     # 轉換日期：{date}

     ---
     ```

  4. **檔名**: 格式 `{書名}_{作者}.md`，需處理檔名中的非法字元 (如 `/`, `:`, `*` 等)。

---

### 4. 異常處理 (Error Handling)

- **檔案損毀**: 若 EPUB 無法開啟，紀錄 Error Log 並終止程式。
- **編碼錯誤**: 讀取 HTML 內容時需強制處理 UTF-8 編碼，若遇亂碼則嘗試 fallback 編碼或忽略錯誤字元。
- **解析失敗**: 若單一章節轉換失敗，紀錄 Warning Log，跳過該章節並繼續處理下一章，不應中斷整個書籍的轉換。

### 5. 使用者介面 (User Interface)

#### 5.1 命令列介面 (CLI)

- **指令**:

  ```bash
  python src/epub2md.py input.epub [output_dir]
  ```

- **參數**:
  - `input.epub`: 來源檔案路徑。
  - `output_dir`: (選填) 輸出目錄，預設為當前目錄。

#### 5.2 網頁介面 (Web UI)

- **技術**: Streamlit
- **核心功能**:
  - **拖曳上傳**: 支援使用者拖曳單一或多個 `.epub` 檔案進行上傳。
  - **批次處理 (Batch Processing)**: 針對多個檔案進行佇列轉換，並顯示總體進度。
  - **自動重置 (Workflow Optimization)**: 轉換成功後，介面會自動重置上傳區狀態，方便使用者接續上傳下一批次檔案，而無須手動重新整理。
  - **彈性下載 (Smart Download)**:
    - 單檔轉換：直接下載 `.md` 檔案，並預覽前 2000 字部分。
    - 多檔轉換：自動打包為單一 `.zip` 檔案以便下載。
- **啟動方式**:

  ```bash
  streamlit run src/web_ui.py
  ```

---

### 6. 開發與測試計畫

- **單元測試**: 針對 Cleaner 和 Converter 撰寫測試案例 (Input HTML -> Expected Markdown)。
- **整合測試**: 選取 3-5 本不同排版風格的 EPUB (技術書、小說、多重巢狀目錄) 進行實測。
