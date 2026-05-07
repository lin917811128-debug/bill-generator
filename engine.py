# engine.py
import pandas as pd
import csv
import json
import re
from openai import OpenAI

# ================= 配置大模型 =================
client = OpenAI(
    api_key="sk-a9ecbc8e94594507ad5942aa28c8aab8",  
    base_url="https://api.deepseek.com"
)

def ask_deepseek(prompt: str) -> str:
    """调用DeepSeek chat模型"""
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": "你是一个专业的工程造价师，擅长编写国标工程量清单。"},
            {"role": "user", "content": prompt}
        ],
        temperature=0.1,
        max_tokens=4000,
    )
    return response.choices[0].message.content

# ================= 批量生成清单 =================
def process_excel_with_ai(file_path: str, sheet_name: str = None) -> list:
    df = pd.read_excel(file_path, sheet_name=sheet_name, dtype=str)
    all_rows = []
    for idx, row in df.iterrows():
        cat = row.get('类别', '')
        name = row.get('名称', '')
        method = row.get('构造做法', '')
        scope = row.get('适用范围', '')
        remark = row.get('备注', '')
        if pd.isna(method) or method.strip() == '':
            continue
        all_rows.append({
            "类别": str(cat),
            "名称": str(name),
            "构造做法": str(method),
            "适用范围": str(scope) if not pd.isna(scope) else "",
            "备注": str(remark) if not pd.isna(remark) else ""
        })
    
    # 分批处理，每批最多20条，避免超出token限制
    batch_size = 20
    all_bills = []
    for i in range(0, len(all_rows), batch_size):
        batch = all_rows[i:i+batch_size]
        prompt = build_prompt(batch)
        result_text = ask_deepseek(prompt)
        bills = parse_ai_response(result_text)
        all_bills.extend(bills)
    return all_bills

def build_prompt(batch: list) -> str:
    """构造提示词，要求模型输出严格JSON"""
    input_data = json.dumps(batch, ensure_ascii=False, indent=2)
    prompt = f"""
根据以下建筑工程做法表，为每一行生成一个符合GB50500-2013的分部分项工程量清单项。
要求：
1. 项目编码必须严格遵循2013国标清单规范，同一类型做法编码一致，不同部位应区分。
2. 项目名称应体现关键参数：厚度、材料、强度等级、做法特征，不能重复。
3. 项目特征应按构造层次从下到上（或从上到下）逐项列出，每条前加序号。
4. 计量单位根据工程内容合理确定（m²,m³,m,t,个等）。
5. 工程量暂填1。
6. 备注注明来源（名称+适用范围）。
7. 如果做法中明确出现了“防水卷材”、“防水涂料”，必须使用“屋面及防水工程”章节编码。
8. 如果涉及混凝土，请默认采用“商品混凝土”，砂浆默认采用“干混砂浆”。
9. 最后，请匹配四川2020定额编号（例如AJ0023代表卷材防水，AE0005代表商品混凝土垫层）。在输出中增加“定额编号”字段。
10. 输出格式为纯JSON，不要包含任何其他文字，结构如下：
[
  {{
    "项目编码": "...",
    "项目名称": "...",
    "项目特征": "1. ...\\n2. ...",
    "计量单位": "...",
    "工程量": "1",
    "备注": "来源：...",
    "定额编号": ""
  }}
]

以下是做法表：
{input_data}
"""
    return prompt

def parse_ai_response(response_text: str) -> list:
    """解析AI返回的JSON"""
    try:
        # 清理可能的markdown标记
        json_str = re.sub(r'```json|```', '', response_text).strip()
        bills = json.loads(json_str)
        return bills
    except Exception as e:
        print("AI返回解析错误:", e)
        print("原始返回:", response_text)
        return []

def write_csv(bills, path):
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=["项目编码","项目名称","项目特征","计量单位","工程量","备注","定额编号"])
        writer.writeheader()
        writer.writerows(bills)