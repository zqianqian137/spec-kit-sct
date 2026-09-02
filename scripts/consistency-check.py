"""
consistency-check.py
====================
SCT 工具 3：三方一致性校验 + 详细测试报告生成

归属：Speckit 扩展 `sct` 内置实现（v1.0-W2 / 自包含）

检测场景：
1. spec 定义了接口，但 code 没实现 → 漂移
2. code 实现了接口，但 spec 没定义 → 漂移
3. test 没覆盖 spec 的验收场景 → 漂移
4. test 引用了 code 中不存在的字段 → 漂移
5. test 案例缺失「真相意图说明」（[意图]/Given/When/Then）→ 漂移（MISSING_INTENT）

测试报告（--report 落盘，模板：templates/consistency-report-template.md）：
  - JaCoCo 覆盖率：方法/行/指令，总体 + 增量（--jacoco + --base）
  - 接口测试覆盖与执行情况：测了多少个、案例数、通过/失败/跳过（--junit）
  - 业务规则验证情况
  - 改动点审查表（--impact：change-impact.md 的 P0/P1 场景 × 执行结果）

用法：
    python $SCT_EXT_HOME/scripts/consistency-check.py \\
        --spec specs/001-batch-import/acceptance.yaml \\
        --code backend/src/main/java \\
        --tests tests/generated/ \\
        --jacoco backend/target/site/jacoco/jacoco.xml \\
        --junit tests/generated/junit-report.xml \\
        --impact change-impact.md \\
        --base main \\
        --report specs/001-batch-import/reports/test-report.md

覆盖模式（--mode 覆盖，缺省读 SoT _meta.coverage_mode，最终默认 full）：
  full        全量：SoT 应覆盖扫描范围内全部接口（新项目 / 模块整体重构）
  incremental 增量：存量项目不做全量补测——SoT 只登记本次变更范围，
              存量未登记代码不报 UNSPEC_API；门禁 = SoT 范围内
              API/规则覆盖 100% + 增量行覆盖率 ≥ 80%（全量覆盖率仅供参考）

junit 报告生成方式：
    pytest tests/generated/ --junitxml=tests/generated/junit-report.xml

CodeGraph 整合：
    acceptance-codegen.py --codegraph 会落盘 tests/generated/_codegen_meta.json
    （API 实现标注 + FIELD_DRIFT + 派生异常用例数 + 系统级异常清单）。
    本脚本自动发现（或 --codegen-meta 指定），把生成测试文件头部标注与
    字段级漂移整合进测试报告：
    头部 CodeGraph 状态 / 3.2 实现列与「其中派生异常」列 /
    6.2 FIELD_DRIFT 节 / 6.3 系统级异常清单节 / 第 7 节结论汇总。

退出码：
  0 = 校验通过（无 HIGH 漂移）
  1 = 存在 HIGH 级别漂移
"""
import yaml
import argparse
import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Set, Tuple

# JaCoCo 计数器类型 → 中文名（只取报告关注的三个维度）
JACOCO_TYPES = [("INSTRUCTION", "指令 (INSTRUCTION)"), ("LINE", "行 (LINE)"), ("METHOD", "方法 (METHOD)")]


def load_acceptance(spec_path: Path) -> dict:
    with open(spec_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def extract_code_apis(code_root: Path, scope_filter: str = "all") -> Set[str]:
    """扫描 Java Controller，提取已实现的接口路径

    scope_filter: 只提取文件名包含此关键字的 controller；
                  'all'（默认）或空字符串 = 扫描全部 controller，不过滤。
    """
    apis = set()
    if not code_root.exists():
        return apis
    # 'all' / 空 = 不过滤；其它 = 仅保留文件名含该关键字的 controller
    scope_l = scope_filter.lower() if (scope_filter and scope_filter.lower() != "all") else None
    for java_file in code_root.rglob("*Controller.java"):
        if scope_l and scope_l not in java_file.name.lower():
            continue
        content = java_file.read_text(encoding="utf-8")
        # 提取类级别 @RequestMapping 的前缀路径（仅作前缀，不计入 API）
        class_prefix = ""
        class_m = re.search(r'@RequestMapping\(["\']([^"\']+)["\']\)', content)
        if class_m:
            class_prefix = class_m.group(1).rstrip("/")
        # 匹配方法级别 HTTP 动词映射（Post/Get/Put/Delete/Patch）
        # 注意：类级 @RequestMapping 仅作前缀，不再生成 method=REQUEST 的假条目
        def build_full(prefix: str, p: str) -> str:
            """拼装全路径：空 path 直接取类前缀（避免多余斜杠）"""
            if not p:
                return prefix
            if not p.startswith("/"):
                p = "/" + p
            return (prefix + p) if prefix else p

        verb_pat = r'@(Post|Get|Put|Delete|Patch)Mapping\((?:value\s*=\s*)?["\']([^"\']*)["\']'
        for verb, path in re.findall(verb_pat, content):
            method = verb.upper()
            full_path = build_full(class_prefix, path)
            norm = re.sub(r'\{(\w+)\}', r':\1', full_path)
            apis.add(f"{method} {norm}")
        # 方法级 @RequestMapping(value="/x", method=RequestMethod.GET)
        req_pat = (r'@RequestMapping\([^)]*value\s*=\s*["\']([^"\']*)["\']'
                   r'[^)]*method\s*=\s*RequestMethod\.(\w+)')
        for path, http_method in re.findall(req_pat, content):
            method = http_method.upper()
            full_path = build_full(class_prefix, path)
            norm = re.sub(r'\{(\w+)\}', r':\1', full_path)
            apis.add(f"{method} {norm}")
    return apis


def extract_non_http_annotations(code_root: Path) -> Set[str]:
    """F-18：扫描非 HTTP 接口适配器注解，返回 {TYPE:destination} 描述集合

    支持：@RabbitListener(queues=...) / @KafkaListener(topics=...) / @Scheduled(...)
    - RABBIT_LISTENER:队列名
    - KAFKA_LISTENER:topic 名
    - SCHEDULED:方法名（无显式 destination，约定用方法名）
    """
    found = set()
    if not code_root.exists():
        return found
    for java_file in code_root.rglob("*.java"):
        try:
            content = java_file.read_text(encoding="utf-8")
        except Exception:
            continue
        for m in re.finditer(r'@RabbitListener\([^)]*queues\s*=\s*["\']([^"\']+)["\']', content):
            found.add(f"RABBIT_LISTENER:{m.group(1)}")
        for m in re.finditer(r'@KafkaListener\([^)]*topics\s*=\s*["\']([^"\']+)["\']', content):
            found.add(f"KAFKA_LISTENER:{m.group(1)}")
        # @Scheduled 后的第一个方法名（跨行：注解在方法上一行）
        for m in re.finditer(
                r'@Scheduled\s*\([^)]*\)\s*\n?\s*(?:[\w<>\[\],\s.]+?)\s+(\w+)\s*\(', content):
            found.add(f"SCHEDULED:{m.group(1)}")
    return found


def check_non_http_consistency(spec: dict, code_root: Path) -> List[dict]:
    """F-18：SoT non_http_interfaces 段 vs 代码非 HTTP 适配器注解比对

    SoT 每个非 HTTP 接口（type + destination）都应在代码中找到对应适配器；
    找不到 → MISSING_NON_HTTP_IMPL（HIGH）。仅 --non-http 开启时检查。
    """
    issues = []
    nhs = spec.get("non_http_interfaces", [])
    if not nhs:
        return issues
    found = extract_non_http_annotations(code_root)
    for nh in nhs:
        nh_id = nh.get("id", "?")
        nh_type = nh.get("type", "UNKNOWN")
        dest = nh.get("destination", "")
        key = f"{nh_type}:{dest}" if dest else nh_type
        matched = key in found or (not dest and any(k.startswith(nh_type + ":") for k in found))
        if not matched:
            issues.append({
                "type": "MISSING_NON_HTTP_IMPL",
                "severity": "HIGH",
                "message": (f"SoT 登记了非 HTTP 接口 {nh_id}（{nh_type}"
                            f"{(':' + dest) if dest else ''}）但代码未找到对应适配器"
                            f"（@RabbitListener/@KafkaListener/@Scheduled）"),
            })
    return issues


def extract_test_coverage(test_root: Path) -> Dict[str, Set[str]]:
    """扫描测试文件，提取已覆盖的 API / 规则 / 场景，以及全部测试函数名"""
    coverage = {"apis": set(), "rules": set(), "scenarios": set(), "funcs": set()}
    if not test_root.exists():
        return coverage
    for test_file in test_root.rglob("test_*.py"):
        # 从文件名提取（F-2 命名：test_api_001.py → 末段 001，与 SoT id API-F003-001 末段匹配）
        m = re.search(r'test_api_([\w]+)\.py', test_file.name)
        if m:
            coverage["apis"].add(m.group(1).lower())
        content = test_file.read_text(encoding="utf-8")
        funcs = re.findall(r'def (test_\w+)', content)
        for func in funcs:
            coverage["funcs"].add(f"{test_file.name}::{func}")
            if "br_" in func:
                # F-5 命名：test_br_001 → br-001（与 SoT BR-F003-001 末段匹配）
                rm = re.search(r'br_(\w+)', func)
                if rm:
                    coverage["rules"].add(f"br-{rm.group(1)}")
            sm = re.match(r'test_sc_f(\d+)_(\d+)', func)
            if sm:
                # test_sc_f001_1 → F001-1
                coverage["scenarios"].add(f"F{sm.group(1)}-{sm.group(2)}")
    return coverage


def normalize_api_path(path: str) -> str:
    """把 {id} 转成 :id 用于比对"""
    return re.sub(r'\{(\w+)\}', r':\1', path)


def normalize_for_compare(path: str) -> str:
    """比对时归一化：去掉 /api 前缀，{id} -> :id"""
    p = re.sub(r'\{(\w+)\}', r':\1', path)
    p = re.sub(r'^/api/', '/', p)
    return p


# =====================================================================
# JaCoCo 覆盖率（总体 + 增量）
# =====================================================================

def parse_jacoco(xml_path: Path) -> dict:
    """解析 jacoco.xml → 总体计数器 + 逐类计数器

    返回：{
      'overall': {type: (missed, covered)},
      'classes': [(类全名, sourcefilename, {type: (missed, covered)})]
    }
    """
    root = ET.parse(xml_path).getroot()

    def counters_of(el) -> Dict[str, Tuple[int, int]]:
        d = {}
        for c in el.findall('counter'):
            d[c.get('type')] = (int(c.get('missed')), int(c.get('covered')))
        return d

    classes = []
    for pkg in root.findall('package'):
        for cls in pkg.findall('class'):
            classes.append((cls.get('name'), cls.get('sourcefilename'), counters_of(cls)))
    return {'overall': counters_of(root), 'classes': classes}


def git_changed_java_files(base: str) -> Set[str]:
    """git diff → 变更的 .java 文件名集合（用于增量覆盖率匹配）"""
    try:
        out = subprocess.check_output(
            ["git", "diff", "--name-only", base, "HEAD"],
            text=True, encoding="utf-8", stderr=subprocess.DEVNULL,
        )
        return {Path(f.strip()).name for f in out.splitlines() if f.strip().endswith(".java")}
    except Exception:
        return set()


def incremental_coverage(jacoco: dict, changed_basenames: Set[str]) -> dict:
    """按变更类聚合计数器 → 增量覆盖率"""
    agg: Dict[str, Tuple[int, int]] = {}
    matched = []
    for _name, src, ctrs in jacoco['classes']:
        if src in changed_basenames:
            matched.append(src)
            for t, (m, c) in ctrs.items():
                pm, pc = agg.get(t, (0, 0))
                agg[t] = (pm + m, pc + c)
    return {'counters': agg, 'matched': sorted(set(matched))}


def pct(missed: int, covered: int) -> str:
    total = missed + covered
    return f"{covered / total * 100:.1f}%" if total else "N/A"


def render_counter_table(counters: Dict[str, Tuple[int, int]]) -> str:
    """渲染 方法/行/指令 三行覆盖率表"""
    lines = ["| 维度 | 未覆盖 | 已覆盖 | 总量 | 覆盖率 |",
             "|------|--------|--------|------|--------|"]
    for t, label in JACOCO_TYPES:
        missed, covered = counters.get(t, (0, 0))
        lines.append(f"| {label} | {missed} | {covered} | {missed + covered} | {pct(missed, covered)} |")
    return "\n".join(lines)


# =====================================================================
# JUnit 执行结果
# =====================================================================

def parse_junit(xml_path: Path) -> Dict[str, str]:
    """解析 pytest --junitxml → {测试函数名: PASS/FAIL/ERROR/SKIP}"""
    root = ET.parse(xml_path).getroot()
    suites = root.findall('testsuite') or [root]
    results = {}
    for s in suites:
        for tc in s.findall('testcase'):
            name = tc.get('name')
            if tc.find('failure') is not None:
                st = 'FAIL'
            elif tc.find('error') is not None:
                st = 'ERROR'
            elif tc.find('skipped') is not None:
                st = 'SKIP'
            else:
                st = 'PASS'
            results[name] = st
    return results


def junit_status_by_prefix(junit: Dict[str, str], prefix: str) -> Dict[str, str]:
    """按函数名前缀过滤执行结果"""
    return {n: st for n, st in junit.items() if n.startswith(prefix)}


def summarize_exec(results: Dict[str, str]) -> Tuple[int, int, int, int]:
    """→ (通过, 失败, 跳过, 总数)；失败含 ERROR"""
    p = sum(1 for s in results.values() if s == 'PASS')
    f = sum(1 for s in results.values() if s in ('FAIL', 'ERROR'))
    sk = sum(1 for s in results.values() if s == 'SKIP')
    return p, f, sk, len(results)


# =====================================================================
# 意图说明完整性检查（单元测试模板约定）
# =====================================================================

def check_intent_docstrings(test_root: Path) -> Tuple[List[str], int]:
    """检查每个 test 函数的 docstring 是否含 [意图] 与 Given/When/Then

    返回 (缺失列表 ['file::func'], 检查总数)
    """
    missing, total = [], 0
    if not test_root.exists():
        return missing, total
    for test_file in test_root.rglob("test_*.py"):
        content = test_file.read_text(encoding="utf-8")
        # 按 '\ndef test_' 切块，每块首行是函数定义
        chunks = re.split(r'\n(?=def test_)', content)
        for chunk in chunks:
            m = re.match(r'def (test_\w+)', chunk)
            if not m:
                continue
            total += 1
            doc = re.search(r'"""(.*?)"""', chunk, re.DOTALL)
            doc_text = doc.group(1) if doc else ""
            ok = ('[意图]' in doc_text and 'Given' in doc_text
                  and 'When' in doc_text and 'Then' in doc_text)
            if not ok:
                missing.append(f"{test_file.name}::{m.group(1)}")
    return missing, total


# =====================================================================
# 三方比对
# =====================================================================

def check_consistency(spec: dict, code_apis: Set[str], test_cov: Dict[str, Set[str]],
                      mode: str = "full") -> List[dict]:
    """三方比对，输出漂移报告

    mode=incremental（存量项目增量模式）：
      SoT 只登记变更范围，code 中存量未登记接口不报 UNSPEC_API——
      存量代码"没测"不是漂移，只有 SoT 登记的变更项缺实现/缺测试才算。
    """
    issues = []

    # 1. spec API vs code
    spec_apis = set()
    for a in spec.get("apis", []):
        key = f"{a['method']} {normalize_for_compare(a['path'])}"
        spec_apis.add(key)
    spec_apis_normalized = spec_apis
    # 同样归一化 code_apis
    code_apis_normalized = set()
    for ca in code_apis:
        method, path = ca.split(" ", 1)
        code_apis_normalized.add(f"{method} {normalize_for_compare(path)}")
    missing_in_code = spec_apis_normalized - code_apis_normalized
    extra_in_code = code_apis_normalized - spec_apis_normalized
    for m in missing_in_code:
        issues.append({
            "type": "MISSING_IMPL",
            "severity": "HIGH",
            "message": f"spec 定义了接口但 code 未实现: {m}",
        })
    if mode != "incremental":
        # 全量模式：code 有而 SoT 无 → 漂移
        # 增量模式：存量未登记代码不算漂移，跳过
        for m in extra_in_code:
            issues.append({
                "type": "UNSPEC_API",
                "severity": "MEDIUM",
                "message": f"code 实现了 spec 未定义的接口: {m}",
            })

    # 2. spec API vs test（F-2 命名修复后按 ID 末段匹配：API-F003-001 ↔ test_api_001.py）
    spec_api_suffix = {}
    for a in spec.get("apis", []):
        spec_api_suffix[a["id"].split("-")[-1].lower()] = a["id"]
    test_api_suffixes = {s.lower() for s in test_cov["apis"]}
    missing_in_test = [spec_api_suffix[s] for s in spec_api_suffix
                       if s not in test_api_suffixes]
    for m in sorted(missing_in_test):
        issues.append({
            "type": "MISSING_TEST",
            "severity": "HIGH",
            "message": f"spec 定义了 API 但 test 未覆盖: {m}",
        })

    # 3. 业务规则覆盖（F-5 命名修复后按 ID 末段匹配：BR-F003-001 ↔ test_br_001）
    spec_rules = {r["id"] for r in spec.get("rules", [])}
    spec_rule_suffix = {r["id"].split("-")[-1].lower(): r["id"] for r in spec.get("rules", [])}
    test_rule_suffixes = {x.split("-")[-1].lower() for x in test_cov["rules"]}
    missing_rules = [spec_rule_suffix[s] for s in spec_rule_suffix
                     if s not in test_rule_suffixes]
    for m in sorted(missing_rules):
        issues.append({
            "type": "MISSING_RULE_TEST",
            "severity": "MEDIUM",
            "message": f"spec 定义了业务规则但 test 未覆盖: {m}",
        })

    # 4. 覆盖率目标检查
    api_cov = (len(spec_api_suffix) - len(missing_in_test)) / len(spec_api_suffix) * 100 \
        if spec_api_suffix else 0
    rule_cov = (len(spec_rules - set(missing_rules)) / len(spec_rules) * 100) \
        if spec_rules else 0

    return issues, {
        "api_coverage": api_cov,
        "rule_coverage": rule_cov,
        "api_target": 100,
        "rule_target": 100,
        "line_coverage_target": 80,
    }


def parse_impact_priorities(impact_path: Path | None) -> Dict[str, str]:
    """解析 change-impact.md → {场景ID: 优先级}（只认 P0/P1 行）"""
    out = {}
    if not impact_path or not Path(impact_path).exists():
        return out
    for line in Path(impact_path).read_text(encoding="utf-8").splitlines():
        if '|' not in line:
            continue
        cols = [c.strip() for c in line.split('|')]
        # 形如 | **P0** | F001-1 | ... |
        if len(cols) >= 3 and cols[1].strip('*') in ('P0', 'P1', 'P2'):
            out[cols[2]] = cols[1].strip('*')
    return out


def load_codegen_meta(tests_root: Path, explicit: str | None) -> dict | None:
    """加载 acceptance-codegen.py 的机器可读产物 _codegen_meta.json

    显式路径优先；否则在 tests 目录自动发现。缺失/损坏返回 None（报告显示未接入）。
    """
    p = Path(explicit) if explicit else (tests_root / "_codegen_meta.json")
    if not p.exists():
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


# =====================================================================
# 详细测试报告渲染（模板：templates/consistency-report-template.md）
# =====================================================================

def render_test_report(spec: dict, issues: List[dict], stats: dict,
                       jacoco: dict | None, incr: dict | None,
                       junit: Dict[str, str] | None, impact_pri: Dict[str, str],
                       test_cov: Dict[str, Set[str]], intent_missing: List[str],
                       intent_total: int, meta: dict) -> Tuple[str, bool]:
    """渲染详细测试报告 markdown → (报告文本, 是否 FAIL)"""
    now = datetime.now().isoformat(timespec="seconds")
    apis = spec.get("apis", [])
    rules = spec.get("rules", [])
    high = [i for i in issues if i["severity"] == "HIGH"]
    # CodeGraph 整合数据（来自 acceptance-codegen 的 _codegen_meta.json）
    cg_meta = meta.get("codegen_meta") or {}
    cg_src = cg_meta.get("codegraph") or ""
    cg_ann = cg_meta.get("api_annotations") or {}
    cg_drifts = cg_meta.get("field_drifts") or []
    # 派生异常用例（CodeGraph 约束/枚举/类型派生，test_*_cg_error_*）
    cg_derived_total = cg_meta.get("derived_error_cases_total")
    if cg_derived_total is None:
        cg_derived_total = sum(a.get("derived_error_cases", 0) for a in cg_ann.values())
    # 系统级异常清单（@ControllerAdvice，生成测试文件头部的标注）
    cg_gx = cg_meta.get("global_exceptions") or []
    L: List[str] = []

    L.append("# SCT 测试报告（一致性 × 覆盖率 × 执行情况）")
    L.append("")
    L.append(f"**Generated**: {now}  ")
    L.append(f"**SoT**: `{meta.get('spec', '')}`  ")
    L.append(f"**Code Scope**: `{meta.get('code', '')}`  ")
    L.append(f"**Tests**: `{meta.get('tests', '')}`  ")
    L.append(f"**Diff Base**: `{meta.get('base', 'N/A')}`  ")
    mode_label = ("incremental（增量：SoT 只登记变更范围，存量未登记代码不算漂移）"
                  if meta.get("mode") == "incremental"
                  else "full（全量：SoT 应覆盖扫描范围内全部接口）")
    L.append(f"**覆盖模式**: {mode_label}  ")
    if cg_src:
        refs = ["实现标注见 3.2", "字段级漂移见 6.2"]
        if cg_gx:
            refs.append("系统级异常见 6.3")
        if cg_derived_total:
            refs.append(f"派生异常用例 {cg_derived_total} 个（test_*_cg_error_*）")
        L.append(f"**CodeGraph**: `已接入（{cg_src}）`——示例值/必填/异常值取自真实代码，"
                 f"{'，'.join(refs)}  ")
    else:
        L.append("**CodeGraph**: `未接入（示例值为 SoT 启发式，无字段级比对与异常值派生）`  ")
    L.append(f"**JaCoCo 报告**: `{meta.get('jacoco', '未提供（--jacoco）')}`  ")
    L.append("**Tool**: consistency-check.py")
    L.append("")

    # ---- 摘要指标（结论部分再汇总）----
    incr_line_pct = "N/A"
    if incr and incr['counters'].get('LINE'):
        m, c = incr['counters']['LINE']
        incr_line_pct = pct(m, c)
    api_pass = api_fail = api_skip = api_total = 0
    if junit:
        api_pass, api_fail, api_skip, api_total = summarize_exec(junit_status_by_prefix(junit, "test_api_"))

    # ===== 1. 执行摘要 =====
    p0_fail = high or (junit and api_fail > 0)
    final_ok = not p0_fail
    L.append("## 1. 执行摘要")
    L.append("")
    L.append("| 维度 | 结果 | 门禁 |")
    L.append("|------|------|------|")
    L.append(f"| 三方一致性 | {len(high)} 个 HIGH 漂移 | 无 HIGH |")
    L.append(f"| 增量行覆盖率 | {incr_line_pct} | ≥ {stats['line_coverage_target']}% |")
    if junit:
        L.append(f"| 接口测试执行 | {api_pass}/{api_total} 通过，失败 {api_fail} | 全部通过 |")
    else:
        L.append("| 接口测试执行 | 未提供 junit（--junit） | 全部通过 |")
    if cg_src:
        L.append(f"| 字段级漂移 (FIELD_DRIFT) | {len(cg_drifts)} 个 | 建议 0（不阻塞放行） |")
    L.append(f"| **总结论** | {'✅ PASS' if final_ok else '❌ FAIL'} | — |")
    L.append("")

    # ===== 2. JaCoCo =====
    L.append("## 2. JaCoCo 代码覆盖率")
    L.append("")
    L.append("### 2.1 总体覆盖率")
    L.append("")
    if jacoco:
        L.append(render_counter_table(jacoco['overall']))
    else:
        L.append("> 未提供（运行时加 `--jacoco target/site/jacoco/jacoco.xml`）")
    L.append("")
    L.append("### 2.2 增量覆盖率（本次改动，人工审查重点）")
    L.append("")
    if jacoco and incr is not None:
        L.append("> 仅统计本次 diff 涉及的类；回答「改动是否被测试执行过」。")
        L.append("")
        L.append(render_counter_table(incr['counters']))
        L.append("")
        L.append(f"**本次改动的类**：{('、'.join(f'`{c}`' for c in incr['matched']) or '无（与 diff 无交集）')}")
    else:
        L.append("> 未提供 `--jacoco` + `--base`，无法计算增量覆盖率")
    L.append("")
    L.append("### 2.3 报告产物")
    L.append("")
    L.append(f"- HTML 明细：`{(meta.get('jacoco') or '').replace('jacoco.xml', 'index.html') or '未提供'}`")
    L.append(f"- XML 数据：`{meta.get('jacoco', '未提供')}`")
    L.append("")

    # ===== 3. 接口测试 =====
    L.append("## 3. 接口测试覆盖与执行情况")
    L.append("")
    tested_apis = {a["id"] for a in apis} & test_cov["apis"]
    untested = sorted({a["id"] for a in apis} - test_cov["apis"])
    L.append("### 3.1 覆盖情况")
    L.append("")
    if meta.get("mode") == "incremental":
        L.append("> 增量模式：只统计 SoT 登记的变更范围；存量接口不在本轮范围。")
        L.append("")
    L.append("| 指标 | 数值 |")
    L.append("|------|------|")
    L.append(f"| 范围内 API 总数（SoT） | {len(apis)} |")
    L.append(f"| 已测 | {len(tested_apis)} |")
    L.append(f"| 未测 | {len(untested)}" + (f"（{', '.join(untested)}）" if untested else "") + " |")
    L.append("")
    L.append("### 3.2 案例情况与执行结果")
    L.append("")
    # 「实现」列 = 生成测试文件头部的 CodeGraph 标注（Controller → Service）
    # 「其中派生异常」列 = CodeGraph 约束/枚举/类型派生的 cg_error 用例数（案例数的子集）
    has_ann = bool(cg_ann)
    if has_ann:
        L.append("> 「实现」列来自生成测试文件头部的 CodeGraph 标注（Controller → Service）；"
                 "「派生异常」为 CodeGraph 约束派生的 `cg_error` 用例数（含在案例数内）。")
        L.append("")
        L.append("| API ID | 接口名 | 方法 | 路径 | 实现（Controller → Service） | 案例数 | 其中派生异常 | 通过 | 失败 | 跳过 | 状态 |")
        L.append("|--------|--------|------|------|------------------------------|--------|--------------|------|------|------|------|")
    else:
        L.append("| API ID | 接口名 | 方法 | 路径 | 案例数 | 通过 | 失败 | 跳过 | 状态 |")
        L.append("|--------|--------|------|------|--------|------|------|------|------|")
    for a in apis:
        num = a["id"].split("-")[1] if "-" in a["id"] else a["id"]
        cases = junit_status_by_prefix(junit, f"test_api_{num.lower()}") if junit else {}
        if cases:
            p, f, sk, t = summarize_exec(cases)
            status = "✅" if f == 0 and p > 0 else "❌"
        else:
            # 无执行数据：按测试函数存在性统计案例数
            t = sum(1 for fn in test_cov["funcs"] if f"test_api_{num.lower()}_" in fn)
            p = f = sk = 0
            status = "未执行" if t else "❌ 无案例"
        row = f"| {a['id']} | {a['name']} | {a['method']} | `{a['path']}` |"
        if has_ann:
            a_ann = cg_ann.get(a["id"]) or {}
            if a_ann.get("matched"):
                impl = " → ".join(x for x in (a_ann.get("controller", ""),
                                              a_ann.get("service", "")) if x) or "-"
            else:
                impl = "未匹配"
            derived = a_ann.get("derived_error_cases", 0)
            row += f" {impl} |"
            row += f" {t} | {derived or '-'} |"
        else:
            row += f" {t} |"
        row += f" {p} | {f} | {sk} | {status} |"
        L.append(row)
    L.append("")
    if junit:
        fails = [n for n, s in junit.items() if n.startswith("test_api_") and s in ("FAIL", "ERROR")]
        if fails:
            L.append("**失败案例明细**：")
            L.append("")
            L.append("| 案例 | 执行状态 | 缺陷单（人工填写） |")
            L.append("|------|----------|---------------------|")
            for n in fails:
                L.append(f"| {n} | {junit[n]} | |")
            L.append("")
    L.append("### 3.3 案例意图说明完整性")
    L.append("")
    L.append(f"- 检查案例数：{intent_total}")
    if intent_missing:
        L.append(f"- 缺失意图说明：{len(intent_missing)}")
        for m in intent_missing:
            L.append(f"  - `{m}`")
    else:
        L.append("- 缺失意图说明：0")
    L.append("")

    # ===== 4. 业务规则 =====
    L.append("## 4. 业务规则验证情况")
    L.append("")
    L.append("| Rule ID | 规则（意图） | 优先级 | 对应测试 | 执行结果 | 结论 |")
    L.append("|---------|--------------|--------|----------|----------|------|")
    for r in rules:
        func = f"test_{r['id'].lower().replace('-', '_')}"
        st = junit.get(func) if junit else None
        result = f"{ '✅ ' + st if st else '未执行'}"
        concl = "已实现" if st == "PASS" else ("未通过" if st else "待执行")
        L.append(f"| {r['id']} | {r['text']} | {r.get('priority', '-')} | test_rules.py::{func} | {result} | {concl} |")
    L.append("")

    # ===== 5. 改动点审查 =====
    L.append("## 5. 改动点审查（人工审查核心）")
    L.append("")
    L.append("> 数据来自 `change-impact.md` × 测试执行结果；审查者逐行确认并填写审查意见。")
    L.append("")
    L.append("| 场景 ID | 优先级 | Given → When → Then | 覆盖测试 | 执行结果 | 测到改动点 | 审查意见（人工填写） |")
    L.append("|---------|--------|---------------------|----------|----------|------------|----------------------|")
    for feat in spec.get("features", []):
        for sc in feat.get("acceptance_scenarios", []):
            sid = sc.get("id", "?")
            pri = impact_pri.get(sid, "")
            if impact_pri and sid not in impact_pri:
                continue  # 有 impact 数据时只列命中场景
            func = "test_sc_" + sid.lower().replace("-", "_")
            covered = func in {f.split("::")[-1] for f in test_cov["funcs"]}
            st = junit.get(func) if junit else None
            hit = "✅ 是" if (covered and st == "PASS") else ("⚠️ 已测未过" if covered else "❌ 否")
            L.append(f"| {sid} | {pri or '-'} | {sc.get('given', '')} → {sc.get('when', '')} → {sc.get('then', '')} "
                     f"| {func} | {st or '未执行'} | {hit} | |")
    L.append("")

    # ===== 6. 漂移明细 =====
    L.append("## 6. 漂移明细")
    L.append("")
    L.append("### 6.1 三方一致性漂移（spec ↔ code ↔ test）")
    L.append("")
    if issues:
        L.append("| # | 严重级别 | 类型 | 描述 | 修复建议 |")
        L.append("|---|----------|------|------|----------|")
        for i, issue in enumerate(issues, 1):
            L.append(f"| {i} | {issue['severity']} | {issue['type']} | {issue['message']} | |")
    else:
        L.append("✓ 无漂移，spec/code/test 三方一致")
    L.append("")

    L.append("### 6.2 FIELD_DRIFT（SoT ↔ 代码 DTO 字段比对）")
    L.append("")
    if cg_src:
        L.append(f"> 来源：acceptance-codegen（CodeGraph `{cg_src}`）。`MISSING_IN_CODE` 优先处理"
                 "（SoT 改了代码没跟上）；`UNSPEC_IN_SOT` 增量模式下建议补登记；"
                 "`REQUIRED_MISMATCH` 核对必填口径。")
        L.append("")
        if cg_drifts:
            L.append("| API | 字段 | 类型 | 说明 |")
            L.append("|-----|------|------|------|")
            for d in cg_drifts:
                L.append(f"| {d.get('api', '')} | {d.get('field', '')} | {d.get('kind', '')} | {d.get('detail', '')} |")
        else:
            L.append("✓ SoT 与代码 DTO 字段一致，无字段级漂移")
    else:
        L.append("> 未接入 CodeGraph（codegen 未提供 `--codegraph`），无字段级比对。")
    L.append("")

    L.append("### 6.3 系统级异常清单（@ControllerAdvice，测试文件头部标注）")
    L.append("")
    if cg_src:
        if cg_gx:
            L.append("> 来源：CodeGraph `global_exceptions`（同步写入各生成测试文件头部）。"
                     "全接口适用、不可自动触发（401 需无 token、500 需故障注入），"
                     "故不生成用例，由安全/框架测试覆盖——本清单供人工审查系统异常值全集。")
            L.append("")
            L.append("| Status | Code | Message | Exception | 覆盖方式 |")
            L.append("|--------|------|---------|-----------|----------|")
            for gx in cg_gx:
                L.append(f"| {gx.get('status')} | {gx.get('code', '')} | {gx.get('message', '')} "
                         f"| {gx.get('exception', '')} | 安全/框架测试 |")
        else:
            L.append("> CodeGraph 未登记 `global_exceptions`，无法列出系统级异常全集"
                     "（建议对接方导出 @ControllerAdvice 处理器清单）。")
    else:
        L.append("> 未接入 CodeGraph，无系统级异常信息。")
    L.append("")

    # ===== 7. 结论 =====
    L.append("## 7. 结论与放行")
    L.append("")
    L.append(f"- HIGH 漂移: {len(high)} 个")
    L.append(f"- 接口测试执行: {api_pass + api_fail + api_skip}/{api_total or len(tested_apis)} 通过 {api_pass}，失败 {api_fail}" if junit
             else f"- 接口测试执行: 未提供 junit（--junit）")
    L.append(f"- 增量行覆盖率: {incr_line_pct}（门禁 ≥ {stats['line_coverage_target']}%）")
    if cg_src:
        L.append(f"- 字段级漂移 (FIELD_DRIFT): {len(cg_drifts)} 个（见 6.2，不阻塞放行）")
        L.append(f"- 派生异常用例: {cg_derived_total} 个（CodeGraph 约束/枚举/类型派生，见 3.2「其中派生异常」列）")
        L.append(f"- 系统级异常清单: {len(cg_gx)} 个（见 6.3，供人工审查）")
    if meta.get("mode") == "incremental":
        L.append("- 覆盖模式: **incremental（增量）**——存量代码不在本轮范围，"
                 "全量覆盖率仅供参考不作门禁；门禁 = SoT 范围内覆盖 100% + 增量行覆盖率")
    L.append(f"- **最终结论**: {'✅ PASS（可合入）' if final_ok else '❌ FAIL（先消除 HIGH 漂移与失败案例再合入）'}")
    L.append("")
    L.append("> FAIL 处置路径：改 spec / 改 code / 改 SoT → 重跑 `sct.codegen` → `sct.check` → `sct.e2e`。")
    return "\n".join(L), final_ok


def print_summary(issues: List[dict], stats: dict, report_path: str | None, final_ok: bool):
    """终端摘要（详细内容看报告文件）"""
    print("=" * 60)
    print("三方一致性校验摘要")
    print("=" * 60)
    print(f"API 覆盖率: {stats['api_coverage']:.1f}% (目标 {stats['api_target']}%)")
    print(f"规则覆盖率: {stats['rule_coverage']:.1f}% (目标 {stats['rule_target']}%)")
    if not issues:
        print("✓ 无漂移，spec/code/test 三方一致")
    else:
        high_count = sum(1 for i in issues if i["severity"] == "HIGH")
        print(f"发现 {len(issues)} 个漂移（HIGH {high_count} 个），详见报告")
    if report_path:
        print(f"\n📄 详细测试报告: {report_path}")
    return 0 if final_ok else 1


def preflight_api_tests(tests_root: Path, timeout: float) -> int:
    """接口测试预检：BASE_URL 是否存在且可达、API_AUTH_TOKEN 是否提示需要。

    返回 0 = 通过；3 = 缺前（agent 收到退出码 3 应让用户在对话框确认是否跳过接口层）。
    """
    api_files = list(tests_root.glob("test_api_*.py"))
    if not api_files:
        return 0  # 没有接口测试，不需预检
    base_url = os.getenv("BASE_URL", "http://localhost:8080")
    has_token = bool(os.getenv("API_AUTH_TOKEN"))

    # 可达性探测：HEAD BASE_URL，超时短（3s）足够
    reachable = False
    detail = ""
    try:
        import urllib.request, urllib.error
        req = urllib.request.Request(base_url, method="HEAD")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            reachable = (r.status < 500)
    except urllib.error.URLError as e:
        detail = f"连接失败：{e.reason}"
    except Exception as e:
        detail = f"{type(e).__name__}: {e}"

    print("🔎 接口测试预检：")
    print(f"   BASE_URL = {base_url}")
    print(f"   API_AUTH_TOKEN = {'已设置' if has_token else '未设置（开放接口/本地开发可继续）'}")
    print(f"   可达性 = {'可达' if reachable else f'不可达（{detail}）'}")

    if reachable:
        return 0
    if has_token:
        # 设了 token 但连不上 → 网络/服务问题
        print()
        print("⚠️  [prereq] BASE_URL 设了 token 但服务不可达——可能是服务未启动、端口被挡、或环境不通。")
        print("    退出码 3 表示「接口测试缺前」，将作为工具结果反馈给 agent；")
        print("    在对话框确认是否：")
        print("      a) 先修环境（启动服务/换 BASE_URL），再重跑 sct.check")
        print("      b) 跳过接口层：`sct.check --skip-api-tests ...`")
        return 3
    print()
    print("⚠️  [prereq] 接口测试缺前：")
    print(f"    - BASE_URL 不可达：{detail or '服务未监听'}")
    print("    - API_AUTH_TOKEN 未设")
    print("    在对话框确认输入：")
    print("      1) 提供 token / 修环境后再跑：`export API_AUTH_TOKEN=...` 后重跑 sct.check")
    print("      2) 跳过接口层：`sct.check --skip-api-tests ...`")
    return 3


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", required=True)
    parser.add_argument("--code", required=True)
    parser.add_argument("--tests", required=True)
    parser.add_argument("--scope", default="all",
                        help="Controller 名字关键字过滤；'all'（默认）= 扫描全部 controller")
    parser.add_argument("--jacoco", help="jacoco.xml 路径（总体+增量覆盖率）")
    parser.add_argument("--base", default="main", help="增量覆盖率基线 git ref")
    parser.add_argument("--junit", help="pytest --junitxml 报告路径（执行情况）")
    parser.add_argument("--impact", help="change-impact.md 路径（改动点审查表）")
    parser.add_argument("--codegen-meta",
                        help="_codegen_meta.json 路径（acceptance-codegen 产物，含 CodeGraph "
                             "实现标注/FIELD_DRIFT/派生异常数/系统级异常清单；"
                             "缺省自动在 --tests 目录发现）")
    parser.add_argument("--mode", choices=["full", "incremental"],
                        help="覆盖模式：full=全量（默认）/ incremental=增量（存量项目只测变更，"
                             "缺省读 SoT _meta.coverage_mode）")
    parser.add_argument("--report", help="详细测试报告输出路径（markdown）")
    parser.add_argument("--skip-api-tests", action="store_true",
                        help="跳过接口测试层（test_api_*.py）；用于环境无 BASE_URL/token 时"
                             "只跑规则测试 + 覆盖率 + 漂移门禁，避免阻塞。")
    parser.add_argument("--skip-rule-tests", action="store_true",
                        help="跳过规则测试层（test_rules.py / Java 单测）；用于只关心 API 层的场景")
    parser.add_argument("--prereq-timeout", type=float, default=3.0,
                        help="API 测试预检 BASE_URL 可达性的超时（秒），默认 3")
    parser.add_argument("--module", default="",
                        help="F-17：微服务模块名；默认拼接 {code}/{module}/src/main/java 作为源码根"
                             "（源码位置可用 --module-src 覆盖）")
    parser.add_argument("--module-src", default="",
                        help="F-17：模块内源码相对路径（默认 src/main/java；源码在 src/main/kotlin "
                             "或自定义目录时用）")
    parser.add_argument("--non-http", action="store_true",
                        help="F-18：启用非 HTTP 接口适配器检查（扫描 @RabbitListener/"
                             "@KafkaListener/@Scheduled 与 SoT non_http_interfaces 段比对）")
    args = parser.parse_args()

    spec = load_acceptance(Path(args.spec))
    # F-17：--module 时源码根 = {code}/{module}/{module_src or 'src/main/java'}
    if args.module:
        code_root = (Path(args.code) / args.module
                     / (args.module_src or "src/main/java"))
    else:
        code_root = Path(args.code)
    code_apis = extract_code_apis(code_root, args.scope)
    test_cov = extract_test_coverage(Path(args.tests))

    # 接口测试预检：BASE_URL 可达性 + token 提示；缺前则退出 3，让 agent 让用户在对话框确认
    if not args.skip_api_tests and not args.skip_rule_tests:
        # skip_rule_tests 不影响 API 预检；只 skip_api_tests 才免预检
        rc = preflight_api_tests(Path(args.tests), args.prereq_timeout)
        if rc == 3:
            sys.exit(3)

    # 覆盖模式解析优先级：CLI --mode > SoT _meta.coverage_mode > full
    mode = args.mode or (spec.get("_meta") or {}).get("coverage_mode") or "full"

    # 意图说明检查 → 追加 MISSING_INTENT 漂移
    intent_missing, intent_total = check_intent_docstrings(Path(args.tests))
    issues, stats = check_consistency(spec, code_apis, test_cov, mode)
    for m in intent_missing:
        issues.append({
            "type": "MISSING_INTENT",
            "severity": "MEDIUM",
            "message": f"测试案例缺失真相意图说明（[意图]/Given/When/Then）: {m}",
        })
    # F-18：非 HTTP 接口适配器检查（--non-http 开启且 SoT 有 non_http_interfaces 段）
    if args.non_http:
        nh_issues = check_non_http_consistency(spec, code_root)
        issues.extend(nh_issues)
        if nh_issues:
            print(f"⚠️  {len(nh_issues)} 个非 HTTP 接口未在代码中找到适配器（MISSING_NON_HTTP_IMPL）")

    # 可选数据源
    jacoco = parse_jacoco(Path(args.jacoco)) if args.jacoco and Path(args.jacoco).exists() else None
    incr = incremental_coverage(jacoco, git_changed_java_files(args.base)) if jacoco else None
    junit = parse_junit(Path(args.junit)) if args.junit and Path(args.junit).exists() else None
    impact_pri = parse_impact_priorities(Path(args.impact) if args.impact else None)
    codegen_meta = load_codegen_meta(Path(args.tests), args.codegen_meta)
    if codegen_meta:
        cg = codegen_meta.get("codegraph") or ""
        n = len(codegen_meta.get("field_drifts") or [])
        d = codegen_meta.get("derived_error_cases_total")
        if d is None:
            d = sum(a.get("derived_error_cases", 0)
                    for a in (codegen_meta.get("api_annotations") or {}).values())
        g = len(codegen_meta.get("global_exceptions") or [])
        print(f"CodeGraph: {'已接入（' + cg + '）' if cg else '未接入'}，"
              f"FIELD_DRIFT {n} 个，派生异常用例 {d} 个，系统级异常 {g} 个（将整合进测试报告）")

    meta = {"spec": args.spec, "code": str(code_root), "tests": args.tests,
            "base": args.base if jacoco else "N/A", "jacoco": args.jacoco or "",
            "mode": mode, "codegen_meta": codegen_meta}

    # 落盘详细报告 + 终端摘要
    report_path = None
    final_ok = not any(i["severity"] == "HIGH" for i in issues)
    if args.report:
        report, final_ok = render_test_report(
            spec, issues, stats, jacoco, incr, junit, impact_pri,
            test_cov, intent_missing, intent_total, meta)
        rp = Path(args.report)
        rp.parent.mkdir(parents=True, exist_ok=True)
        rp.write_text(report, encoding="utf-8")
        report_path = str(rp)

    sys.exit(print_summary(issues, stats, report_path, final_ok))


if __name__ == "__main__":
    main()
