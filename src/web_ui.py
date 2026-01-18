import streamlit as st
import os
import tempfile
import sys
import zipfile
import io

# Add current directory to path so we can import modules
sys.path.append(os.path.dirname(__file__))

from epub2md import generate_markdown_content

st.set_page_config(page_title="Epub2NotebookLM Converter", page_icon="📚")

# Initialize session state for uploader key and previous results
if "uploader_key" not in st.session_state:
    st.session_state.uploader_key = 0
if "last_results" not in st.session_state:
    st.session_state.last_results = None

st.title("📚 Epub to Markdown Converter")
st.markdown("""
這個工具可以將 EPUB 電子書轉換為 Markdown 格式。
它會自動清理雜訊、保留章節結構，並處理圖片與連結。

**Tip:** 支援批次上傳！轉換完成後會自動重置，方便您直接上傳下一批書籍。
""")

# --- Result Display Section (Shows results from previous run) ---
if st.session_state.last_results:
    st.divider()
    st.success(f"✅ 上一次轉換成功！ (共 {len(st.session_state.last_results)} 個檔案)")

    results = st.session_state.last_results

    # Download Logic
    if len(results) == 1:
        filename, content = results[0]
        st.download_button(
            label=f"📥 下載 {filename}",
            data=content,
            file_name=filename,
            mime="text/markdown",
            key="download_single_last",
        )
    else:
        # Create ZIP
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for filename, content in results:
                zf.writestr(filename, content)

        st.download_button(
            label="📦 下載所有檔案 (ZIP)",
            data=zip_buffer.getvalue(),
            file_name="converted_books.zip",
            mime="application/zip",
            key="download_zip_last",
        )
    st.divider()


# --- Upload Section ---
uploaded_files = st.file_uploader(
    "上傳 EPUB 檔案 (支持多選)",
    type=["epub"],
    accept_multiple_files=True,
    key=f"uploader_{st.session_state.uploader_key}",
)

if uploaded_files:
    # 顯示上傳檔案數量
    file_count = len(uploaded_files)
    st.info(f"已選取 {file_count} 個檔案，準備轉換...")

    # 顯示前 10 筆檔案名稱
    with st.expander("查看已選取檔案"):
        for i, f in enumerate(uploaded_files[:10]):
            st.text(f"{i + 1}. {f.name}")
        if file_count > 10:
            st.text(f"... 以及其他 {file_count - 10} 個檔案")

    if st.button("🚀 開始轉換", type="primary"):
        with st.spinner("正在轉換中..."):
            # 準備結果容器
            results = []  # List of (filename, content)
            progress_bar = st.progress(0)

            for idx, uploaded_file in enumerate(uploaded_files):
                try:
                    # Save uploaded file to a temporary file
                    with tempfile.NamedTemporaryFile(
                        delete=False, suffix=".epub"
                    ) as tmp_file:
                        tmp_file.write(uploaded_file.getvalue())
                        tmp_path = tmp_file.name

                    # Process
                    md_content, _ = generate_markdown_content(tmp_path)

                    # Use uploaded filename as base
                    base_name = os.path.splitext(uploaded_file.name)[0]
                    output_filename = f"{base_name}.md"

                    # Cleanup temp file
                    try:
                        if os.path.exists(tmp_path):
                            os.unlink(tmp_path)
                    except Exception as e:
                        print(f"Warning: Could not delete temp file {tmp_path}: {e}")

                    results.append((output_filename, md_content))

                except Exception as e:
                    st.error(f"檔案 {uploaded_file.name} 轉換失敗：{e}")
                    # Cleanup even on error
                    try:
                        if "tmp_path" in locals() and os.path.exists(tmp_path):
                            os.unlink(tmp_path)
                    except Exception:
                        pass  # Ignore cleanup errors on failure

                # Update progress
                progress_bar.progress((idx + 1) / file_count)

            if results:
                # Store results in session state
                st.session_state.last_results = results

                # Increment key to clear uploader
                st.session_state.uploader_key += 1

                # Rerun to refresh UI (Clear uploader & Show Result Section)
                st.rerun()
            else:
                st.error("沒有檔案轉換成功。")
