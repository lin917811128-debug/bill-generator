import streamlit as st
import pandas as pd
import tempfile
import os
from pathlib import Path
from engine import process_excel_with_ai, write_csv

st.set_page_config(page_title="智能清单生成器", layout="wide")
st.title("🏗️ 智能分部分项清单生成工具")
st.markdown("上传构造做法表，自动生成符合GB 50500规范的清单（含四川2020定额）")

uploaded_file = st.file_uploader("📁 选择Excel文件", type=["xls", "xlsx"])
sheet = st.text_input("工作表名", "Sheet1")

if uploaded_file:
    st.info("📌 文件已上传，请点击下方按钮开始生成清单")
    if st.button("🚀 开始生成清单", type="primary"):
        with tempfile.NamedTemporaryFile(delete=False, suffix=Path(uploaded_file.name).suffix) as tmp:
            tmp.write(uploaded_file.getvalue())
            tmp_path = tmp.name

        try:
            with st.spinner("🤖 AI正在处理中，请稍候..."):
                bills = process_excel_with_ai(tmp_path, sheet)
            os.unlink(tmp_path)

            if bills:
                st.success(f"✅ 成功生成 {len(bills)} 条清单")
                df_view = pd.DataFrame(bills)
                df_view["项目特征"] = df_view["项目特征"].str.replace("\n", " | ")
                st.dataframe(df_view[["项目编码", "项目名称", "项目特征", "计量单位", "工程量", "备注", "定额编号"]], use_container_width=True)

                out_path = tempfile.NamedTemporaryFile(delete=False, suffix=".csv").name
                write_csv(bills, out_path)
                with open(out_path, "r", encoding="utf-8-sig") as f:
                    csv_data = f.read()
                os.unlink(out_path)
                st.download_button("⬇️ 下载清单CSV", data=csv_data.encode("utf-8-sig"), file_name="工程清单.csv")
            else:
                st.warning("⚠️ 未提取到清单项，请检查表格格式。")
        except Exception as e:
            st.error(f"❌ 错误：{e}")