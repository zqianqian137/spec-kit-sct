#!/usr/bin/env python3
"""
spec-merge.py
=============
SCT 工具 1：合并 spec.md / plan.md / data-model.md / api-contracts.md → acceptance.yaml (SoT)

归属：Speckit 扩展 `sct` 内置实现（v1.0-W2 / 自包含）
      本脚本是 SCT 工具 1 的自包含实现，安装 Speckit+本扩展后即可独立运行，
      运行时**不依赖**外部 `ai-test-platform/tools/`。
      ai-test-platform/tools/spec-merge.py 是同源代码的独立副本，逻辑完全等价。

W1 阶段只读 spec.md，提取 features + acceptance_scenarios。
W2+ 完整实现：
  - 读 plan.md 提取 api 列表
  - 读 data-model.md 提取 entities
  - 读 api-contracts.md 提取 apis[]
  - --ai 模式调 LLM 增强 edge_cases

用法（直接调）：
  python $SCT_EXT_HOME/scripts/spec-merge.py \\
    --spec specs/001-batch-import/spec.md \\
    --out specs/001-batch-import/acceptance.yaml

  # AI 模式（需要 SILICONFLOW_API_KEY）
  python $SCT_EXT_HOME/scripts/spec-merge.py \\
    --spec specs/001-batch-import/spec.md \\
    --out specs/001-batch-import/acceptance.yaml \\
    --ai

退出码：
  0 = 生成成功
  1 = spec.md 不存在
  2 = AI 模式但 API key 缺失
  3 = 生成失败
"""
import argparse
import os
import re
import sys
from pathlib import Path
from datetime import datetime

import yaml


def parse_args():
    p = argparse.ArgumentParser(
        description="工具 1：spec/plan/data-model/api-contracts → acceptance.yaml (SoT)"
    )
    p.add_argument("--spec", required=True, help="spec.md 路径")
    p.add_argument("--plan", help="plan.md 路径（可选，W1 不解析）")
    p.add_argument("--data-model", help="data-model.md 路径（可选，W1 不解析）")
    p.add_argument("--api-contracts", help="api-contracts.md 路径（可选，W1 不解析）")
    p.add_argument("--out", required=True, help="acceptance.yaml 输出路径")
    p.add_argument("--ai", action="store_true", help="AI 自动增强 edge_cases（需 SILICONFLOW_API_KEY）")
    p.add_argument("--api-key", help="LLM API key（默认读 SILICONFLOW_API_KEY 环境变量）")
    p.add_argument("--feature-id", help="手动指定 feature ID（默认从 spec.md 推断）")
    return p.parse_args()


def extract_features_from_spec(spec_text: str) -> list:
    """从 spec.md 提取 features 和 acceptance_scenarios

    解析规则（W1 demo）：
      - '## 功能' 或 '# 功能' 下的 H2 作为 feature
      - '### 用户故事' 或 H3 作为 acceptance_scenarios
      - bullet 形式: "- Given ... When ... Then ..."
    """
    features = []
    current_feature = None
    current_scenario = None

    lines = spec_text.splitlines()
    for raw in lines:
        line = raw.rstrip()
        stripped = line.strip()

        # 跳过空行
        if not stripped:
            continue

        # 标题
        if stripped.startswith("## ") and not stripped.startswith("### "):
            # 新的 feature
            if current_feature:
                if current_scenario:
                    current_feature["acceptance_scenarios"].append(current_scenario)
                    current_scenario = None
                features.append(current_feature)
            feat_name = stripped[3:].strip()
            current_feature = {
                "name": feat_name,
                "requirements": [],
                "acceptance_scenarios": [],
            }
        elif stripped.startswith("### ") and current_feature:
            # 新的 acceptance_scenario
            if current_scenario:
                current_feature["acceptance_scenarios"].append(current_scenario)
            sc_text = stripped[4:].strip()
            current_scenario = {
                "given": "",
                "when": "",
                "then": "",
                "_raw": sc_text,  # 暂存原始文本，AI 模式用
            }
        elif stripped.startswith("- ") and current_feature:
            content = stripped[2:].strip()
            if current_scenario is None:
                # 顶层 bullet → 需求
                current_feature["requirements"].append(content)
            elif content.lower().startswith("given "):
                current_scenario["given"] = content[6:].rstrip(":：")
            elif content.lower().startswith("when "):
                current_scenario["when"] = content[5:].rstrip(":：")
            elif content.lower().startswith("then "):
                current_scenario["then"] = content[5:].rstrip(":：")
            else:
                # 兜底：塞 when
                if not current_scenario["when"]:
                    current_scenario["when"] = content
                elif not current_scenario["then"]:
                    current_scenario["then"] = content

    # 收尾
    if current_feature:
        if current_scenario:
            current_feature["acceptance_scenarios"].append(current_scenario)
        features.append(current_feature)

    return features


def _split_kv(content: str):
    """把 '- key: value' / '- key：value' 拆成 (key, value)；非键值行返回 (None, None)"""
    content = content.strip()
    if content.startswith("- "):
        content = content[2:].strip()
    if ":" in content or "：" in content:
        sep = ":" if ":" in content else "："
        k, v = content.split(sep, 1)
        return k.strip(), v.strip()
    return None, None


def extract_apis_from_spec(spec_text: str) -> list:
    """从 spec.md 的 '## API/接口' 段解析 apis[]（结构对齐 acceptance-template.yaml）

    约定（与 acceptance-template.yaml 一致）：
      ## API 契约
      ### API-001 创建批量导入任务
      - method: POST
      - path: /api/batch-tasks
      - priority: P0                # 可选
      - spec_ref: specs/001/spec.md#批量导入   # 可选
      - success: 200                # 可选，默认 200
      - error: 400 fileName is required        # 可重复，每条一个异常
      - errors: 409 同名任务冲突; 400 缺字段     # 或单行多条
    """
    apis = []
    cur = None
    in_api = False

    def flush():
        nonlocal cur
        if cur is not None:
            apis.append(cur)
            cur = None

    for raw in spec_text.splitlines():
        stripped = raw.strip()
        if stripped.startswith("## "):
            head = stripped[3:].strip().lower()
            in_api = bool(re.match(r"^(api|接口)", head))
            flush()
            continue
        if not in_api:
            continue
        if stripped.startswith("### "):
            flush()
            title = stripped[4:].strip()
            m = re.match(r"(API-\d+)\s*(.*)", title)
            if m:
                cur = {
                    "id": m.group(1).upper(),
                    "name": m.group(2).strip() or title,
                    "method": "GET",
                    "path": "",
                    "response": {"success": {"status": 200}, "errors": []},
                }
            else:
                cur = None
            continue
        if cur is None:
            continue
        k, v = _split_kv(stripped)
        if not k:
            continue
        if k == "method":
            cur["method"] = v.upper()
        elif k == "path":
            cur["path"] = v
        elif k == "priority":
            cur["priority"] = v.upper()
        elif k == "spec_ref":
            cur["spec_ref"] = v
        elif k == "success":
            try:
                cur["response"]["success"]["status"] = int(v)
            except ValueError:
                pass
        elif k == "error":
            mm = re.match(r"(\d+)\s*(.*)", v)
            if mm:
                cur["response"]["errors"].append({
                    "status": int(mm.group(1)),
                    "condition": mm.group(2).strip() or "异常",
                    "message": mm.group(2).strip(),
                })
        elif k == "errors":
            for part in re.split(r"[;；]", v):
                mm = re.match(r"(\d+)\s*(.*)", part.strip())
                if mm:
                    cur["response"]["errors"].append({
                        "status": int(mm.group(1)),
                        "condition": mm.group(2).strip() or "异常",
                        "message": mm.group(2).strip(),
                    })
    flush()
    return [a for a in apis if a.get("path")]


def extract_rules_from_spec(spec_text: str) -> list:
    """从 spec.md 的 '## 业务规则/规则' 段解析 rules[]（对齐 acceptance-template.yaml）

    约定：
      ## 业务规则
      ### BR-001 单次导入不超过 1000 条用例
      - priority: P0          # 可选，默认 P2
      - derived_from: specs/001/spec.md#数据约束   # 可选
    """
    rules = []
    cur = None
    in_block = False

    def flush():
        nonlocal cur
        if cur is not None:
            rules.append(cur)
            cur = None

    for raw in spec_text.splitlines():
        stripped = raw.strip()
        if stripped.startswith("## "):
            head = stripped[3:].strip().lower()
            in_block = bool(re.match(r"(业务规则|规则|rules?|rule)", head))
            flush()
            continue
        if not in_block:
            continue
        if stripped.startswith("### "):
            flush()
            title = stripped[4:].strip()
            m = re.match(r"(BR-\d+)\s*(.*)", title)
            if m:
                cur = {
                    "id": m.group(1).upper(),
                    "text": m.group(2).strip() or title,
                    "priority": "P2",
                }
            else:
                cur = None
            continue
        if cur is None:
            continue
        k, v = _split_kv(stripped)
        if k == "priority":
            cur["priority"] = v.upper()
        elif k == "derived_from":
            cur["derived_from"] = v
    flush()
    return rules


def extract_from_doc_file(path: Path) -> dict:
    """从可选输入文件（api-contracts.md / plan.md / data-model.md）提取 apis/rules

    支持两种格式：
      - YAML：含顶层 apis:/rules: 键（直接采用）
      - Markdown：按 extract_apis_from_spec / extract_rules_from_spec 约定解析
    """
    text = path.read_text(encoding="utf-8")
    try:
        y = yaml.safe_load(text)
        if isinstance(y, dict) and (y.get("apis") or y.get("rules")):
            return {"apis": y.get("apis") or [], "rules": y.get("rules") or []}
    except yaml.YAMLError:
        pass
    return {
        "apis": extract_apis_from_spec(text),
        "rules": extract_rules_from_spec(text),
    }


def assign_scenario_ids(features: list) -> list:
    """给每个 scenario 分配 ID：F001-1, F001-2, F002-1, ....

    ID 生成规则：feature_index 从 0 开始 = 001
    """
    for feat_idx, feat in enumerate(features, start=1):
        feat["id"] = f"F{feat_idx:03d}"
        for sc_idx, sc in enumerate(feat["acceptance_scenarios"], start=1):
            sc["id"] = f"{feat['id']}-{sc_idx}"
            # 删除暂存字段
            sc.pop("_raw", None)
    return features


def ai_enhance_scenarios(features: list, api_key: str) -> list:
    """AI 模式：为每个 scenario 补充 edge_cases

    W1 demo：调 SiliconFlow（siliconflow.cn 提供的 Qwen2.5 等模型）。
    W1 空壳：如果 API key 不存在，输出空 edge_cases 并打印警告。
    """
    if not api_key:
        print("⚠️  --ai 模式但无 API key，跳过 edge_cases 增强（输出空列表）", file=sys.stderr)
        for feat in features:
            for sc in feat.get("acceptance_scenarios", []):
                sc["edge_cases"] = []
        return features

    # W2+ 真实实现
    try:
        import requests
    except ImportError:
        print("⚠️  缺少 requests 库，跳过 AI 增强", file=sys.stderr)
        for feat in features:
            for sc in feat.get("acceptance_scenarios", []):
                sc["edge_cases"] = []
        return features

    api_url = "https://api.siliconflow.cn/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    for feat in features:
        for sc in feat.get("acceptance_scenarios", []):
            prompt = f"""为以下验收场景生成 2-3 个边界用例（edge cases）。

场景：
  Given: {sc.get('given', '')}
  When: {sc.get('when', '')}
  Then: {sc.get('then', '')}

输出 YAML 格式（不要 ```yaml 包裹）：
- condition: <条件>
  expected: <预期>
"""
            try:
                resp = requests.post(
                    api_url,
                    headers=headers,
                    json={
                        "model": "Qwen/Qwen2.5-7B-Instruct",
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 500,
                        "temperature": 0.3,
                    },
                    timeout=30,
                )
                resp.raise_for_status()
                llm_output = resp.json()["choices"][0]["message"]["content"]
                edge_cases = yaml.safe_load(llm_output) or []
                if not isinstance(edge_cases, list):
                    edge_cases = []
                sc["edge_cases"] = edge_cases
            except Exception as e:
                print(f"⚠️  LLM 调用失败（{sc.get('id', '?')}）: {e}", file=sys.stderr)
                sc["edge_cases"] = []

    return features


def main():
    args = parse_args()

    spec_path = Path(args.spec)
    if not spec_path.exists():
        print(f"❌ spec.md 不存在: {spec_path}", file=sys.stderr)
        return 1

    spec_text = spec_path.read_text(encoding="utf-8")
    features = extract_features_from_spec(spec_text)

    if not features:
        print(f"⚠️  spec.md 未解析出任何 feature（需要 '## 标题' 格式）", file=sys.stderr)
        return 3

    features = assign_scenario_ids(features)

    # ---- C2 修复：合并 apis / rules（来源：spec.md 段 + 可选输入文件）----
    apis = extract_apis_from_spec(spec_text)
    rules = extract_rules_from_spec(spec_text)
    for src in (args.api_contracts, args.plan, args.data_model):
        if src and Path(src).exists():
            extra = extract_from_doc_file(Path(src))
            apis.extend(extra.get("apis") or [])
            rules.extend(extra.get("rules") or [])
    # 按 id 去重
    seen_a, merged_apis = set(), []
    for a in apis:
        if a.get("id") and a["id"] not in seen_a:
            seen_a.add(a["id"])
            merged_apis.append(a)
    seen_r, merged_rules = set(), []
    for r in rules:
        if r.get("id") and r["id"] not in seen_r:
            seen_r.add(r["id"])
            merged_rules.append(r)
    apis, rules = merged_apis, merged_rules
    if not apis and not rules:
        print("⚠️  未解析出 apis/rules（如需接口/规则测试，请在 spec.md 增加 "
              "'## API 契约' / '## 业务规则' 段，或提供 --api-contracts/--plan/--data-model）",
              file=sys.stderr)

    # AI 增强
    api_key = args.api_key or os.environ.get("SILICONFLOW_API_KEY")
    if args.ai:
        features = ai_enhance_scenarios(features, api_key)
    else:
        for feat in features:
            for sc in feat.get("acceptance_scenarios", []):
                sc["edge_cases"] = []

    # 写 yaml
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    doc = {
        "_meta": {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "source_spec": str(spec_path),
            "tool": "spec-merge.py",
            "tool_home": "speckit-extension:sct/scripts/spec-merge.py",
            "version": "1.0-W2-INTERNAL",
            "ai_enhanced": args.ai,
        },
        "features": features,
    }
    if apis:
        doc["apis"] = apis
    if rules:
        doc["rules"] = rules

    with open(out_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(doc, f, allow_unicode=True, sort_keys=False, indent=2)

    # 摘要
    total_scenarios = sum(len(f["acceptance_scenarios"]) for f in features)
    total_edge_cases = sum(
        len(sc.get("edge_cases", []))
        for f in features
        for sc in f["acceptance_scenarios"]
    )
    print(f"✅ 生成 {out_path}")
    print(f"   - {len(features)} features")
    print(f"   - {total_scenarios} acceptance_scenarios")
    print(f"   - {len(apis)} apis / {len(rules)} rules")
    print(f"   - {total_edge_cases} edge_cases (AI 模式)" if args.ai else f"   - 0 edge_cases (默认模式)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
