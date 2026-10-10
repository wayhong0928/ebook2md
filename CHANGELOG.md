# 更新紀錄

v1.3.0 之前沒有打 tag。舊版本是事後依 commit 歷史整理的，v1.2 這條分界也是事後才訂。

## v1.6.0（2026-10-10）

這一版改架構，有不相容的變動。轉出來的 md 除了開頭多一行轉換器版本以外，跟 v1.5.0 逐字相同。

### 不相容的變動

- 程式改成 `ebook2md/` 套件：`epub/`（extractor、cleaner、converter、epub2md）、`pdf/pdf2md.py`（整檔搬入）、`slicing.py`（從 `pipeline/notes.py` 抽出章節切分）。`src/` 下的模組與 `pipeline/pdf2md.py` 移除。
- 單一命令列：`python -m ebook2md convert BOOK...`（依副檔名走 EPUB 或 PDF，`-o` 輸出目錄、`--name` 檔名）、`python -m ebook2md slice BOOK`（輸出章節 JSON）。加了 `pyproject.toml`，`pip install -e .` 後可直接打 `ebook2md`。舊入口 `src/epub2md.py` 保留這一版，執行時提示改用新指令。
- md 開頭多一行 `# 轉換器：ebook2md 1.6.0 (commit)`，記下轉出這份 md 的版本；套件有未 commit 的修改時加 `+dirty`。v1.6 以前的 md 沒有這一行，切片兩種都接受。
- 移除網頁介面（`src/web_ui.py`，Streamlit），requirements 也拿掉 streamlit。
- pipeline 的書庫與 vault 位置不再寫在 `config.py`，改讀環境變數 `EBOOK2MD_EBOOKS_ROOT`、`EBOOK2MD_VAULT_ROOT` 或本機的 `pipeline/local_config.json`（不進版本庫）。

### 新增

- `docs/output_format.md`：md 開頭、`---`、標題、圖片標記與章節 JSON 的規格。
- 測試：命令列、版本行、同一本書轉兩次逐位元相同、舊入口仍可用、版本庫的檔案不含個人路徑。

## v1.5.0（2026-10-10）

這一版整理工程面，轉出來的 md 跟 v1.4.0 逐字相同。

- 相依套件合成根目錄一份 `requirements.txt` 並釘死版本，PyMuPDF 補進來；`pipeline/requirements.txt` 改成引用它。程式沒用到的 anthropic、tqdm 移除。
- 新增 GitHub Actions：push 與 pull request 時跑版本庫裡的測試（Linux 3.10／3.12、Windows 3.11）。
- `docs/` 三份文件開頭標明描述的是 v1.3.0 的 EPUB 轉檔。

## v1.4.0（2026-10-10）

這一版加量測與防線，轉出來的 md 跟 v1.3.0 逐字相同。

### 新增

- `scripts/baseline.py`：全書庫數字基準。每本書記正文字數、分節數、標題數、殘留頁碼行數、刪掉的頁首頁尾數、跨頁接段數、切章數與切片自檢結果；正文字數不得少於基準、殘留頁碼不得多於基準，基準只在指名書目並寫明理由時才能放寬。基準檔只存在本機。
- `tests/test_slicing_invariants.py`：用隨機產生的書（含章末注釋、書末書目、超長章、一檔多章、只有圖的章名頁、短檔）檢查切片：正文不遺失、章節順序不變、注釋與書目不進章節、只在段落之間切。
- README 新增「已知限制」。

### 修正

- 切片：不到 200 字的片段原本一律併進相鄰片段，所以很短的書末書目（例如只有「參考文獻」標題）會併進前一章，書目前面一小段正文也可能被併進書目。現在書目保持書末附屬，前面的短正文併回前一章；全書最後一小段（書目後的版權頁）仍跟著前面的片段。全書庫 9 本書的切片因此改變，轉檔結果不受影響。

## v1.3.0（2026-10-06）

這一版的重點是 PDF 轉檔與章節切分要穩定、正確、有跡可循。

### PDF 轉檔（新增 `pipeline/pdf2md.py`，取代 MarkItDown）

- 以 PyMuPDF 讀文字層，書籤當章節標題，合併排版斷行與跨頁段落。
- 先判斷掃描檔與亂碼字型，這兩類不轉檔。
- 直排頁：欄由右至左重排；橫放的數字、英文、括號放回所在的欄。欄中心取欄內各字的中位數。欄比正文短、字數也少，又以句末標點結尾，就結束段落。
- 書眉與頁碼：依版面位置加跨頁重複判斷。版面已判定為書眉候選的欄，即使 OCR 弄亂了部分文字，只要有兩段字在 3 頁以上重複就刪除。沒刪掉的書眉自成一行，不截斷跨頁段落。
- 橫排頁：雙欄頁先讀左欄再讀右欄。條列符號開頭、字級改變一律換段；右邊不對齊的英文段落，另依縮排、編號步驟、粗細改變換段。
- PDF 開檔失敗不中斷批次。
- 新相依 PyMuPDF（AGPL-3.0／商業雙授權，與本專案的 MIT 不同）。目前只列在 `pipeline/requirements.txt`，根目錄的 `requirements.txt` 還沒有。

### EPUB 轉檔（`src/`）

- TOC 收巢狀小節並記錄層級，TOC 錨點轉成對應層級的標題，不切斷句子。
- 缺 nav／NCX 等檔案時不再失敗，缺檔彙總回報。
- 保留 aside 註腳；非 UTF-8 依宣告編碼解碼。
- 整頁圖片的文件保留 TOC 標題。
- 輸出格式改變：內文 `<hr>` 改輸出 `* * *`，`---` 只代表文件分界；底線不再跳脫。
- CLI 加 `-o/--output-name`。

### Phase 2 切片（`prepare-notes`）

- 不再把每章截在 4 萬字；超長章依 TOC 小節、標題、段落再拆。
- 一檔多章依 TOC 錨點切；章末注釋、書目、索引移到書末附屬，不放進章節。
- 章名頁的標題帶給內文檔，沒有標題的檔併入上一章。
- 短檔不再略過，只略過空白檔。
- 全書拼回原文自檢，沒通過就不寫檔。

### 測試

- `tests/test_pdf2md.py`：合成 PDF 的單元測試。
- `tests/test_pdf_bench.py`：用實書頁面的事實做檢查（present、absent、line、no_line、order、max_lines），做法參考 olmOCR-Bench。斷言取自實書，放在 gitignore 的 `tests/local_pdf_bench/`，沒有該檔就全部略過。
- 新增合成 EPUB 測試，涵蓋章末注釋與切片。

### 其他

- 專案改名 ebook2md，轉檔器路徑改由 `config.py` 的位置推算。

### 已知限制

- PDF 直排：條列只部分分行；跨頁的縮排新段偶爾沒斷開。
- PDF OCR 文字層：偶有書眉殘留；掉了句號時，相鄰的注釋會接成一段。
- PDF 橫排：條列偶爾在句中斷段；圖說、側邊標籤、灰底框的文字可能混進正文；表格欄序可能錯；英文複合詞剛好在行尾斷開時，連字號會被吃掉（self-driving 變成 selfdriving）。
- EPUB：少數 TOC 條目指向句子中間的頁碼錨點，這些地方刻意不插標題，md 會少掉這些小節標題（正文不缺）。

## v1.2（2026-08 至 09，未打 tag）

- Phase 2 移除章節上限，大書拆批處理。
- 重跑同一本書時，警告孤兒概念卡，並提供 `stale-review` 列出候選。
- 批次檔名可加 `--tag`，多本書平行處理時不會互相覆蓋。
- 修正 Windows cp950 編碼崩潰。
- 分類時同系列或同作者達 5 本就建子資料夾；`reclassify` 加 `--subfolder`／`--no-subfolder`。
- 新增 `onepage-candidates`。

## v1.1／v1.0（2026-01-18）

- EPUB 轉 Markdown 的第一版。
