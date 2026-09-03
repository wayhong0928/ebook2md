# Claude × Obsidian 書籍管理 Pipeline

將 Ebook 書庫自動分類，並在 Obsidian 建立結構化書籍筆記與概念卡片的批次處理工具。

---

## 目錄結構

```
pipeline/
├── config.py               # 所有路徑常數（單一真實來源）
├── manifest.py             # 書庫掃描與狀態追蹤
├── convert.py              # EPUB → Markdown 批次包裝器
├── classify.py             # 分類批次匯出 / 套用結果
├── create_book_card.py     # 在 Obsidian 建立書籍筆記 stub
├── notes.py                # Phase 2：EPUB 解析 + 筆記生成
├── sync.py                 # 三檔同步移動（EPUB + MD + 筆記）
├── run_pipeline.py         # 主 CLI 入口
├── logger.py               # Rotating file log + console log
├── activity.py             # Append-only activity log (JSONL)
├── manifest.json           # 書庫狀態（自動生成，勿手改）
├── pending_classify.json   # 待分類批次（process-new 輸出）
├── classify_results.json   # 分類結果（Claude Code 寫入）
├── pending_notes.json      # 待筆記章節（prepare-notes 輸出）
├── notes_results.json      # 筆記結果（Claude Code 寫入）
├── activity_log.jsonl      # 每個操作的歷程紀錄
└── logs/
    └── pipeline.log        # Rotating log（5 MB × 5 份）
```

### Obsidian Vault 結構

```
D:\github-repo\Obsidian Vault\Ebook\
├── CLAUDE.md               # 系統路徑速查與 CLI 指令手冊
├── 00_Inbox\               # 低信心度分類暫存，人工確認後移走
├── 10_Books\               # 書籍筆記（依 15 個分類 + 系列子資料夾）
├── 20_Concepts\            # 概念卡片（Zettelkasten 永久筆記）
├── 30_MOC\                 # 主題索引頁（Map of Content）
├── 40_Reflections\         # 個人心得、閱讀文章草稿
└── 90_Templates\
    ├── 書籍筆記_template.md    # Phase 1 stub + Phase 2 完整筆記格式
    ├── 概念卡片_template.md    # 概念卡片格式
    └── MOC_template.md         # 主題索引頁格式
```

---

## 筆記類型說明

### 書籍筆記（`10_Books/[類別]/書名.md`）

Phase 1 建立 stub（`status: card_only`），Phase 2 填入完整章節內容（`status: notes_generated`）。

**結構：**
```markdown
## 核心前提       ← 分類時 AI 產出（≤ 50 字）
## 目錄摘要       ← Phase 1：toc_summary；Phase 2：book_summary（5 句總結）
---
## 章節筆記       ← Phase 2 逐章填入
  ### 章節標題
  #### 摘要       ← ≤ 100 字
  #### 重點擷取   ← 100% 原文引述（不允許改寫）
  #### 關鍵概念   ← [[wikilink]] 連結至 20_Concepts/
  #### 我的想法   ← 空白，使用者撰寫
## 全書概念連結   ← 自動彙整所有章節提及的概念（去重）
## MOC 連結建議   ← 依分類自動填入，如 [[_思考方法_MOC]]
## 整體心得       ← 空白，使用者撰寫
```

### 概念卡片（`20_Concepts/概念名.md`）

從書籍筆記提取的原子概念，獨立成卡。`#type/concept`，記錄定義、原文出處、相關概念連結。

**無獨立書籍卡片**。書籍筆記本身即為單一入口，20_Concepts 只存放概念卡片。

---

## 書籍狀態流轉

```
raw              → EPUB 存在，尚未轉 MD
converted        → MD 已轉，尚未分類
classified       → 分類完成，尚未建 Obsidian 筆記
card_only        → 書籍筆記 stub 已建（章節筆記尚未生成）
notes_generated  → 完整書籍筆記已生成（Phase 2）
reading          → 正在閱讀中
done             → 閱讀完畢
```

---

## 標準工作流程

> 工作目錄：`D:\github-repo\epub_to_markdown`

### 每次 Session 開始

```bash
python pipeline/run_pipeline.py log      # 最近操作紀錄
python pipeline/run_pipeline.py status   # 書庫整體狀態
```

### Phase 1：分類 + 建書籍筆記 stub

```bash
# Step 1：掃描新 EPUB + 轉 MD + 準備分類批次
python pipeline/run_pipeline.py process-new --limit 20

# Step 2：請 Claude Code：
#   "請分類 pipeline/pending_classify.json，輸出到 pipeline/classify_results.json"

# Step 3：套用分類結果 + 建 Obsidian 書籍筆記 stub
python pipeline/run_pipeline.py apply-batch --cards
```

### Phase 2：生成完整章節筆記（Claude Code 在對話中完成）

```bash
# Step 1：從 EPUB 切片（優先使用 EPUB，MD 作 fallback）
python pipeline/run_pipeline.py prepare-notes --book-id "書名"

# Step 2：請 Claude Code：
#   "請讀 pipeline/pending_notes.json，幫我生成書籍筆記，輸出到 pipeline/notes_results.json"
#   格式：book_summary + 每章 {title, summary, key_quotes, key_concepts} + concept_cards

# Step 3：套用到 Obsidian
python pipeline/run_pipeline.py apply-notes
```

**notes_results.json 格式：**
```json
{
  "book_id": "書名",
  "book_summary": "全書核心（≤5句）",
  "chapters": [
    {
      "chapter_num": 1,
      "title": "章節標題",
      "summary": "≤100字",
      "key_quotes": ["原文引述"],
      "key_concepts": ["概念名"]
    }
  ],
  "concept_cards": [
    {
      "title": "概念名",
      "definition": "原子定義",
      "source_quote": "原文",
      "related_concepts": ["相關概念"]
    }
  ]
}
```

### 手動調整

```bash
# 重新分類（同步移動 EPUB + MD + Obsidian 筆記）
python pipeline/run_pipeline.py reclassify --book-id "書名" --category "心理學"

# 將 Inbox 中已確認的筆記移到正確分類
python pipeline/run_pipeline.py inbox-move --book-id "書名"

# 查看單本書的操作歷程
python pipeline/run_pipeline.py history --book-id "書名"
```

---

## 分類規則

| 規則 | 說明 |
|------|------|
| 15 個核心分類 | 人物傳記、個人成長、商業管理、工作技能、心理學、思考方法、投資理財、文學小說、歷史政治、社會科學、資訊科技、運動科學、醫療專業、生活風格、尚未歸檔 |
| 信心度 < 0.7 | 筆記輸出至 `00_Inbox/`，人工確認後用 `inbox-move` 移走 |
| 跨領域書籍 | 主分類 + `sub_categories` 補充次要領域 |
| 全新領域 | `category: 尚未歸檔`，`new_category_suggestion` 提供建議 |
| 系列/作者子資料夾 | 同系列或同作者在整個書庫 ≥ 6 本時，自動建子資料夾 |

---

## EPUB 章節解析策略

Phase 2 優先從 EPUB 直接解析（`notes.py`），而非轉換後的 MD：

- **Spine 讀取順序**：依 EPUB `spine` 確保章節正確排列
- **TOC 標題對應**：從 EPUB `toc` 提取章節標題，比 MD 轉換後的標題更精準
- **過濾規則**：章節字數 < 200 字跳過（版權頁、目次等）
- **截斷上限**：每章最多 8000 字送入 Claude，最多 30 章
- **fallback**：EPUB 解析章數 < 2 章時，改用 MD 以 `---` 分隔切片

---

## 待規劃功能（下次 Session）

1. **書庫全量佇列**：`scan` 後將所有 EPUB 加入進度追蹤佇列，方便 Phase 1+2 批次進行
2. **章節目錄錨點**：在 `## 章節筆記` 前加入 TOC（Obsidian `[[#標題]]` 錨點連結），方便快速跳章
3. **Phase 1+2 合批流程**：一次指令驅動多本書完整流程（分類 → 準備筆記 → Claude 生成 → 套用）

---

## 環境安裝

```bash
pip install -r pipeline/requirements.txt
# 需要：tqdm、EbookLib、BeautifulSoup4、markdownify
# anthropic 套件備用（目前 Claude Code 在對話中完成，不需 API key）
```

PDF 書籍目前不在處理範圍，規劃於未來版本加入。
