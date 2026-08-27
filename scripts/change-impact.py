#!/usr/bin/env python3
"""
change-impact.py
================
SCT 工具 4：git diff + acceptance.yaml → change-impact.md（含 P0/P1/P2 场景列表）

归属：Speckit 扩展 `sct` 内置实现（v1.0-W2 / 自包含）

W1 阶段：
  1. 拿 git diff 的文件清单
  2. 简单匹配 acceptance.yaml 中的 features
  3. 全量输出 P0 场景（保守）
  4. W2+ 实现 4 维度匹配（API/UI/Rule/Scenario）+ 优先级评分

用法：
  python $SCT_EXT_HOME/scripts/change-impact.py \\
    --spec specs/001-batch-import/acceptance.yaml \\
    --base main \\
    --head HEAD \\
    --out change-impact.md

  # 仅看 staged
  python $SCT_EXT_HOME/scripts/change-impact.py --spec ... --out change-impact.md --staged

退出码：
  0 = 报告生成
  1 = 无变更
  2 = SoT 缺失
"""
import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import yaml


def parse_args():
    p = argparse.ArgumentParser(description="工具 4：git diff → change-impact.md")
    p.add_argument("--spec", required=True, help="acceptance.yaml 路径")
    p.add_argument("--base", default="main", help="git base ref")
    p.add_argument("--head", default="HEAD", help="git head ref")
    p.add_argument("--out", default="change-impact.md", help="报告输出")
    p.add_argument("--staged", action="store_true", help="仅看 staged（与 --base/--head 互斥）")
    p.add_argument("--config", help="YAML 配置（4 维度匹配规则，W2 实现）")
    return p.parse_args()


def git_diff_files(base: str, head: str, staged: bool = False) -> list:
    """返回变更文件列表（相对路径）"""
    if staged:
        cmd = ["git", "diff", "--cached", "--name-only"]
    else:
        cmd = ["git", "diff", "--name-only", base, head]

    try:
        out = subprocess.check_output(cmd, text=True, encoding="utf-8", stderr=subprocess.PIPE)
        files = [f.strip() for f in out.splitlines() if f.strip()]
        return files
    except subprocess.CalledProcessError as e:
        # 可能是新分支无 base，或者仓库无 git
        print(f"⚠️  git diff 失败: {e.stderr.strip()}", file=sys.stderr)
        return []


def load_spec(spec_path: Path) -> dict:
    with open(spec_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def classify_changed_files(files: list) -> dict:
    """W1 demo：简单分类变更文件"""
    buckets = {
        "api": [],      # 后端接口
        "ui": [],       # 前端组件
        "service": [],  # service 层
        "test": [],     # 测试
        "config": [],   # 配置
        "other": [],
    }
    for f in files:
        if "Controller" in f or "/controller/" in f:
            buckets["api"].append(f)
        elif "Service" in f or "/service/" in f:
            buckets["service"].append(f)
        elif "frontend/" in f or "src/views/" in f or "src/components/" in f:
            buckets["ui"].append(f)
        elif "Test" in f or "/test/" in f or "__tests__" in f or "spec.js" in f:
            buckets["test"].append(f)
        elif "config" in f or "yml" in f or "yaml" in f or "json" in f:
            buckets["config"].append(f)
        else:
            buckets["other"].append(f)
    return buckets


def score_scenarios(scenarios: list, buckets: dict, spec: dict) -> list:
    """W1 demo：保守算法 - 任何后端/前端变更 → 全量 P0 跑

    W2 算法（4 维度）：
      score = (api_count*10 + rule_count*8 + ui_count*5 + e2e_count*3) * priority_weight
      score ≥ 30 → P0
      score 15-29 → P1
      score 5-14 → P2
    """
    has_api_change = bool(buckets["api"])
    has_service_change = bool(buckets["service"])
    has_ui_change = bool(buckets["ui"])
    has_test_change = bool(buckets["test"])

    # W1 保守策略
    if has_api_change or has_service_change:
        # 任何后端/服务层变更 → 全 P0 跑
        return [(s, "P0") for s in scenarios]
    elif has_ui_change:
        # 前端变更 → P0 + P1
        return [(s, "P0" if idx < 2 else "P1") for idx, s in enumerate(scenarios)]
    elif has_test_change:
        # 仅测试变更 → 跳过（不需要回归）
        return [(s, "P2") for s in scenarios]
    else:
        # 其他变更 → P1 中等
        return [(s, "P1") for s in scenarios]


def collect_all_scenarios(spec: dict) -> list:
    """拍平所有 features[].acceptance_scenarios 为 list"""
    out = []
    for feat in spec.get("features", []):
        for sc in feat.get("acceptance_scenarios", []):
            out.append({
                "id": sc.get("id", "?"),
                "given": sc.get("given", ""),
                "when": sc.get("when", ""),
                "then": sc.get("then", ""),
                "feature_id": feat.get("id", "?"),
                "feature_name": feat.get("name", ""),
            })
    return out


def decide_change_level(buckets: dict) -> tuple:
    """由变更文件类型推断变更级别（对齐 change-impact-template.md）

    返回 (级别 'L1'/'L2'/'L3', 理由)：
      L3 大改：涉及后端接口/服务层 → 完整 SOP + e2e
      L2 中改：涉及前端           → 定向 codegen + check
      L1 小改：仅测试/配置/其它   → 存量回归即可（跳过实现需求契约）
    """
    if buckets["api"] or buckets["service"]:
        return "L3", "涉及后端接口/服务层变更，需完整 SOP + e2e 回归"
    if buckets["ui"]:
        return "L2", "涉及前端变更，需定向 codegen + check"
    return "L1", "仅测试/配置/其它变更，存量回归即可"


def render_report(scenarios_with_pri: list, buckets: dict, spec: dict,
                  level: str = "L3", level_reason: str = "") -> str:
    """生成 change-impact.md"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total = len(scenarios_with_pri)
    p0_count = sum(1 for _, p in scenarios_with_pri if p == "P0")
    p1_count = sum(1 for _, p in scenarios_with_pri if p == "P1")
    p2_count = sum(1 for _, p in scenarios_with_pri if p == "P2")

    lines = []
    lines.append("# Change Impact Report")
    lines.append("")
    lines.append(f"**Date**: {now}  ")
    lines.append(f"**SoT**: `{spec.get('_meta', {}).get('source_spec', '?')}`  ")
    lines.append(f"**Tool**: change-impact.py v1.0-W2-INTERNAL")
    lines.append(f"**变更级别**: {level}（{level_reason}）")
    lines.append("")

    # Summary
    lines.append("## 📊 Summary")
    lines.append("")
    lines.append("| Priority | Count |")
    lines.append("|----------|-------|")
    lines.append(f"| **P0**   | **{p0_count}** |")
    lines.append(f"| P1       | {p1_count} |")
    lines.append(f"| P2       | {p2_count} |")
    lines.append(f"| **Total**| **{total}** |")
    lines.append("")

    # Changed files
    lines.append("## 📁 Changed Files")
    lines.append("")
    lines.append("| Type | File |")
    lines.append("|------|------|")
    for typ, files in buckets.items():
        for f in files:
            lines.append(f"| {typ} | `{f}` |")
    if not any(buckets.values()):
        lines.append("| (无) | (无变更) |")
    lines.append("")

    # 实现需求（Spec→Code 契约）：L1 小改跳过本节（无 SoT 变更）
    if level != "L1":
        lines.append("## 📋 实现需求（Spec→Code 契约，implement 照此单实现）")
        lines.append("")
        lines.append("> 从 SoT (acceptance.yaml) 范围原文转录，是实现阶段的输入契约。")
        lines.append("> 实现完成时逐条勾选（[ ]→[x]）。")
        lines.append("")
        # APIs
        lines.append("### APIs")
        lines.append("")
        spec_apis = spec.get("apis", []) or []
        if spec_apis:
            for a in spec_apis:
                line = f"- [ ] **{a.get('id', '?')} {a.get('name', '')}** `{a.get('method', '')} {a.get('path', '')}`"
                req = a.get("request") or {}
                body = req.get("body") if isinstance(req, dict) else None
                if body:
                    fields = "、".join(
                        f"`{f.get('name', '')}`" + ("*" if f.get("required") else "")
                        for f in body if isinstance(f, dict)
                    )
                    if fields:
                        line += f"  - 请求：{fields}"
                succ = (a.get("response") or {}).get("success") or {}
                if succ:
                    line += f"  - 成功：{succ.get('status', 200)}"
                errs = (a.get("response") or {}).get("errors") or []
                if errs:
                    line += "  - 异常：" + "；".join(
                        f"{e.get('status', '?')} {e.get('message') or e.get('condition', '')}" for e in errs
                    )
                lines.append(line)
        else:
            lines.append("- （SoT 未登记 apis）")
        lines.append("")
        # Rules
        lines.append("### Rules")
        lines.append("")
        spec_rules = spec.get("rules", []) or []
        if spec_rules:
            for r in spec_rules:
                lines.append(f"- [ ] **{r.get('id', '?')}**：{r.get('text', '')}")
        else:
            lines.append("- （SoT 未登记 rules）")
        lines.append("")
        # Scenarios (P0/P1)
        lines.append("### Scenarios")
        lines.append("")
        for sc, pri in scenarios_with_pri:
            if pri == "P2":
                continue
            lines.append(f"- [ ] **{sc['id']}**：{sc.get('given', '')} → {sc.get('when', '')} → {sc.get('then', '')}")
        lines.append("")

    # Scenarios
    lines.append("## 🎯 Recommended E2E Scenarios")
    lines.append("")
    lines.append("| Priority | Scenario | Description | Match Rule |")
    lines.append("|----------|----------|-------------|------------|")
    for sc, pri in scenarios_with_pri:
        desc = f"{sc.get('when', '')[:30]} → {sc.get('then', '')[:30]}"
        match = "W1 保守匹配（W2 实现 4 维度）"
        marker = "**" if pri == "P0" else ""
        lines.append(
            f"| {marker}{pri}{marker} | {sc['id']} | {desc} | {match} |"
        )
    lines.append("")

    # Risk
    lines.append("## ⚠️ Risk Zones (W1 提示)")
    lines.append("")
    if buckets["api"]:
        lines.append(f"- **{len(buckets['api'])} 个 API 文件变更** - 影响范围最大")
    if buckets["service"]:
        lines.append(f"- **{len(buckets['service'])} 个 service 文件变更** - 业务规则可能漂移")
    if buckets["ui"]:
        lines.append(f"- **{len(buckets['ui'])} 个前端文件变更** - UI 状态机可能有隐藏 bug")
    if not any(buckets.values()):
        lines.append("- 无显著变更")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("> W1 阶段：保守匹配所有 scenario 为 P0/P1。")
    lines.append("> W2 计划：实现 SCT §18 4 维度匹配算法（API/UI/Rule/Scenario）。")
    lines.append("")

    return "\n".join(lines)


def main():
    args = parse_args()

    # 1. 拿 diff
    files = git_diff_files(args.base, args.head, staged=args.staged)
    if not files:
        print(f"⚠️  无变更（base={args.base} head={args.head} staged={args.staged}）", file=sys.stderr)
        # W1：仍生成空报告
        files = []

    # 2. 分类
    buckets = classify_changed_files(files)

    # 3. 读 SoT
    spec_path = Path(args.spec)
    if not spec_path.exists():
        print(f"❌ SoT 不存在: {spec_path}", file=sys.stderr)
        return 2
    spec = load_spec(spec_path)

    # 4. 评分
    scenarios = collect_all_scenarios(spec)
    scenarios_with_pri = score_scenarios(scenarios, buckets, spec)

    # 5. 变更级别（H1 修复：写入 **变更级别** 行，下游命令据此短路）
    level, level_reason = decide_change_level(buckets)

    # 6. 渲染
    report = render_report(scenarios_with_pri, buckets, spec, level, level_reason)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")

    p0 = sum(1 for _, p in scenarios_with_pri if p == "P0")
    p1 = sum(1 for _, p in scenarios_with_pri if p == "P1")
    print(f"✅ 生成 {out_path}")
    print(f"   - {len(files)} 变更文件")
    print(f"   - {p0} P0 + {p1} P1 场景需回归")
    return 0


if __name__ == "__main__":
    sys.exit(main())
