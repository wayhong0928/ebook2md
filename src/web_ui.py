import streamlit as st
import os
import tempfile
import sys

# Add current directory to path so we can import modules
sys.path.append(os.path.dirname(__file__))

from epub2md import generate_markdown_content

st.set_page_config(page_title="Epub2NotebookLM Converter", page_icon="📚")

st.title("📚 Epub to Markdown Converter")
st.markdown("""
這個工具可以將 EPUB 電子書轉換為 **Google NotebookLM** 友善的 Markdown 格式。
它會自動清理雜訊、保留章節結構，並處理圖片與連結。
""")

uploaded_file = st.file_uploader("上傳 EPUB 檔案", type=["epub"])

if uploaded_file is not None:
    st.info(f"檔案已上傳：{uploaded_file.name}")

    if st.button("開始轉換", type="primary"):
        with st.spinner("正在轉換中... (這可能需要幾秒鐘)"):
            try:
                # Save uploaded file to a temporary file because ebooklib needs a path
                with tempfile.NamedTemporaryFile(
                    delete=False, suffix=".epub"
                ) as tmp_file:
                    tmp_file.write(uploaded_file.getvalue())
                    tmp_path = tmp_file.name

                # Process
                md_content, suggested_filename = generate_markdown_content(tmp_path)

                # Cleanup temp file
                os.unlink(tmp_path)

                # Success
                st.success("轉換成功！")

                # Download Button
                st.download_button(
                    label=f"下載 {suggested_filename}",
                    data=md_content,
                    file_name=suggested_filename,
                    mime="text/markdown",
                )

                # Preview
                with st.expander("預覽內容 (前 2000 字)"):
                    st.text(md_content[:2000] + "\n\n(內容過長，僅顯示部分...)")

            except Exception as e:
                st.error(f"轉換失敗：{e}")
                # Clean up if failed
                if "tmp_path" in locals() and os.path.exists(tmp_path):
                    os.unlink(tmp_path)
