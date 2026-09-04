#!/usr/bin/env python3
"""
contract-validate.py
SCT 2.0 · P0-1 Contract 校验（确定性引擎，零外部依赖）

定位：acceptance.yaml 是「需求与测试之间的标准契约」，不能只是 `yaml.safe_load`
就读进来。本脚本在契约进入下游（design / run）之前做确定性校验：

  1. 结构校验（对齐 templates/acceptance-schema.json 的关键约束）
  2. ID 唯一性（features / scenarios / apis / rules 各自末段唯一）
  3. ID 格式（F{3位} / F{3位}-{序号} / API- / BR-）
  4. 契约完整性（每个 apis/rules/场景 是否具备可派生测试的字段）

三态输出（与 SCT 全局一致）：
  PASS      契约合法
  BLOCK     契约存在结构性错误（下游无法可靠派生测试）
  UNPROVEN  无法校验（文件不存在 / YAML 解析失败）

退出码：0=PASS  1=BLOCK  2=UNPROVEN
"""
import argparse
import json
import re
import sys
from pathlib import Path

PASS, BLOCK, UNPROVEN = "PASS", "BLOCK", "UNPROVEN"


def id_suffix(cid: str) -> str:
    """末段才是唯一区分段（同 feature 可有多个同前缀 ID）。"""
    return (cid or "").split("-")[-1].lower()


def validate(contract: dict) -> tuple:
    """→ (问题清单, 警告清单)；问题=BLOCK，警告=提示不阻断。"""
    problems, warnings = [], []

    if not isinstance(contract, dict):
        return [f"契约根节点必须是对象，实际 {type(contract).__name__}"], warnings

    # ---- 版本 ----
    version = contract.get("version")
    if version is None:
        problems.append("缺少 `version` 字段（当前契约版本为 1）")
    elif version != 1:
        problems.append(f"不支持的契约版本 {version}（本工具支持 1）")

    # ---- features / scenarios ----
    features = contract.get("features") or []
    seen_feat, seen_sc = {}, {}
    for i, feat in enumerate(features):
        fid = feat.get("id") if isinstance(feat, dict) else None
        if not fid:
            problems.append(f"features[{i}] 缺少 `id`")
            continue
        if not re.match(r"^F[0-9]{3}$", str(fid)):
            problems.append(f"features[{i}].id `{fid}` 格式应为 F{{3位序号}}（如 F001）")
        if fid in seen_feat:
            problems.append(f"features[].id 重复: `{fid}`（索引 {seen_feat[fid]} 与 {i}）")
        seen_feat[fid] = i
        for j, sc in enumerate(feat.get("acceptance_scenarios") or []):
            sid = sc.get("id") if isinstance(sc, dict) else None
            if not sid:
                problems.append(f"features[{i}].acceptance_scenarios[{j}] 缺少 `id`")
                continue
            if not re.match(r"^F[0-9]{3}-[0-9]+$", str(sid)):
                problems.append(f"场景 id `{sid}` 格式应为 F{{3位}}-{{序号}}（如 F001-1）")
            if sid in seen_sc:
                problems.append(f"acceptance_scenarios[].id 重复: `{sid}`")
            seen_sc[sid] = (i, j)
            for field in ("given", "when", "then"):
                if not sc.get(field):
                    warnings.append(f"场景 `{sid}` 缺少 `{field}`（e2e 案例将不完整）")

    # ---- apis ----
    apis = contract.get("apis") or []
    seen_api = {}
    for i, api in enumerate(apis):
        aid = api.get("id") if isinstance(api, dict) else None
        if not aid:
            problems.append(f"apis[{i}] 缺少 `id`")
            continue
        if not str(aid).startswith("API-"):
            problems.append(f"apis[{i}].id `{aid}` 应以 `API-` 开头")
        suffix = id_suffix(aid)
        if suffix in seen_api:
            problems.append(
                f"apis[].id 末段冲突: `{aid}` 与 `{seen_api[suffix]}` 同为 `{suffix}`"
                f"（末段决定生成文件名 test_api_{suffix}.py，必须唯一）")
        seen_api[suffix] = aid
        if not api.get("method"):
            problems.append(f"apis[{i}] (`{aid}`) 缺少 `method`")
        if not api.get("path"):
            problems.append(f"apis[{i}] (`{aid}`) 缺少 `path`")
        has_schema = bool(api.get("response_200") or api.get("response"))
        has_err = bool(api.get("error_codes") or api.get("errors"))
        if not has_schema and not has_err:
            warnings.append(f"接口 `{aid}` 既无响应 schema 也无异常码，派生不出断言")

    # ---- rules ----
    rules = contract.get("rules") or []
    seen_rule = {}
    for i, rule in enumerate(rules):
        rid = rule.get("id") if isinstance(rule, dict) else None
        if not rid:
            problems.append(f"rules[{i}] 缺少 `id`")
            continue
        if not str(rid).startswith("BR-"):
            problems.append(f"rules[{i}].id `{rid}` 应以 `BR-` 开头")
        suffix = id_suffix(rid)
        if suffix in seen_rule:
            problems.append(
                f"rules[].id 末段冲突: `{rid}` 与 `{seen_rule[suffix]}` 同为 `{suffix}`"
                f"（末段决定生成函数名 test_br_{suffix}，必须唯一）")
        seen_rule[suffix] = rid
        if not rule.get("text"):
            problems.append(f"rules[{i}] (`{rid}`) 缺少 `text`")
        if not rule.get("test_cases") and not rule.get("checks"):
            warnings.append(f"规则 `{rid}` 既无 `test_cases` 也无 `checks`，派生不出可执行单测")

    return problems, warnings


def main():
    p = argparse.ArgumentParser(description="SCT 2.0 Acceptance Contract 校验")
    p.add_argument("--contract", required=True, help="acceptance.yaml 路径")
    p.add_argument("--json", help="结构化结果输出路径（可选）")
    p.add_argument("--quiet", action="store_true", help="只输出结论行")
    args = p.parse_args()

    path = Path(args.contract)
    if not path.exists():
        print(f"{UNPROVEN}: 契约文件不存在: {path}")
        sys.exit(2)

    try:
        import yaml
        contract = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"{UNPROVEN}: 契约解析失败: {e}")
        sys.exit(2)

    problems, warnings = validate(contract or {})
    verdict = BLOCK if problems else PASS

    if not args.quiet:
        print("=" * 60)
        print("SCT Acceptance Contract 校验")
        print("=" * 60)
        print(f"契约: {path}")
        print(f"features: {len(contract.get('features') or [])}  "
              f"apis: {len(contract.get('apis') or [])}  "
              f"rules: {len(contract.get('rules') or [])}")
        if problems:
            print(f"\n❌ 结构性问题 {len(problems)} 处（下游无法可靠派生测试）:")
            for x in problems:
                print(f"  - {x}")
        if warnings:
            print(f"\n⚠️  完整性提示 {len(warnings)} 处（不阻断）:")
            for x in warnings:
                print(f"  - {x}")
        print("-" * 60)
    print(f"结论: {verdict}")

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps({
            "contract": str(path), "verdict": verdict,
            "problems": problems, "warnings": warnings,
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    sys.exit(0 if verdict == PASS else 1)


if __name__ == "__main__":
    main()
