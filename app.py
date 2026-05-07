import streamlit as st
import pandas as pd
import tempfile
import os
import json
import re
from openai import OpenAI
from pathlib import Path

# ────────────── AI引擎（内置） ──────────────
def process_excel_with_ai(file_path, sheet_name=None):
    df = pd.read_excel(file_path, sheet_name=sheet_name, dtype=str)
    all_rows = []
    for idx, row in df.iterrows():
        cat = row.get('类别', '')
        name = row.get('名称', '')
        method = row.get('构造做法', '')
        scope = row.get('适用范围', '')
        remark = row.get('备注', '')
        if pd.isna(method) or str(method).strip() == '':
            continue
        all_rows.append({
            "类别": str(cat),
            "名称": str(name),
            "构造做法": str(method),
            "适用范围": str(scope) if not pd.isna(scope) else "",
            "备注": str(remark) if not pd.isna(remark) else ""
        })

    client = OpenAI(
        api_key=st.secrets["DEEPSEEK_API_KEY"],
        base_url="https://api.deepseek.com"
    )

    batch_size = 10  # 适当减小批次，提高稳定性
    all_bills = []
    required_keys = ["项目编码", "项目名称", "项目特征", "计量单位", "工程量", "备注", "定额编号"]

    for i in range(0, len(all_rows), batch_size):
        batch = all_rows[i:i+batch_size]
        prompt = f"""
你是工程造价专家。根据以下做法表生成GB50500-2013分部分项工程量清单JSON。

要求：
1. 编码严格符合国标，同做法编码一致，不同部位区分。
2. 名称体现厚度、材料、强度等关键参数，不可重复。
3. 项目特征按层次从上到下编号列出，每一条用"\\n"换行。
4. 单位合理确定(m²/m³/m/t/个等)。
5. 涉及混凝土默认商品混凝土，砂浆默认干混砂浆。
6. 匹配四川2020定额编号。
7. 输出纯JSON数组，不要加任何解释文字。

做法表：
{json.dumps(batch, ensure_ascii=False, indent=2)}
"""
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role":"user","content":prompt}],
            temperature=0.1,
            max_tokens=4000
        )
        text = resp.choices[0].message.content

        try:
            # 清理可能的 markdown 标记
            clean_text = re.sub(r'```json|```', '', text).strip()
            records = json.loads(clean_text)

            # 验证每条记录是否包含所有必要字段
            valid_records = []
            for rec in records:
                if all(key in rec for key in required_keys):
                    valid_records.append(rec)
                else:
                    st.warning(f"⚠️ AI 生成了一条不完整的记录，已自动跳过：{rec.get('项目名称', '未知')}")

            all_bills.extend(valid_records)
            st.write(f"✅ 本批次成功生成 {len(valid_records)} 条记录")

        except json.JSONDecodeError as e:
            st.error(f"❌ AI 返回的数据格式有误，本批次跳过。AI 原始输出：\n```\n{text}\n```")
        except Exception as e:
            st.error(f"❌ 处理 AI 返回数据时出错：{str(e)}")

    return all_bills

def write_csv(bills, path):
    import csv
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=["项目编码","项目名称","项目特征","计量单位","工程量","备注","定额编号"])
        w.writeheader()
        w.writerows(bills)

# ────────────── Streamlit 界面 ──────────────
st.set_page_config(page_title="智能清单生成器", layout="wide")
st.title("🏗️ 智能分部分项清单生成工具")
st.markdown("上传构造做法表，AI自动生成符合GB 50500规范的清单（含四川2020定额）")

uploaded_file = st.file_uploader("📁 选择Excel文件", type=["xls","xlsx"])
sheet = st.text_input("📋 工作表名", "Sheet1")

if uploaded_file:
    st.info("📌 文件已上传，请点击下方按钮开始生成")
    if st.button("🚀 开始生成清单", type="primary"):
        with tempfile.NamedTemporaryFile(delete=False, suffix=Path(uploaded_file.name).suffix) as tmp:
            tmp.write(uploaded_file.getvalue())
            tmp_path = tmp.name

        try:
            with st.spinner("🤖 AI正在处理中，请稍候... 通常需要15-30秒"):
                bills = process_excel_with_ai(tmp_path, sheet)
            os.unlink(tmp_path)

            if bills:
                st.success(f"🎉 成功生成 {len(bills)} 条清单")
                df_view = pd.DataFrame(bills)
                df_view["项目特征"] = df_view["项目特征"].str.replace("\n", " | ")
                st.dataframe(df_view[["项目编码","项目名称","项目特征","计量单位","工程量","备注","定额编号"]], use_container_width=True)

                out_path = tempfile.NamedTemporaryFile(delete=False, suffix=".csv").name
                write_csv(bills, out_path)
                with open(out_path, "r", encoding="utf-8-sig") as f:
                    csv_data = f.read()
                os.unlink(out_path)
                st.download_button("⬇️ 下载清单CSV", data=csv_data.encode("utf-8-sig"), file_name="工程清单.csv")
            else:
                st.warning("⚠️ 没有生成任何有效清单。请检查表格中是否有完整的'构造做法'列，或联系管理员。")
        except Exception as e:
            st.error(f"❌ 运行出错：{str(e)}")
            st.error("如问题持续出现，请截图本页面并联系开发者。")
