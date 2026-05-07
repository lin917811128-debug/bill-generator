import streamlit as st
import pandas as pd
import tempfile
import os
import json
import re
from openai import OpenAI
from pathlib import Path

# ────────────── AI引擎 ──────────────
def extract_json_array(text: str):
    """从AI返回文本中提取JSON数组"""
    # 1. 直接解析
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return data
    except:
        pass

    # 2. 代码块提取
    match = re.search(r'```json\s*\n?(.*?)\n?```', text, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(1))
            if isinstance(data, list):
                return data
        except:
            pass

    # 3. 提取首尾括号
    start = text.find('[')
    end = text.rfind(']')
    if start != -1 and end != -1 and end > start:
        try:
            data = json.loads(text[start:end+1])
            if isinstance(data, list):
                return data
        except:
            pass

    return None

# 字段映射（AI可能使用的各种键名）
FIELD_ALIASES = {
    "项目编码": ["项目编码", "编码", "code", "项目编号"],
    "项目名称": ["项目名称", "名称", "name", "工程名称"],
    "项目特征": ["项目特征", "特征", "features", "描述", "做法"],
    "计量单位": ["计量单位", "单位", "unit"],
    "工程量": ["工程量", "数量", "quantity"],
    "定额编号": ["定额编号", "定额", "quota"],
    "备注": ["备注", "备注信息", "remark"]
}

def normalize_record(rec):
    """标准化记录键名，如果缺少关键字段尝试推断默认值"""
    norm = {}
    # 映射键名
    alias_map = {}
    for standard_key, aliases in FIELD_ALIASES.items():
        for alias in aliases:
            if alias in rec:
                alias_map[standard_key] = rec[alias]
                break

    # 最少需要‘项目特征’或‘项目名称’之一才能生成有效记录
    if "项目特征" not in alias_map and "项目名称" not in alias_map:
        return None

    # 填充默认值
    norm["项目编码"] = alias_map.get("项目编码", "010101001")  # 默认编码
    norm["项目名称"] = alias_map.get("项目名称", "未命名做法")
    norm["项目特征"] = alias_map.get("项目特征", "1. 参见构造做法")
    norm["计量单位"] = alias_map.get("计量单位", "m²")
    norm["工程量"] = alias_map.get("工程量", "1")
    norm["备注"] = alias_map.get("备注", "")
    norm["定额编号"] = alias_map.get("定额编号", "")

    return norm

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

    batch_size = 10
    all_bills = []
    raw_samples = []  # 收集原始输出样本

    for i in range(0, len(all_rows), batch_size):
        batch = all_rows[i:i+batch_size]
        prompt = f"""
你是工程造价师。基于以下做法表，生成GB50500-2013分部分项工程量清单JSON数组。
要求：
1. 编码符合国标，同类同码。
2. 名称含厚度、材料等。
3. 项目特征按层次编号，用 \n 分隔。
4. 单位 m²/m³/m/t。
5. 商品混凝土、干混砂浆。
6. 匹配四川2020定额。
7. 只输出纯JSON数组。

做法表：
{json.dumps(batch, ensure_ascii=False, indent=2)}
"""
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role":"user","content":prompt}],
            temperature=0.0,  # 降低温度，更确定
            max_tokens=4000
        )
        text = resp.choices[0].message.content
        raw_samples.append(text[:500])  # 保存前500字符用于诊断

        records = extract_json_array(text)

        if records is None:
            st.warning(f"⚠️ 第{i//batch_size+1}批返回不是有效JSON数组，已跳过。")
            continue

        batch_valid = 0
        for rec in records:
            norm_rec = normalize_record(rec)
            if norm_rec:
                all_bills.append(norm_rec)
                batch_valid += 1
            else:
                st.warning(f"⚠️ 跳过一条无效记录（缺少关键字段）")

        st.write(f"✅ 第{i//batch_size+1}批：生成 {batch_valid} 条清单")

    # 如果没有生成任何清单，展示原始数据供分析
    if not all_bills:
        st.error("❌ 全部批次均未生成有效清单。下面是 AI 返回的原始数据样本：")
        for idx, sample in enumerate(raw_samples):
            with st.expander(f"第 {idx+1} 批 AI 原始回复 (前500字)"):
                st.code(sample)
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
            with st.spinner("🤖 AI正在处理中... 正在提取清单项"):
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
                st.warning("⚠️ 没有生成任何有效清单。请检查‘构造做法’列是否完整，并展开上方AI原始回复信息分析原因。")
        except Exception as e:
            st.error(f"❌ 运行出错：{str(e)}")
