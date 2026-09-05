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

防空洞（测试有效性维度，v2.3 起，收编 verification-gate 三态）：
        加任一旗标即在门禁中追加「测试有效性」证据项——
        --surefire <surefire-reports>   真实执行数 REAL_TESTS（堵"声称有测试实际 0 执行"）
        --tasks <tasks.md>              幻影任务 PHANTOM_TASK（标 [X] 但代码无证据）
        --verify-compile                编译门 COMPILE（默认不跑；内网无 mvn/gradle 时勿开）

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
import sct_ids
from typing import Dict, List, Set, Tuple


def _load_contract_validate():
    """加载同目录 contract-validate.py（文件名带连字符，不能普通 import）。"""
    import importlib.util as _ilu
    _p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "contract-validate.py")
    _s = _ilu.spec_from_file_location("sct_contract_validate", _p)
    _m = _ilu.module_from_spec(_s)
    _s.loader.exec_module(_m)
    return _m

# JaCoCo 计数器类型 → 中文名（只取报告关注的三个维度）
JACOCO_TYPES = [("INSTRUCTION", "指令 (INSTRUCTION)"), ("LINE", "行 (LINE)"), ("METHOD", "方法 (METHOD)")]

# =====================================================================
# 可选复用 verification-gate.py（同目录）的防空洞检查：
#   --surefire        → REAL_TESTS 真实执行数
#   --tasks           → PHANTOM_TASK 幻影任务
#   --verify-compile  → COMPILE 编译门
# 收编为「测试有效性」维度的证据项（v2.3 起）。verification-gate.py
# 缺失时降级为 UNPROVEN，不假装完成。
# =====================================================================
_VERIFICATION_GATE = None


def _load_verification_gate():
    global _VERIFICATION_GATE
    if _VERIFICATION_GATE is None:
        try:
            import importlib.util as _ilu
            _p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "verification-gate.py")
            _s = _ilu.spec_from_file_location("sct_verification_gate", _p)
            _m = _ilu.module_from_spec(_s)
            _s.loader.exec_module(_m)
            _VERIFICATION_GATE = _m
        except Exception:
            _VERIFICATION_GATE = False
    return _VERIFICATION_GATE or None


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

    # v2.5 语言中立：Python 路由提取（Flask / FastAPI / aiohttp 约定）。
    # 覆盖常见声明式路由；自造路由表的项目用契约 _meta.impl_evidence: none
    # 显式声明"不做路由级实现核对"，MISSING_IMPL 降级为人工核对项而非 HIGH。
    for py_file in list(code_root.rglob("*.py")):
        if scope_l and scope_l not in py_file.name.lower():
            continue
        try:
            content = py_file.read_text(encoding="utf-8")
        except OSError:
            continue
        if "route" not in content and "post(" not in content.lower() \
                and "get(" not in content.lower() and "put(" not in content.lower() \
                and "delete(" not in content.lower() and "patch(" not in content.lower():
            continue
        # FastAPI：@app.post("/path") / @router.delete("/path") ...
        for verb, path in re.findall(
                r'@\w+\.(post|get|put|delete|patch)\(\s*["\']([^"\']+)["\']', content, re.I):
            norm = re.sub(r'\{(\w+)\}', r':\1', path if path.startswith("/") else "/" + path)
            apis.add(f"{verb.upper()} {norm}")
        # Flask：@app.route("/path", methods=["POST", ...])（缺 methods 默认 GET）
        for m in re.finditer(
                r'@[\w.]+\.route\(\s*["\']([^"\']+)["\']([^)]*)\)', content):
            path, extra = m.group(1), m.group(2)
            methods = re.findall(r'["\'](GET|POST|PUT|DELETE|PATCH)["\']', extra, re.I) or ["GET"]
            norm = re.sub(r'<(\w+:)?(\w+)>', r':\2', path if path.startswith("/") else "/" + path)
            for mm in methods:
                apis.add(f"{mm.upper()} {norm}")
        # aiohttp：routes.append(("POST", "/path", handler)) 或 web.post("/path", h)
        for verb, path in re.findall(
                r'web\.(post|get|put|delete|patch)\(\s*["\']([^"\']+)["\']', content, re.I):
            norm = re.sub(r'\{(\w+)\}', r':\1', path if path.startswith("/") else "/" + path)
            apis.add(f"{verb.upper()} {norm}")
    return apis


def extract_test_coverage(test_root: Path) -> Dict[str, Set[str]]:
    """扫描测试文件，提取已覆盖的 API / 规则 / 场景，以及全部测试函数名"""
    coverage = {"apis": set(), "rules": set(), "scenarios": set(), "funcs": set(),
                "java_tests": set()}
    if not test_root.exists():
        return coverage
    # Java 单测类（target.class 有值时生成 <Class>Test.java，如 UpControllerTest）
    for jf in test_root.rglob("*Test.java"):
        content = jf.read_text(encoding="utf-8", errors="ignore")
        m = re.search(r'class\s+(\w+Test)\b', content)
        if m:
            coverage["java_tests"].add(m.group(1))
    for test_file in test_root.rglob("test_*.py"):
        # 从文件名提取（F-2 命名：test_api_001.py → 末段 001，与 SoT id API-F003-001 末段匹配）
        m = sct_ids.API_TEST_FILE_PAT.search(test_file.name)
        if m:
            coverage["apis"].add(m.group(1).lower())
        content = test_file.read_text(encoding="utf-8")
        funcs = re.findall(r'def (test_\w+)', content)
        for func in funcs:
            coverage["funcs"].add(f"{test_file.name}::{func}")
            if "br_" in func:
                # F-5 命名：test_br_001 → br-001（与 SoT BR-F003-001 末段匹配）
                rm = sct_ids.RULE_FUNC_PAT.search(func)
                if rm:
                    coverage["rules"].add(f"br-{rm.group(1)}")
            sm = sct_ids.SCENARIO_FUNC_PAT.match(func)
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

    # v2.5 语言中立：coverage.py 的 XML（cobertura 格式）与 JaCoCo 同门禁——
    # Python 项目用 `coverage xml` 产出，行计数由 <line hits> 逐行统计
    # （cobertura 类级只有 line-rate，无 missed/covered 总量属性）。
    if root.tag == "coverage":
        def _int(el, k):
            try:
                return int(float(el.get(k) or 0))
            except (TypeError, ValueError):
                return 0
        covered = _int(root, "lines-covered")
        valid = _int(root, "lines-valid")
        overall = {"LINE": (valid - covered, covered)}
        classes = []
        for cls in root.iter("class"):
            hit_lines = [int(ln.get("hits") or 0) for ln in cls.findall("lines/line")]
            cov = sum(1 for h in hit_lines if h > 0)
            val = len(hit_lines)
            fname = (cls.get("filename") or "").replace("\\", "/").split("/")[-1]
            if val:
                classes.append((cls.get("name") or fname, fname, {"LINE": (val - cov, cov)}))
        return {'overall': overall, 'classes': classes}

    classes = []
    for pkg in root.findall('package'):
        for cls in pkg.findall('class'):
            classes.append((cls.get('name'), cls.get('sourcefilename'), counters_of(cls)))
    return {'overall': counters_of(root), 'classes': classes}


def git_changed_java_files(base: str) -> Set[str]:
    """git diff → 变更的源码文件名集合（v2.5 语言中立：.java + .py，用于增量覆盖率匹配）"""
    try:
        out = subprocess.check_output(
            ["git", "diff", "--name-only", base, "HEAD"],
            text=True, encoding="utf-8", stderr=subprocess.DEVNULL,
        )
        return {Path(f.strip()).name for f in out.splitlines()
                if f.strip().endswith((".java", ".py"))}
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
# 三态门禁（v1.1.3 起）：与 testing.run 同一语义 —— UNPROVEN ≠ PASS
# 每个证据项独立判 PASS/BLOCK/UNPROVEN/NOT_APPLICABLE，整体取最严。
# 退出码：PASS=0 / BLOCK=1 / UNPROVEN=2（预检用户确认跳过仍为 3）。
# =====================================================================

# 三态排序统一引自 sct_ids.VERDICT_RANK（v2.5.1 单一事实源，与 verification-gate 一致）
VERDICT_ORDER = sct_ids.VERDICT_RANK

# =====================================================================
# P0-4 Quality Profile：用档位替代硬编码的「90% 覆盖率」
#   fast     快速验证：覆盖率门槛低，测试完整性要求宽松（改代码时的快速反馈）
#   standard 标准：当前默认（覆盖率 90% + 测试完整性严格）
#   strict   严格：覆盖率 95%，不放过任何 UNPROVEN 缝隙
# =====================================================================

PROFILES = {
    "fast": {"coverage": 70, "label": "快速验证"},
    "standard": {"coverage": 90, "label": "标准"},
    "strict": {"coverage": 95, "label": "严格"},
}
DEFAULT_PROFILE = "standard"

# 2.0 四维证据（P0-3）：每个 gate 归属一个维度
EVIDENCE_DIMENSIONS = ["需求覆盖", "执行结果", "证据完整性", "测试完整性"]


def profile_coverage(profile: str) -> int:
    return PROFILES.get(profile, PROFILES[DEFAULT_PROFILE])["coverage"]


def evaluate_gates(issues: List[dict], junit: Dict[str, str] | None,
                   incr: dict | None, coverage_target: int,
                   skip_api_tests: bool, tests_root: Path | None = None,
                   codegen_meta: dict | None = None,
                   trace_rows: List[dict] | None = None,
                   intent_missing: List[str] | None = None,
                   profile: str = DEFAULT_PROFILE,
                   tasks_path: str | None = None,
                   surefire_dir: str | None = None,
                   verify_compile: bool = False,
                   compile_timeout: int = 300,
                   skip_rule_tests: bool = False,
                   code_root: str | None = None) -> List[dict]:
    """把门禁落成**结构化证据**（P0-3，四维 + 可选第五维「测试有效性」）：
    需求覆盖 / 执行结果 / 证据完整性 / 测试完整性，
    提供 --surefire / --tasks / --verify-compile 时追加「测试有效性」（防空洞，
    v2.3 起收编 verification-gate 的 REAL_TESTS / PHANTOM_TASK / COMPILE）。

    每个证据项独立判 PASS/BLOCK/UNPROVEN/NOT_APPLICABLE，整体取最严。
    覆盖率门槛由 Quality Profile（P0-4）决定，不再硬编码。
    """
    gates: List[dict] = []
    trace_rows = trace_rows or []
    intent_missing = intent_missing or []

    # ===== 维度 1：需求覆盖 REQUIREMENT_COVERAGE =====
    high = [i for i in issues if i["severity"] == "HIGH"]
    no_test = [r for r in trace_rows if r["test"] == "—"]
    if no_test or high:
        parts = []
        if no_test:
            parts.append(f"{len(no_test)} 条契约条目无测试（漏测）")
        if high:
            parts.append(f"{len(high)} 个 HIGH 漂移")
        gates.append({"id": "REQUIREMENT_COVERAGE", "dimension": "需求覆盖",
                      "verdict": "BLOCK",
                      "detail": "；".join(parts) + "（详见报告「需求追溯矩阵」）"})
    else:
        gates.append({"id": "REQUIREMENT_COVERAGE", "dimension": "需求覆盖",
                      "verdict": "PASS" if trace_rows else "UNPROVEN",
                      "detail": (f"{len(trace_rows)} 条契约条目全部有测试与实现"
                                 if trace_rows else "无可追溯条目")})

    # ===== 维度 2：执行结果 EXECUTION_RESULT（通过率 + 覆盖率）=====
    if skip_api_tests:
        gates.append({"id": "EXECUTION_RESULT", "dimension": "执行结果",
                      "verdict": "NOT_APPLICABLE", "detail": "--skip-api-tests：执行层跳过"})
    elif not junit:
        gates.append({"id": "EXECUTION_RESULT", "dimension": "执行结果",
                      "verdict": "UNPROVEN", "detail": "未提供 --junit，执行结果未验证"})
    else:
        p, f, sk, total = summarize_exec(junit)
        if total == 0 or (p == 0 and f == 0):
            gates.append({"id": "EXECUTION_RESULT", "dimension": "执行结果",
                          "verdict": "UNPROVEN",
                          "detail": f"junit 中无可执行用例（总数 {total}，跳过 {sk}）"})
        elif f > 0:
            gates.append({"id": "EXECUTION_RESULT", "dimension": "执行结果",
                          "verdict": "BLOCK",
                          "detail": f"{f} 个用例失败/错误（通过 {p}，跳过 {sk}，总数 {total}）"})
        else:
            gates.append({"id": "EXECUTION_RESULT", "dimension": "执行结果",
                          "verdict": "PASS", "detail": f"{p}/{total} 通过（跳过 {sk}）"})

    # 覆盖率（同一维度：执行结果）
    if skip_api_tests:
        gates.append({"id": "LINE_COVERAGE", "dimension": "执行结果",
                      "verdict": "NOT_APPLICABLE", "detail": "--skip-api-tests：覆盖率不判定"})
    elif incr is None:
        gates.append({"id": "LINE_COVERAGE", "dimension": "执行结果",
                      "verdict": "UNPROVEN",
                      "detail": "未提供 --jacoco + --base，增量覆盖率未验证"})
    else:
        line = incr["counters"].get("LINE")
        if not line or (line[0] + line[1]) == 0:
            gates.append({"id": "LINE_COVERAGE", "dimension": "执行结果",
                          "verdict": "UNPROVEN",
                          "detail": "diff 与 JaCoCo 类无交集，增量覆盖率无法计算"})
        else:
            missed, covered = line
            pct_val = covered / (missed + covered) * 100
            ok = pct_val >= coverage_target
            gates.append({
                "id": "LINE_COVERAGE", "dimension": "执行结果",
                "verdict": "PASS" if ok else "BLOCK",
                "detail": f"增量行覆盖率 {pct_val:.1f}%（{profile} 档门禁 ≥{coverage_target}%）",
            })

    # ===== 维度 3：证据完整性 EVIDENCE_COMPLETENESS =====
    missing_evidence = []
    if not skip_api_tests:
        if not junit:
            missing_evidence.append("--junit")
        if incr is None:
            missing_evidence.append("--jacoco + --base")
    if missing_evidence:
        gates.append({"id": "EVIDENCE_COMPLETENESS", "dimension": "证据完整性",
                      "verdict": "UNPROVEN",
                      "detail": f"缺证据：{'、'.join(missing_evidence)}（UNPROVEN ≠ PASS）"})
    else:
        gates.append({"id": "EVIDENCE_COMPLETENESS", "dimension": "证据完整性",
                      "verdict": "PASS", "detail": "执行结果与覆盖率证据齐备"})

    # ===== 维度 4：测试完整性 TEST_INTEGRITY（write-once + 意图完整）=====
    expected = (codegen_meta or {}).get("expected_outputs") or []
    if not expected:
        gates.append({"id": "TEST_INTEGRITY", "dimension": "测试完整性",
                      "verdict": "UNPROVEN",
                      "detail": "无 write-once manifest（旧版生成），重跑 testing.design 后可验证"})
    elif tests_root is not None:
        import hashlib as _hl
        problems = []
        for item in expected:
            fp = tests_root / item.get("path", "")
            if not fp.exists():
                problems.append(f"缺失 {item.get('path')}")
            elif _hl.sha256(fp.read_bytes()).hexdigest() != item.get("sha256"):
                problems.append(f"手改 {item.get('path')}")
        if problems:
            gates.append({"id": "TEST_INTEGRITY", "dimension": "测试完整性",
                          "verdict": "BLOCK",
                          "detail": f"生成测试被改动/缺失 {len(problems)} 处（{'；'.join(problems[:3])}"
                                    f"{'…' if len(problems) > 3 else ''}）——write-once 纪律被破坏，"
                                    f"重跑 testing.design --force 恢复"})
        elif intent_missing:
            # 意图缺失：standard/strict 档视为不完整证据
            gates.append({"id": "TEST_INTEGRITY", "dimension": "测试完整性",
                          "verdict": "UNPROVEN" if profile == "fast" else "BLOCK",
                          "detail": f"{len(intent_missing)} 个测试案例缺失意图说明"
                                    f"（[意图]/Given/When/Then）"})
        else:
            gates.append({"id": "TEST_INTEGRITY", "dimension": "测试完整性",
                          "verdict": "PASS",
                          "detail": f"{len(expected)} 个生成文件 hash 一致且意图完整"})

    # ===== 维度 5（可选）：测试有效性 TEST_EFFECTIVENESS（防空洞，v2.3 起）=====
    # 提供 --surefire / --tasks / --verify-compile 中的任一旗标即激活本维度。
    # 回答"测试不仅存在，而且真的被执行了、任务不是幻影"——堵"声称有测试
    # 实际 0 个执行"的假绿。verification-gate.py 缺失时降级 UNPROVEN。
    if tasks_path or surefire_dir or verify_compile:
        vg = _load_verification_gate()
        if vg is None:
            gates.append({"id": "TEST_EFFECTIVENESS", "dimension": "测试有效性",
                          "verdict": "UNPROVEN",
                          "detail": "verification-gate.py 不可用（应位于 scripts/ 同目录），"
                                    "无法评估测试有效性——不假装通过"})
        else:
            # 1) 真实执行数 REAL_TESTS：读 surefire TEST-*.xml 的实际执行数
            if not surefire_dir:
                gates.append({"id": "REAL_TESTS", "dimension": "测试有效性",
                              "verdict": "NOT_APPLICABLE",
                              "detail": "未提供 --surefire（真实执行报告）；提供后防空洞证据才能判定"})
            elif skip_rule_tests:
                gates.append({"id": "REAL_TESTS", "dimension": "测试有效性",
                              "verdict": "NOT_APPLICABLE",
                              "detail": "--skip-rule-tests：单测层跳过，真实执行数不判定"})
            else:
                st, _n, dt = vg.check_real_tests(surefire_dir)
                gates.append({"id": "REAL_TESTS", "dimension": "测试有效性",
                              "verdict": st, "detail": dt})
            # 2) 幻影任务 PHANTOM_TASK：tasks.md 标 [X] 但代码中无实现证据
            if not tasks_path:
                gates.append({"id": "PHANTOM_TASK", "dimension": "测试有效性",
                              "verdict": "NOT_APPLICABLE",
                              "detail": "未提供 --tasks（tasks.md）；提供后幻影检测才能判定"})
            else:
                st, items, dt = vg.check_phantom_tasks(
                    tasks_path, code_root or "", str(tests_root) if tests_root else "")
                if items:
                    dt += "　例：" + "；".join(i["task"][:40] for i in items[:3])
                gates.append({"id": "PHANTOM_TASK", "dimension": "测试有效性",
                              "verdict": st, "detail": dt})
            # 3) 编译门 COMPILE：显式 --verify-compile 才跑（内网无 mvn/gradle 默认不拖累门禁）
            if not verify_compile:
                gates.append({"id": "COMPILE", "dimension": "测试有效性",
                              "verdict": "NOT_APPLICABLE",
                              "detail": "未开启 --verify-compile；有真实执行报告（--surefire）即隐含编译通过"})
            else:
                st, dt = vg.check_compile(code_root or "", compile_timeout)
                gates.append({"id": "COMPILE", "dimension": "测试有效性",
                              "verdict": st, "detail": dt.replace("\n", " ")[:300]})
    return gates


def overall_verdict(gates: List[dict]) -> str:
    """整体取最严；NOT_APPLICABLE 不参与。全 N/A 时退化为 UNPROVEN（无证据不放绿）。"""
    effective = [g["verdict"] for g in gates if g["verdict"] != "NOT_APPLICABLE"]
    if not effective:
        return "UNPROVEN"
    return max(effective, key=lambda v: VERDICT_ORDER[v])


def verdict_exit_code(verdict: str) -> int:
    return {"PASS": 0, "BLOCK": 1, "UNPROVEN": 2}.get(verdict, 2)


VERDICT_ICON = {"PASS": "✅ PASS", "BLOCK": "❌ BLOCK",
                "UNPROVEN": "⚠️ UNPROVEN", "NOT_APPLICABLE": "➖ N/A"}


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
    # v2.5：非标准工程逃生门——契约 _meta.impl_evidence: none 显式声明
    # "路由由自造机制承载，静态提取不可见"，MISSING_IMPL 降级为人工核对项（MEDIUM），
    # 不产生 HIGH 假阻断；接口层的执行证据（L2 真调用）仍然照常把关。
    impl_evidence = ((spec.get("_meta") or {}).get("impl_evidence") or "routes").lower()
    for m in missing_in_code:
        if impl_evidence == "none":
            issues.append({
                "type": "MISSING_IMPL",
                "severity": "MEDIUM",
                "message": f"spec 定义了接口但 code 未实现（impl_evidence=none，需人工核对路由）: {m}",
            })
        else:
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
        spec_api_suffix[sct_ids.id_suffix(a["id"])] = a["id"]
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
    spec_rule_suffix = {sct_ids.id_suffix(r["id"]): r["id"] for r in spec.get("rules", [])}
    test_rule_suffixes = {sct_ids.id_suffix(x) for x in test_cov["rules"]}
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
        # P0-4：覆盖率门槛不再硬编码，由 Quality Profile 决定
        "line_coverage_target": profile_coverage(DEFAULT_PROFILE),
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
# P0-2：REQ → AC → TEST → EXECUTION → EVIDENCE 追溯矩阵
# =====================================================================

def build_traceability_matrix(spec: dict, test_cov: Dict[str, Set[str]],
                              junit: Dict[str, str] | None,
                              source_spec: str = "") -> List[dict]:
    """每个契约条目（AC）一行，串起来源需求、派生测试、执行结果与证据状态。

    证据状态推导（与全局三态一致）：
      无测试 → BLOCK（漏测）；有测试未执行 → UNPROVEN；
      执行失败 → BLOCK；执行通过 → PASS；执行被跳过 → UNPROVEN
    """
    rows: List[dict] = []
    funcs = {fn.split("::")[-1]: fn for fn in test_cov.get("funcs", set())}

    def _file_of_func(func: str) -> str:
        """函数名 → 实际所在测试文件名（证据标签精确到文件，v2.5.2）。"""
        full = funcs.get(func, "")
        return full.split("::")[0] if "::" in full else ""

    def evidence_of(func_names: list, has_test: bool) -> tuple:
        if not has_test:
            return "—（无测试）", "BLOCK"
        if not junit:
            return "未执行（缺 --junit）", "UNPROVEN"
        matched = {f: junit[f] for f in func_names if f in junit}
        if not matched:
            return "未执行", "UNPROVEN"
        p = sum(1 for s in matched.values() if s == "PASS")
        f_ = sum(1 for s in matched.values() if s in ("FAIL", "ERROR"))
        sk = sum(1 for s in matched.values() if s == "SKIP")
        desc = f"通过 {p} / 失败 {f_} / 跳过 {sk}"
        if f_ > 0:
            return desc, "BLOCK"
        if p == 0 and sk > 0:
            return desc, "UNPROVEN"
        return desc, "PASS"

    # ---- apis ----
    for a in spec.get("apis", []):
        suffix = sct_ids.id_suffix(a["id"])
        has_test = suffix in test_cov.get("apis", set())
        names = [f for f in funcs
                 if f.startswith(sct_ids.api_test_func_prefix(a["id"]) + "_")]
        exe, ev = evidence_of(names, has_test)
        rows.append({
            "req": a.get("derived_from") or source_spec,
            "ac": a["id"], "kind": "API",
            "desc": f"{a.get('method', '')} {a.get('path', '')}".strip(),
            "test": sct_ids.api_test_filename(a["id"]) if has_test else "—",
            "execution": exe, "evidence": ev,
        })

    # ---- rules ----
    for r in spec.get("rules", []):
        func = sct_ids.rule_test_func(r["id"])
        suffix = sct_ids.id_suffix(r["id"])
        # 有 target 的规则生成 Java 单测 <Class>Test.java（区别于 Python test_br_*）
        target_cls = (r.get("target") or {}).get("class", "") \
            if isinstance(r.get("target"), dict) else ""
        java_cls_name = sct_ids.java_test_class_name(target_cls)
        java_covered = bool(java_cls_name) and java_cls_name in test_cov.get("java_tests", set())
        has_test = java_covered \
            or any(f"br_{suffix}" in k for k in test_cov.get("rules", set())) \
            or func in funcs
        # junit 里 Java 单测按类名（UpControllerTest）记录；Python 按函数名
        java_cls = java_cls_name if java_covered else ""
        names = ([java_cls] if java_cls else []) + ([func] if not java_cls else [])
        exe, ev = evidence_of(names, has_test)
        # 证据标签指向函数实际所在文件（test_unit_py.py 或 test_rules.py 静态层）
        py_label = _file_of_func(func) or sct_ids.RULES_FALLBACK_FILENAME
        test_label = (f"{java_cls_name}.java" if java_covered
                      else (f"{py_label}::{func}" if has_test else "—"))
        rows.append({
            "req": r.get("derived_from") or source_spec,
            "ac": r["id"], "kind": "RULE",
            "desc": (r.get("text", "") or "")[:40],
            "test": test_label,
            "execution": exe, "evidence": ev,
        })

    # ---- acceptance scenarios ----
    for feat in spec.get("features", []):
        for sc in feat.get("acceptance_scenarios", []):
            func = sct_ids.scenario_test_func(sc.get("id", ""))
            has_test = sc.get("id") in test_cov.get("scenarios", set()) or func in funcs
            exe, ev = evidence_of([func], has_test)
            # 证据标签指向函数实际所在文件（v2.5.2，与 RULE 行同规则）
            sc_label = _file_of_func(func) or "test_scenarios.py"
            rows.append({
                "req": f"{feat.get('id', '')} {feat.get('name', '')}".strip(),
                "ac": sc.get("id", "?"), "kind": "SCENARIO",
                "desc": (sc.get("then", "") or "")[:40],
                "test": f"{sc_label}::{func}" if has_test else "—",
                "execution": exe, "evidence": ev,
            })
    return rows


def render_traceability_section(rows: List[dict]) -> List[str]:
    """追溯矩阵渲染为 markdown 行"""
    L = ["## 需求追溯矩阵（REQ → AC → TEST → EXECUTION → EVIDENCE）", ""]
    if not rows:
        L.append("> 契约中没有可追溯的条目。")
        L.append("")
        return L
    counts = {v: sum(1 for r in rows if r["evidence"] == v)
              for v in ("PASS", "BLOCK", "UNPROVEN")}
    L.append(f"> 共 {len(rows)} 条契约条目：证据 PASS {counts['PASS']} · "
             f"BLOCK {counts['BLOCK']} · UNPROVEN {counts['UNPROVEN']}。"
             f"BLOCK/UNPROVEN 条目即需要人工处置的缺口。")
    L.append("")
    L.append("| REQ 来源 | AC ID | 类型 | 说明 | TEST | EXECUTION | EVIDENCE |")
    L.append("|----------|-------|------|------|------|-----------|----------|")
    icon = {"PASS": "✅", "BLOCK": "❌", "UNPROVEN": "⚠️"}
    for r in rows:
        L.append(f"| {r['req'] or '—'} | {r['ac']} | {r['kind']} | {r['desc']} "
                 f"| `{r['test']}` | {r['execution']} "
                 f"| {icon.get(r['evidence'], '')} {r['evidence']} |")
    L.append("")
    return L


# =====================================================================
# 详细测试报告渲染（模板：templates/consistency-report-template.md）
# =====================================================================

def render_test_report(spec: dict, issues: List[dict], stats: dict,
                       jacoco: dict | None, incr: dict | None,
                       junit: Dict[str, str] | None, impact_pri: Dict[str, str],
                       test_cov: Dict[str, Set[str]], intent_missing: List[str],
                       intent_total: int, meta: dict, gates: List[dict],
                       declarations: List[str] | None = None) -> Tuple[str, str]:
    """渲染详细测试报告 markdown → (报告文本, 三态结论 PASS/BLOCK/UNPROVEN)"""
    now = datetime.now().isoformat(timespec="seconds")
    declarations = declarations or []
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

    L.append("# SCT 测试报告（一致性 × 覆盖率 × 执行情况 × 缺陷 × 变更影响）")
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
    # ---- 报告产物索引：本次测试流产出的全部报告，串起各维度供人工查阅 ----
    L.append("**测试报告产物索引**：")
    L.append("")
    L.append("| 维度 | 产物 | 位置 |")
    L.append("|------|------|------|")
    L.append(f"| 本报告（单测+接口+覆盖率+缺陷+漂移） | test-report.md | `{meta.get('report', '') or '--report'}` |")
    L.append(f"| 测试计划 | acceptance.yaml | `{meta.get('spec', '')}` |")
    L.append(f"| 变更影响分析 | change-impact.md | `{meta.get('impact', '') or '（未提供 --impact）'}` |")
    L.append(f"| 覆盖映射（spec→test） | COVERAGE_REPORT.md | `{meta.get('tests', '')}/COVERAGE_REPORT.md` |")
    L.append(f"| 功能测试案例（正/反例） | E2E_TESTCASES.md | `e2e/auto_generated/E2E_TESTCASES.md` |")
    L.append(f"| Playwright 脚本 | `*.spec.js` | `e2e/auto_generated/` |")
    L.append(f"| 场景未实现清单（UNPROVEN） | _scenario_gaps.json | `{meta.get('tests', '')}/_scenario_gaps.json` |")
    L.append("")

    # ---- 摘要指标（结论部分再汇总）----
    incr_line_pct = "N/A"
    if incr and incr['counters'].get('LINE'):
        m, c = incr['counters']['LINE']
        incr_line_pct = pct(m, c)
    api_pass = api_fail = api_skip = api_total = 0
    if junit:
        api_pass, api_fail, api_skip, api_total = summarize_exec(junit_status_by_prefix(junit, "test_api_"))

    # ===== 1. 执行摘要（四维证据 × 三态门禁，P0-3）=====
    verdict = overall_verdict(gates)
    L.append("## 1. 执行摘要")
    L.append("")
    L.append("> Quality Profile（P0-4）：**`" + (meta.get("profile", DEFAULT_PROFILE)) + "`** 档"
             "（覆盖率门禁 ≥ " + str(meta.get("profile_coverage", 90)) + "%）")
    L.append("")
    # v2.5.2 可信度分级（呈现层）：声明范围/盲区让"证据 PASS"与"范围 PASS"可区分，
    # 不改变任何判定逻辑与退出码
    if declarations:
        L.append("> **范围声明**（本次结论含以下声明，评审时请先读）：")
        L.append(">")
        for d in declarations:
            L.append(f"> - {d}")
        if verdict == "PASS":
            L.append("> - ⚠️ 本次 PASS 为**含声明的 PASS**：被声明跳过/降级的维度没有证据，"
                     "不等于已验证。")
        L.append("")
    L.append("| 维度 | 证据项 | 判定 | 说明 |")
    L.append("|------|--------|------|------|")
    for g in gates:
        L.append(f"| {g.get('dimension', '—')} | {g['id']} | {VERDICT_ICON[g['verdict']]} | {g['detail']} |")
    if cg_src:
        L.append(f"| — | 字段级漂移 (FIELD_DRIFT) | ➖ 参考 | {len(cg_drifts)} 个（建议 0，不阻塞放行） |")
    L.append(f"| **—** | **总结论** | **{VERDICT_ICON[verdict]}** | 取全部证据项最严判定 |")
    L.append("")
    if verdict == "UNPROVEN":
        L.append("> ⚠️ **UNPROVEN 不是 PASS**：存在未验证的证据项（见上表），"
                 "补齐证据（--junit / --jacoco + --base）后重跑方可放行。")
        L.append("")

    # ===== 1.5 需求追溯矩阵（P0-2：REQ → AC → TEST → EXECUTION → EVIDENCE）=====
    source_spec = (spec.get("_meta") or {}).get("source_spec", "") or meta.get("spec", "")
    trace_rows = build_traceability_matrix(spec, test_cov, junit, source_spec)
    L.extend(render_traceability_section(trace_rows))

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
        num = sct_ids.id_suffix(a["id"])  # P0-4: 末段匹配，与生成文件名 test_api_<suffix>.py 一致
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

    # ===== 6.4 绑定漂移（design 阶段 BINDING_DRIFT 遗留；v2.5.1 起进统一报告）=====
    # 生成器在 design 阶段发现 SoT ↔ 代码公共契约的分歧（方法缺失/签名不匹配/缺输入/
    # mock 未打桩）。这是"分歧是信号"原则的报告级落点：评审者在 testing.run 报告里
    # 就能看到，不必回翻 design 的 stdout。不改变门禁结论（信号 ≠ 判决）。
    binding_drifts = ((meta.get("codegen_meta") or {}).get("binding_drifts")) or []
    L.append("### 6.4 绑定漂移（design 阶段遗留，需人工裁决）")
    L.append("")
    if binding_drifts:
        L.append(f"> 共 {len(binding_drifts)} 处（testing.design 生成时发现）。"
                 "每处都需人工裁决：改 SoT 或改代码——两种修正都必须追溯到需求。")
        L.append("")
        L.append("| 规则 | 目标 | 类型 | 说明 |")
        L.append("|------|------|------|------|")
        for d in binding_drifts:
            L.append(f"| {d.get('rule', '')} | {d.get('class', '')}.{d.get('method', '')} "
                     f"| {d.get('kind', '')} | {d.get('detail', '')} |")
    else:
        L.append("> 无（design 阶段未发现 SoT 与代码公共契约的绑定分歧）。")
    L.append("")

    # ===== 6.5 缺陷汇总（执行失败 + 漂移 + 未实现，统一成缺陷清单供人工跟进）=====
    L.append("### 6.5 缺陷汇总")
    L.append("")
    defects: List[tuple] = []  # (缺陷类型, 关联对象, 说明)
    if junit:
        for n, s in junit.items():
            if s in ("FAIL", "ERROR"):
                defects.append(("执行失败", n, s))
    for i in issues:
        if i["severity"] == "HIGH":
            defects.append(("漂移-HIGH", i.get("type", ""), i.get("message", "")))
        elif i["severity"] == "MEDIUM":
            defects.append(("漂移-MEDIUM", i.get("type", ""), i.get("message", "")))
    if defects:
        L.append(f"> 共 **{len(defects)}** 处缺陷/问题（执行失败 {sum(1 for d in defects if d[0]=='执行失败')} 处，"
                 f"漂移 {sum(1 for d in defects if d[0].startswith('漂移'))} 处）。"
                 f"每个缺陷应由人工确认并关联缺陷单。")
        L.append("")
        L.append("| # | 缺陷类型 | 关联对象 | 说明 | 缺陷单（人工填写） |")
        L.append("|---|----------|----------|------|---------------------|")
        for idx, (kind, obj, desc) in enumerate(defects, 1):
            L.append(f"| {idx} | {kind} | {obj} | {desc} | |")
        L.append("")
    else:
        L.append("> 未发现执行失败或漂移。")
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
    verdict = overall_verdict(gates)
    L.append(f"- **最终结论**: {VERDICT_ICON[verdict]}"
             + ("（可合入）" if verdict == "PASS"
                else "（先消除 BLOCK 项再合入）" if verdict == "BLOCK"
                else "（证据不足，补齐 --junit / --jacoco + --base 后重跑；UNPROVEN ≠ PASS）"))
    L.append("")
    L.append("> BLOCK 处置路径：先归因断掉的环节（漏测/意图缺失→`testing.design` 重生成；未实现→补实现；"
             "覆盖率→补用例；手改→`testing.design --force`）→ 重跑 `testing.run`。改契约（acceptance.yaml）"
             "需连带改 spec 后重新生成。")
    return "\n".join(L), verdict


def print_summary(issues: List[dict], stats: dict, report_path: str | None,
                  verdict: str, gates: List[dict] | None = None,
                  declarations: List[str] | None = None):
    """终端摘要（详细内容看报告文件）；返回三态退出码 0/1/2"""
    print("=" * 60)
    print("三方一致性校验摘要（三态门禁）")
    print("=" * 60)
    print(f"API 覆盖率: {stats['api_coverage']:.1f}% (目标 {stats['api_target']}%)")
    print(f"规则覆盖率: {stats['rule_coverage']:.1f}% (目标 {stats['rule_target']}%)")
    if not issues:
        print("✓ 无漂移，spec/code/test 三方一致")
    else:
        high_count = sum(1 for i in issues if i["severity"] == "HIGH")
        print(f"发现 {len(issues)} 个漂移（HIGH {high_count} 个），详见报告")
    if gates:
        for g in gates:
            print(f"  [{VERDICT_ICON[g['verdict']]}] [{g.get('dimension', '—')}] {g['id']}: {g['detail']}")
    # v2.5.2 可信度分级（呈现层）：声明范围让 PASS 的证据成色可读，不改判定/退出码
    declarations = declarations or []
    if declarations:
        print(f"\n范围声明（{len(declarations)} 项，被声明跳过/降级的维度没有证据）：")
        for d in declarations:
            print(f"  ⚑ {d}")
    print(f"\n总结论: {VERDICT_ICON.get(verdict, verdict)}")
    if verdict == "PASS" and declarations:
        print("      （含声明范围——被声明维度的缺口不在此体现，评审请先读范围声明）")
    if report_path:
        print(f"📄 详细测试报告: {report_path}")
    return verdict_exit_code(verdict)


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
        print("      a) 先修环境（启动服务/换 BASE_URL），再重跑 testing.run")
        print("      b) 跳过接口层：`testing.run --skip-api-tests ...`")
        return 3
    print()
    print("⚠️  [prereq] 接口测试缺前：")
    print(f"    - BASE_URL 不可达：{detail or '服务未监听'}")
    print("    - API_AUTH_TOKEN 未设")
    print("    接口层（L2）与实现语言无关（v2.5）：任何能本地起服务的项目都可测——")
    print("    Python `uvicorn app:app` / `python manage.py runserver`，Java `mvn spring-boot:run`")
    print("    或 `gradle bootRun`/`java -jar`，非标准工程起你的启动脚本即可；服务起来后重跑。")
    print("    在对话框确认输入：")
    print("      1) 提供 token / 修环境后再跑：`export API_AUTH_TOKEN=...` 后重跑 testing.run")
    print("      2) 跳过接口层：`testing.run --skip-api-tests ...`")
    return 3


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", required=True)
    parser.add_argument("--code", required=True)
    parser.add_argument("--tests", required=True)
    parser.add_argument("--scope", default="all",
                        help="Controller 名字关键字过滤；'all'（默认）= 扫描全部 controller")
    parser.add_argument("--jacoco", help="覆盖率 XML 路径（总体+增量覆盖率）。语言中立（v2.5）："
                                         "Java 用 JaCoCo jacoco.xml；Python 用 coverage.py 的 `coverage xml`（cobertura 格式），自动识别")
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
    parser.add_argument("--profile", default=DEFAULT_PROFILE,
                        help="Quality Profile（P0-4）：fast|standard|strict——"
                             "决定覆盖率门槛与测试完整性要求（默认 standard=90%）")
    parser.add_argument("--prereq-timeout", type=float, default=3.0,
                        help="API 测试预检 BASE_URL 可达性的超时（秒），默认 3")
    parser.add_argument("--module", default="",
                        help="F-17：微服务模块名；默认拼接 {code}/{module}/src/main/java 作为源码根"
                             "（源码位置可用 --module-src 覆盖）")
    parser.add_argument("--module-src", default="",
                        help="F-17：模块内源码相对路径（默认 src/main/java；源码在 src/main/kotlin "
                             "或自定义目录时用）")
    # v2.3 防空洞维度（测试有效性）：提供任一旗标即在门禁中激活
    parser.add_argument("--surefire", help="surefire-reports 目录（Java 真实执行报告）→ REAL_TESTS 真实执行数入门禁")
    parser.add_argument("--tasks", help="tasks.md 路径 → PHANTOM_TASK 幻影任务入门禁（声称完成但代码无证据）")
    parser.add_argument("--verify-compile", action="store_true",
                        help="开启编译门 COMPILE（mvn/gradle test-compile）；内网无构建环境时勿开")
    parser.add_argument("--compile-timeout", type=int, default=300,
                        help="编译门超时（秒），默认 300")
    parser.add_argument("--trace-json",
                        help="追溯矩阵 + 门禁结论的结构化 JSON 输出路径（CI/看板可消费）")
    args = parser.parse_args()

    spec = load_acceptance(Path(args.spec))

    # v2.4：契约校验命令级强制（P0 遗留风险收口）——不再依赖命令文件约定
    # 「先跑 contract-validate」，坏契约在门禁入口直接 BLOCK（退出码 1）。
    cv_problems, cv_warnings = _load_contract_validate().validate(
        spec if isinstance(spec, dict) else {})
    if cv_warnings:
        for w in cv_warnings:
            print(f"⚠️  契约完整性提示: {w}")
    if cv_problems:
        print("=" * 60)
        print("❌ CONTRACT 校验 BLOCK——契约存在结构性错误，门禁入口直接阻断")
        for x in cv_problems:
            print(f"  - {x}")
        print("=" * 60)
        sys.exit(1)
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
        # v2.5.1：design 阶段绑定漂移进 run 摘要（报告 §6.4 同步）
        bdn = len(codegen_meta.get("binding_drifts") or [])
        if bdn:
            print(f"⚠️  绑定漂移（design 阶段遗留）{bdn} 个——详见报告「6.4 绑定漂移」，需人工裁决 SoT 还是代码")

    # P0-4：Quality Profile 决定覆盖率门槛（在 meta 构造之前确定）
    profile = (args.profile or DEFAULT_PROFILE).lower()
    if profile not in PROFILES:
        print(f"⚠️  未知 profile `{profile}`，回退 {DEFAULT_PROFILE}（可选: {'/'.join(PROFILES)}）")
        profile = DEFAULT_PROFILE
    coverage_target = profile_coverage(profile)

    # v2.5.2 可信度分级：收集声明范围/盲区（呈现层——进报告 §1、终端摘要与 trace.json，
    # 让"证据 PASS"与"范围 PASS"可区分；不改变任何判定与退出码）
    declarations: List[str] = []
    if args.skip_api_tests:
        declarations.append("--skip-api-tests：接口层执行与覆盖率维度不判定（声明范围）")
    if args.skip_rule_tests:
        declarations.append("--skip-rule-tests：单测层跳过，真实执行数不判定（声明范围）")
    if ((spec.get("_meta") or {}).get("impl_evidence") or "routes").lower() == "none":
        declarations.append("impl_evidence=none：路由级实现核对降级为人工核对（声明盲区，"
                            "接口层真实执行证据仍然把关）")

    meta = {"spec": args.spec, "code": str(code_root), "tests": args.tests,
            "base": args.base if jacoco else "N/A", "jacoco": args.jacoco or "",
            "mode": mode, "codegen_meta": codegen_meta,
            "impact": args.impact or "", "report": args.report or "",
            "profile": profile, "profile_coverage": coverage_target}

    # 契约追溯矩阵（P0-2）→ 四维门禁评估（P0-3）
    source_spec = (spec.get("_meta") or {}).get("source_spec", "") or args.spec
    trace_rows = build_traceability_matrix(spec, test_cov, junit, source_spec)
    gates = evaluate_gates(issues, junit, incr, coverage_target,
                           skip_api_tests=args.skip_api_tests,
                           tests_root=Path(args.tests), codegen_meta=codegen_meta,
                           trace_rows=trace_rows, intent_missing=intent_missing,
                           profile=profile,
                           tasks_path=args.tasks, surefire_dir=args.surefire,
                           verify_compile=args.verify_compile,
                           compile_timeout=args.compile_timeout,
                           skip_rule_tests=args.skip_rule_tests,
                           code_root=str(code_root))
    verdict = overall_verdict(gates)

    # 落盘详细报告 + 终端摘要
    report_path = None
    if args.report:
        report, verdict = render_test_report(
            spec, issues, stats, jacoco, incr, junit, impact_pri,
            test_cov, intent_missing, intent_total, meta, gates,
            declarations=declarations)
        rp = Path(args.report)
        rp.parent.mkdir(parents=True, exist_ok=True)
        rp.write_text(report, encoding="utf-8")
        report_path = str(rp)

    # v2.4：追溯矩阵 JSON 导出（--trace-json）——CI/看板可直接消费，
    # 不再只依赖 markdown 报告表格
    if args.trace_json:
        payload = {
            "source_spec": source_spec, "profile": profile,
            "coverage_target": coverage_target, "verdict": verdict,
            "gates": gates, "items": trace_rows,
            "binding_drifts": (codegen_meta or {}).get("binding_drifts") or [],
            "declarations": declarations,
        }
        tj = Path(args.trace_json)
        tj.parent.mkdir(parents=True, exist_ok=True)
        tj.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str),
                      encoding="utf-8")
        print(f"📄 追溯矩阵 JSON: {tj}")

    sys.exit(print_summary(issues, stats, report_path, verdict, gates,
                           declarations=declarations))


if __name__ == "__main__":
    main()
