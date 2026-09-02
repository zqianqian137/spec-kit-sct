#!/usr/bin/env python3
"""
verification-gate.py
SCT 工具 6：测试有效性验证门（诚实三态：PASS / BLOCK / UNPROVEN）

归属：Speckit 扩展 `sct` 内置实现（v1.1.0）

弥补 SCT 的实质缺口：sct.check 回答"测试有没有、覆盖到没有"，
本门回答"**这些测试真能抓住 bug 吗**"——即测试**有效性**验证。

四项检查：
  1. PHANTOM_TASK  幻影任务：tasks.md 标 [X] 但代码中找不到实现证据
                   （与 sct.check 的 MISSING_IMPL 反向互补：那里查
                     "SoT 定义了代码没做"，这里查"声称做了实际没做"）
  2. COMPILE       编译门：测试代码能否真正编译（mvn / gradle）
  3. REAL_TESTS    真实测试计数：从 surefire/junit 报告读**实际执行**的测试数，
                   防止"声称有测试、实际 0 个"（Vurnix 诚实门思路）
  4. MUTATION      变异强度（可选）：PITest mutations.xml 变异得分，
                   低于阈值说明测试抓不住注入的缺陷

三态语义（关键设计：不允许"没验证"冒充"验证通过"）：
  PASS      四项检查全部通过
  BLOCK     发现幻影 / 编译失败 / 真实测试为 0 / 变异得分低于阈值
  UNPROVEN  无法验证（缺工具、缺环境、缺报告）—— 明确提示，不静默放行

退出码：0=PASS  1=BLOCK  2=UNPROVEN

用法：
  python $SCT_EXT_HOME/scripts/verification-gate.py \\
    --spec specs/001-xxx/acceptance.yaml \\
    --code backend/src/main/java \\
    --tests tests/generated/ \\
    --tasks specs/001-xxx/tasks.md \\
    --surefire backend/target/surefire-reports \\
    --report specs/001-xxx/reports/verification.md

  # 可选增强：变异测试（PITest 报告）
  python ... --mutation backend/target/pit-reports/mutations.xml --mutation-threshold 60

  # 内网无 Maven/无构建环境时跳过编译门
  python ... --skip-compile
"""
import argparse
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

import yaml

PASS, BLOCK, UNPROVEN = "PASS", "BLOCK", "UNPROVEN"
# 严重度排序：BLOCK 最严，UNPROVEN 次之（不静默当通过），PASS 最轻
_RANK = {PASS: 0, UNPROVEN: 1, BLOCK: 2}


def _worst(statuses: list) -> str:
    """整体状态取最严：BLOCK > UNPROVEN > PASS"""
    return max(statuses, key=lambda s: _RANK.get(s, 0)) if statuses else PASS


def load_acceptance(spec_path: Path) -> dict:
    with open(spec_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


# =====================================================================
# 1. 幻影任务检测：tasks.md 标 [X] 但代码中无实现证据
# =====================================================================

def _evidence_tokens(text: str) -> list:
    """从任务描述提取可作为"实现证据"的 token：
    大驼峰类名(FooService)、方法调用(calculate())、全大写常量(MAX_SIZE)"""
    toks = []
    toks += re.findall(r"\b[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+\b", text)      # FooService
    toks += re.findall(r"\b([a-z][a-zA-Z0-9]*)\s*\(", text)                  # calculate()
    toks += re.findall(r"\b[A-Z][A-Z0-9_]{2,}\b", text)                      # MAX_SIZE
    # 去噪：过滤太通用/太短的词
    noise = {"set", "get", "is", "to", "of", "in", "on", "for", "and", "the",
             "with", "from", "that", "this", "add", "new", "use"}
    seen, out = set(), []
    for t in toks:
        tl = t.lower()
        if len(t) < 3 or tl in noise or t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out


def _build_corpus(roots: list) -> str:
    """把代码根下所有 .java 拼成一个检索语料（规模可控，逐文件搜索太慢）"""
    parts = []
    for root in roots:
        if not root or not Path(root).exists():
            continue
        p = Path(root)
        files = list(p.rglob("*.java")) if p.is_dir() else [p]
        for f in files:
            try:
                parts.append(f.read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                continue
    return "\n".join(parts)


def check_phantom_tasks(tasks_path: str | None, code_root: str, test_root: str) -> tuple:
    """解析 tasks.md 中标记完成的任务，在代码中找实现证据；找不到 = 幻影"""
    if not tasks_path or not Path(tasks_path).exists():
        return UNPROVEN, [], "未提供 tasks.md（--tasks），无法做幻影检测"

    corpus = _build_corpus([code_root, test_root])
    if not corpus.strip():
        return UNPROVEN, [], "代码/测试目录为空或不可读，无法做幻影检测"

    findings = []
    done_count = 0
    for line in Path(tasks_path).read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\s*[-*]\s*\[([xX])\]\s+(.*)$", line)
        if not m:
            continue
        done_count += 1
        desc = m.group(2).strip()
        toks = _evidence_tokens(desc)
        if not toks:
            continue  # 描述里没有可检索的类名/方法名，不做判断（避免误报）
        hit = [t for t in toks if t in corpus]
        if not hit:
            findings.append({
                "task": desc[:120],
                "tokens": toks[:5],
            })

    if not done_count:
        return UNPROVEN, [], "tasks.md 中未找到已完成（[X]）任务"
    if findings:
        return BLOCK, findings, f"{len(findings)}/{done_count} 个已完成任务在代码中无实现证据（幻影）"
    return PASS, findings, f"{done_count} 个已完成任务均有代码证据"


# =====================================================================
# 2. 编译门：测试代码能否真正编译
# =====================================================================

def check_compile(code_root: str, timeout: int = 300) -> tuple:
    """检测 maven / gradle 构建文件并执行测试编译

    注意：内网无构建环境时无法验证 → 返回 UNPROVEN（不冒充通过）。
    """
    root = Path(code_root)
    if not root.exists():
        return UNPROVEN, "代码目录不存在，无法编译验证"

    # 向上找构建文件（code_root 常是 backend/src/main/java）
    build_dir, build_kind = None, None
    for cand in [root, *root.parents]:
        if (cand / "pom.xml").exists():
            build_dir, build_kind = cand, "maven"
            break
        if (cand / "build.gradle").exists() or (cand / "build.gradle.kts").exists():
            build_dir, build_kind = cand, "gradle"
            break
    if not build_dir:
        return UNPROVEN, "未找到 pom.xml / build.gradle，无法编译验证（可用 --skip-compile 跳过）"

    cmd = (["mvn", "-q", "-DskipTests", "test-compile"] if build_kind == "maven"
           else ["gradle", "compileTestJava", "compileJava", "-q"])
    try:
        proc = subprocess.run(cmd, cwd=str(build_dir), capture_output=True,
                              text=True, timeout=timeout, shell=False)
    except FileNotFoundError:
        return UNPROVEN, f"未安装 {'mvn' if build_kind == 'maven' else 'gradle'}，无法编译验证（可用 --skip-compile 跳过）"
    except subprocess.TimeoutExpired:
        return UNPROVEN, f"编译超时（{timeout}s），无法判定（可用 --skip-compile 跳过）"

    if proc.returncode == 0:
        return PASS, f"{build_kind} 测试编译通过"
    tail = (proc.stdout or "")[-800:] + (proc.stderr or "")[-800:]
    return BLOCK, f"{build_kind} 测试编译失败（exit={proc.returncode}）：\n{tail}"


# =====================================================================
# 3. 真实测试计数：从 surefire / junit 报告读实际执行数
# =====================================================================

def check_real_tests(surefire_dir: str | None) -> tuple:
    """读取 surefire-reports 下 TEST-*.xml，统计真实执行的测试数"""
    if not surefire_dir:
        return UNPROVEN, 0, "未提供 --surefire 报告目录，无法验证真实测试数"
    d = Path(surefire_dir)
    if not d.exists():
        return UNPROVEN, 0, f"surefire 报告目录不存在：{surefire_dir}"

    xmls = list(d.rglob("TEST-*.xml"))
    if not xmls:
        return UNPROVEN, 0, "surefire 报告目录中没有 TEST-*.xml"

    totals = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    for x in xmls:
        try:
            r = ET.parse(x).getroot()
        except Exception:
            continue
        for k in totals:
            try:
                totals[k] += int(r.get(k) or 0)
            except ValueError:
                pass

    if totals["tests"] == 0:
        return BLOCK, 0, "surefire 报告中实际执行测试数为 0（声称有测试但未真正执行）"
    if totals["failures"] or totals["errors"]:
        return BLOCK, totals["tests"], (f"实际执行 {totals['tests']} 个测试，"
                                        f"其中失败 {totals['failures']} / 错误 {totals['errors']}")
    return PASS, totals["tests"], (f"实际执行 {totals['tests']} 个测试，全部通过"
                                   f"（跳过 {totals['skipped']}）")


# =====================================================================
# 4. 变异强度（可选）：PITest 变异得分
# =====================================================================

def check_mutation(mutation_path: str | None, threshold: float,
                   manual_score: float | None = None) -> tuple:
    """PITest mutations.xml → 变异得分；低于阈值说明测试抓不住注入缺陷

    未提供报告 → UNPROVEN（变异测试是可选增强，不强制）。
    """
    if manual_score is not None:
        score = manual_score
        src = "（由 --mutation-score 直接提供，如 mutmut / 自研工具结果）"
    elif mutation_path and Path(mutation_path).exists():
        try:
            root = ET.parse(mutation_path).getroot()
        except Exception as e:
            return UNPROVEN, None, f"变异报告解析失败：{e}"
        muts = root.findall(".//mutation")
        if not muts:
            return UNPROVEN, None, "变异报告中没有 mutation 条目"
        killed = sum(1 for m in muts if (m.get("detected") or "").lower() == "true")
        score = killed / len(muts) * 100
        src = f"（PITest：{killed}/{len(muts)} 个变异体被测试杀死）"
    else:
        return UNPROVEN, None, "未提供变异报告（--mutation / --mutation-score）；该检查为可选增强"

    if score < threshold:
        return BLOCK, score, (f"变异得分 {score:.1f}% 低于阈值 {threshold}%——"
                              f"测试未能抓住注入的缺陷 {src}")
    return PASS, score, f"变异得分 {score:.1f}%（阈值 {threshold}%）{src}"


# =====================================================================
# 报告渲染
# =====================================================================

def render_report(spec_path: str, checks: list, overall: str, meta: dict) -> str:
    L = ["# SCT 测试有效性验证报告（verification gate）", ""]
    L.append(f"**Generated**: {datetime.now().isoformat(timespec='seconds')}  ")
    L.append(f"**SoT**: `{spec_path}`  ")
    L.append(f"**结论**: **{overall}**")
    L.append("")
    L.append("> 三态语义：`PASS`=通过；`BLOCK`=发现幻影/编译失败/测试未真正执行/变异得分不足；"
             "`UNPROVEN`=**无法验证**（缺工具或环境）——不冒充通过，需人工确认或补齐环境。")
    L.append("")
    L.append("| 检查项 | 结果 | 说明 |")
    L.append("|--------|------|------|")
    for c in checks:
        L.append(f"| {c['name']} | **{c['status']}** | {c['detail']} |")
    L.append("")

    for name, items in meta.items():
        if not items:
            continue
        L.append(f"## {name}")
        L.append("")
        if name == "幻影任务明细":
            L.append("| 已完成任务 | 未找到证据的 token |")
            L.append("|------------|-------------------|")
            for it in items:
                L.append(f"| {it['task']} | {', '.join(it['tokens'])} |")
        else:
            for it in items:
                L.append(f"- {it}")
        L.append("")

    L.append("## 门禁建议")
    L.append("")
    if overall == BLOCK:
        L.append("- ❌ **阻断**：存在有效性问题，修复后再进入下一阶段。")
        L.append("- 幻影任务 → 补实现，或把 tasks.md 的 `[X]` 改回 `[ ]`（诚实标注未完成）。")
        L.append("- 编译失败 / 测试未执行 → 先让测试真正跑起来。")
        L.append("- 变异得分低 → 加强断言（断言期望仍须来自 SoT，不得迎合代码）。")
    elif overall == UNPROVEN:
        L.append("- ⚠️ **未验证**：不构成通过。补齐工具/环境后重跑，或人工确认风险可接受。")
        L.append("- 内网环境常见：无 Maven/Gradle → `--skip-compile`；无 surefire 报告 → 先执行测试。")
    else:
        L.append("- ✅ 通过：测试不仅存在，而且能编译、能真正执行、能抓住注入的缺陷。")
    return "\n".join(L)


def main():
    p = argparse.ArgumentParser(
        description="SCT 测试有效性验证门（三态：PASS / BLOCK / UNPROVEN）")
    p.add_argument("--spec", required=True, help="acceptance.yaml 路径")
    p.add_argument("--code", default="backend/src/main/java", help="源码根目录")
    p.add_argument("--tests", default="tests/generated", help="测试目录")
    p.add_argument("--tasks", help="tasks.md 路径（幻影检测数据源）")
    p.add_argument("--surefire", help="surefire-reports 目录（真实测试计数）")
    p.add_argument("--mutation", help="PITest mutations.xml 路径（可选）")
    p.add_argument("--mutation-score", type=float,
                   help="直接提供变异得分（mutmut 等无 XML 报告时用）")
    p.add_argument("--mutation-threshold", type=float, default=60.0,
                   help="变异得分门禁阈值（%%），默认 60")
    p.add_argument("--skip-compile", action="store_true", help="跳过编译门")
    p.add_argument("--skip-mutation", action="store_true", help="跳过变异检查")
    p.add_argument("--compile-timeout", type=int, default=300, help="编译超时（秒），默认 300")
    p.add_argument("--report", help="验证报告输出路径（markdown）")
    args = p.parse_args()

    spec = load_acceptance(Path(args.spec))
    phantom_items, compile_detail, mutation_detail = [], "", ""

    # 1. 幻影任务
    st_task, items, detail_task = check_phantom_tasks(args.tasks, args.code, args.tests)
    if items:
        phantom_items = items
    checks = [{"name": "PHANTOM_TASK 幻影任务检测", "status": st_task, "detail": detail_task}]

    # 2. 编译门
    if args.skip_compile:
        checks.append({"name": "COMPILE 编译门", "status": UNPROVEN,
                       "detail": "已通过 --skip-compile 跳过"})
    else:
        st_compile, compile_detail = check_compile(args.code, args.compile_timeout)
        checks.append({"name": "COMPILE 编译门", "status": st_compile,
                       "detail": compile_detail.replace("\n", " ")[:500]})

    # 3. 真实测试计数
    st_tests, real_count, detail_tests = check_real_tests(args.surefire)
    checks.append({"name": "REAL_TESTS 真实测试计数", "status": st_tests, "detail": detail_tests})

    # 4. 变异强度（可选）
    if args.skip_mutation:
        checks.append({"name": "MUTATION 变异强度", "status": UNPROVEN,
                       "detail": "已通过 --skip-mutation 跳过"})
    else:
        st_mut, score, mutation_detail = check_mutation(
            args.mutation, args.mutation_threshold, args.mutation_score)
        checks.append({"name": "MUTATION 变异强度", "status": st_mut, "detail": mutation_detail})

    overall = _worst([c["status"] for c in checks])

    print("=" * 60)
    print("SCT 测试有效性验证门（verification gate）")
    print("=" * 60)
    for c in checks:
        mark = {PASS: "✅", BLOCK: "❌", UNPROVEN: "⚠️ "}.get(c["status"], "  ")
        print(f"{mark} {c['name']}: {c['status']}")
        print(f"    {c['detail'][:200]}")
    print("-" * 60)
    print(f"结论: {overall}")
    if overall == UNPROVEN:
        print("      （未验证 ≠ 通过：补齐工具/环境后重跑，或人工确认风险）")
    print("=" * 60)

    if args.report:
        meta = {"幻影任务明细": phantom_items}
        if st_compile == BLOCK:
            meta["编译错误"] = [compile_detail[-1500:]]
        rp = Path(args.report)
        rp.parent.mkdir(parents=True, exist_ok=True)
        rp.write_text(render_report(args.spec, checks, overall, meta), encoding="utf-8")
        print(f"📄 详细报告: {rp}")

    sys.exit({"PASS": 0, "BLOCK": 1, "UNPROVEN": 2}[overall])


if __name__ == "__main__":
    main()
