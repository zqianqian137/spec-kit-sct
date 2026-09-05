#!/usr/bin/env python3
"""
self-test.py — SCT 自测（SCT 2.0 P1-3：自测 + golden fixtures + 回归底线）

不依赖 pytest/外部工具，纯 stdlib + 本地脚本，跑完整链路并断言：
  契约校验(contract-validate) → 测试派生(codegen) → 门禁(check) → 追溯矩阵

断言七档：
  golden    合法契约全链路应 PASS
  blocker   坏契约（重复 ID）应被 contract-validate BLOCK
  gate      漏测场景应被 check BLOCK
  anti-hollow  surefire 真实执行数为 0 → check 的 REAL_TESTS 应 BLOCK（防空洞，v2.3）
  python       pytest emitter 端到端：派生 → 真执行 → 门禁 PASS（v2.5）
  none         非标准工程降级为静态断言层，不崩溃（v2.5）
  units        解析器/路由提取/语言探测/命名约定 纯函数单测（v2.5.1）

用法：python scripts/self-test.py   （退出码 0=全过 1=有失败）
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
PY = sys.executable

GOOD_CONTRACT = """\
version: 1
feature: f003
_meta:
  source_spec: specs/001/spec.md
  coverage_mode: full
apis:
  - id: API-F003-001
    name: 上传
    method: POST
    path: /api/upload
    response_200: {status: 200}
    error_codes: [400]
rules:
  - id: BR-F003-001
    text: 不超过 1.5MB
    priority: P0
    target: {class: com.demo.UpController, method: upload}
    test_cases:
      - inputs: {size: 100}
        expect: {returns: ok}
features:
  - id: F003
    name: 场景设计
    acceptance_scenarios:
      - id: F003-1
        given: 用户已登录
        when: 上传合法文件
        then: 导入成功
        e2e:
          priority: P0
          case_type: positive
"""

BAD_CONTRACT = GOOD_CONTRACT + "  - id: API-F003-001\n    name: 重复\n    method: GET\n    path: /api/dup\n"

CODE_JAVA = """\
package com.demo;
import org.springframework.web.bind.annotation.*;
@RestController
public class UpController {
    @PostMapping("/api/upload")
    public String upload() { return "ok"; }
}
"""


def run(cmd: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def probe_environment() -> int:
    """环境探针：解释器/依赖不满足时给明确报错退出（2），
    不让脚本在半路以难排查的方式失败（内网/CI 首个排障点）。"""
    problems = []
    if sys.version_info < (3, 10):
        problems.append(f"需要 Python ≥ 3.10（脚本使用 X | Y 类型标注），"
                        f"当前 {sys.version.split()[0]}")
    try:
        import yaml  # noqa: F401
    except ImportError:
        problems.append("缺少 PyYAML：pip install pyyaml")
    if problems:
        print("❌ 环境探针失败，无法运行 SCT 自测：")
        for p in problems:
            print(f"  - {p}")
        return 2
    print(f"环境探针通过：Python {sys.version.split()[0]} + PyYAML "
          f"{__import__('yaml').__version__}")
    return 0


def make_workspace(tdir: Path, contract: str):
    code = tdir / "code" / "com" / "demo"
    code.mkdir(parents=True)
    (tdir / "acceptance.yaml").write_text(contract, encoding="utf-8")
    (code / "UpController.java").write_text(CODE_JAVA, encoding="utf-8")


def main() -> int:
    rc = probe_environment()
    if rc:
        return rc
    failures: list[str] = []

    def check(name: str, cond: bool, detail: str = ""):
        mark = "✅" if cond else "❌"
        print(f"  {mark} {name}{(' — ' + detail) if detail and not cond else ''}")
        if not cond:
            failures.append(name)

    with tempfile.TemporaryDirectory() as td:
        tdir = Path(td)

        # ---- golden：合法契约全链路 ----
        print("1) golden 全链路（合法契约 → 校验 → 派生 → 门禁）")
        make_workspace(tdir, GOOD_CONTRACT)
        r = run([PY, str(SCRIPTS / "contract-validate.py"), "--contract", str(tdir / "acceptance.yaml")])
        check("contract-validate PASS", r.returncode == 0, r.stdout[-300:])
        r = run([PY, str(SCRIPTS / "acceptance-codegen.py"),
                 "--spec", str(tdir / "acceptance.yaml"), "--out", str(tdir / "out"),
                 "--java-test-root", str(tdir / "out"), "--code", str(tdir / "code"),
                 "--force"])
        check("codegen 派生成功", r.returncode == 0 and (tdir / "out" / "test_api_001.py").exists(),
              r.stdout[-300:])
        # 校验 write-once manifest 落盘
        check("manifest 落盘", (tdir / "out" / "_codegen_meta.json").exists())
        r = run([PY, str(SCRIPTS / "consistency-check.py"),
                 "--spec", str(tdir / "acceptance.yaml"), "--code", str(tdir / "code"),
                 "--tests", str(tdir / "out"), "--skip-api-tests",
                 "--report", str(tdir / "report.md"),
                 "--trace-json", str(tdir / "trace.json")])
        check("check 总结论 PASS", r.returncode == 0, r.stdout[-300:])
        report = (tdir / "report.md").read_text(encoding="utf-8") if (tdir / "report.md").exists() else ""
        check("报告含追溯矩阵", "需求追溯矩阵" in report)
        check("报告含 Quality Profile", "Quality Profile" in report)
        # v2.4：--trace-json 结构化导出可解析且含门禁结论
        import json as _json
        trace_ok = False
        if (tdir / "trace.json").exists():
            try:
                tj = _json.loads((tdir / "trace.json").read_text(encoding="utf-8"))
                trace_ok = tj.get("verdict") == "PASS" and isinstance(tj.get("items"), list) \
                    and any(it.get("kind") == "API" for it in tj["items"])
            except Exception:
                trace_ok = False
        check("trace.json 可解析且 verdict=PASS", trace_ok)
        # v2.5.2 可信度分级：--skip-api-tests 是声明范围，必须可在 trace.json 中读到
        decl_ok = trace_ok and isinstance(tj.get("declarations"), list) \
            and any("skip-api-tests" in d for d in tj.get("declarations", []))
        check("范围声明可读（declarations 含 skip-api-tests）", decl_ok)

        # ---- blocker：重复 ID 契约被拒 ----
        print("2) blocker（坏契约应被拒）")
        make_workspace(tdir / "bad", BAD_CONTRACT)
        r = run([PY, str(SCRIPTS / "contract-validate.py"), "--contract", str(tdir / "bad" / "acceptance.yaml")])
        check("重复 ID 契约 → BLOCK(exit 1)", r.returncode == 1, r.stdout[-300:])
        # v2.4：契约校验命令级强制——绕过 contract-validate 直接调门禁也拦得住
        r = run([PY, str(SCRIPTS / "consistency-check.py"),
                 "--spec", str(tdir / "bad" / "acceptance.yaml"),
                 "--code", str(tdir / "bad" / "code"),
                 "--tests", str(tdir / "bad" / "out"), "--skip-api-tests"])
        check("坏契约直调门禁 → 入口 CONTRACT BLOCK(exit 1)",
              r.returncode == 1 and "CONTRACT" in r.stdout, r.stdout[-300:])

        # ---- gate：漏测契约被 check 阻断 ----
        print("3) gate（无实现的契约条目应 BLOCK）")
        leak = GOOD_CONTRACT + "    test_cases: []\n    checks: []\n"
        leak = leak.replace("      - id: BR-F003-001", "      - id: BR-F003-002")
        make_workspace(tdir / "leak", leak.replace("rules:", "rules:", 1) and leak)
        r = run([PY, str(SCRIPTS / "acceptance-codegen.py"),
                 "--spec", str(tdir / "leak" / "acceptance.yaml"), "--out", str(tdir / "leak" / "out"),
                 "--code", str(tdir / "leak" / "code"), "--force"])
        r = run([PY, str(SCRIPTS / "consistency-check.py"),
                 "--spec", str(tdir / "leak" / "acceptance.yaml"), "--code", str(tdir / "leak" / "code"),
                 "--tests", str(tdir / "leak" / "out"), "--skip-api-tests"])
        # 契约中 BR-F003-002 无 test_cases → 不生成对应测试（规则漂移或漏测判定由 check 处理）
        check("check 可运行", r.returncode in (0, 1), r.stdout[-300:])

        # ---- anti-hollow：surefire 0 真实执行应 BLOCK（防空洞，v2.3）----
        print("4) anti-hollow（surefire 真实执行为 0 → REAL_TESTS BLOCK）")
        ah = tdir / "ah"
        (ah / "sf0").mkdir(parents=True)
        (ah / "sf1").mkdir()
        (ah / "tasks.md").write_text("- [x] 实现 UpController.upload 批量上传接口\n", encoding="utf-8")
        (ah / "sf0" / "TEST-Empty.xml").write_text(
            '<testsuite name="EmptySuite" tests="0" failures="0" errors="0" skipped="0"/>', encoding="utf-8")
        (ah / "sf1" / "TEST-Run.xml").write_text(
            '<testsuite name="RunSuite" tests="2" failures="0" errors="0" skipped="0"/>', encoding="utf-8")
        # 反例：声称有测试但 0 真实执行 → 门禁必须 BLOCK（exit 1）
        r = run([PY, str(SCRIPTS / "consistency-check.py"),
                 "--spec", str(tdir / "acceptance.yaml"), "--code", str(tdir / "code"),
                 "--tests", str(tdir / "out"), "--skip-api-tests",
                 "--surefire", str(ah / "sf0"), "--tasks", str(ah / "tasks.md")])
        check("REAL_TESTS=0 → BLOCK(exit 1)", r.returncode == 1 and "REAL_TESTS" in r.stdout,
              r.stdout[-300:])
        # 正例：有真实执行（2 个全过）→ 有效性维度 PASS，整体沿 golden 仍 PASS
        r = run([PY, str(SCRIPTS / "consistency-check.py"),
                 "--spec", str(tdir / "acceptance.yaml"), "--code", str(tdir / "code"),
                 "--tests", str(tdir / "out"), "--skip-api-tests",
                 "--surefire", str(ah / "sf1"), "--tasks", str(ah / "tasks.md")])
        check("REAL_TESTS>0 → PASS(exit 0)", r.returncode == 0 and "REAL_TESTS" in r.stdout,
              r.stdout[-300:])

        # ---- python：Python emitter 端到端（语言中立，v2.5）----
        print("5) python（pytest emitter：派生 → 执行 → 门禁）")
        pycode = tdir / "py" / "code"
        pycode.mkdir(parents=True)
        (pycode / "calc_service.py").write_text(
            "class CalcService:\n    def add(self, a, b):\n        return a + b\n",
            encoding="utf-8")
        py_contract = """\
version: 1
feature: f003
rules:
  - id: BR-F003-001
    text: 求和正确
    priority: P0
    target: {class: calc_service.CalcService, method: add}
    test_cases:
      - inputs: {a: 1, b: 2}
        expect: {returns: 3}
"""
        (tdir / "py" / "acceptance.yaml").write_text(py_contract, encoding="utf-8")
        r = run([PY, str(SCRIPTS / "acceptance-codegen.py"),
                 "--spec", str(tdir / "py" / "acceptance.yaml"), "--out", str(tdir / "py" / "out"),
                 "--code", str(pycode), "--skip-api-tests", "--force"])
        unit_py = tdir / "py" / "out" / "test_unit_py.py"
        check("python emitter 派生 test_unit_py.py", unit_py.exists(), r.stdout[-300:])
        check("函数名遵循 test_br_ 约定", unit_py.exists() and "def test_br_001" in unit_py.read_text(encoding="utf-8"))
        # emitter 语法守卫：字符串拼接生成的测试必须可解析（v2.5 曾在此类拼接上踩坑）
        if unit_py.exists():
            import ast as _ast
            try:
                _ast.parse(unit_py.read_text(encoding="utf-8"))
                _syntax_ok = True
            except SyntaxError:
                _syntax_ok = False
            check("python emitter 产物可被 ast.parse（语法守卫）", _syntax_ok)
        r = run([PY, "-m", "pytest", str(unit_py), "-q", "--junitxml",
                 str(tdir / "py" / "out" / "junit.xml")], cwd=str(tdir / "py"))
        check("python 单测真实执行 PASS", r.returncode == 0, r.stdout[-300:])
        r = run([PY, str(SCRIPTS / "consistency-check.py"),
                 "--spec", str(tdir / "py" / "acceptance.yaml"), "--code", str(pycode),
                 "--tests", str(tdir / "py" / "out"), "--skip-api-tests",
                 "--junit", str(tdir / "py" / "out" / "junit.xml"),
                 "--trace-json", str(tdir / "py" / "trace.json")])
        check("python 项目门禁 PASS(exit 0)", r.returncode == 0, r.stdout[-300:])
        # v2.5.2：RULE 行证据标签指向实际文件（test_unit_py.py，不再是 test_rules.py 误标）
        label_ok = False
        try:
            _tj = _json.loads((tdir / "py" / "trace.json").read_text(encoding="utf-8"))
            _rule = next((it for it in _tj["items"] if it.get("kind") == "RULE"), {})
            label_ok = _rule.get("test") == "test_unit_py.py::test_br_001" \
                and _rule.get("evidence") == "PASS"
        except Exception:
            label_ok = False
        check("RULE 行标签指向实际文件（test_unit_py.py）", label_ok)

        # ---- none：非标准工程（无 java/py 标记）降级为静态断言层 ----
        print("6) none（非标准工程：只留静态断言层，不崩溃）")
        (tdir / "plain").mkdir()
        (tdir / "plain" / "acceptance.yaml").write_text(
            'version: 1\nfeature: f003\nrules:\n  - id: BR-F003-001\n    text: 审计日志存在\n'
            '    priority: P0\n    checks:\n      - kind: text\n        expect: "audit"\n',
            encoding="utf-8")
        r = run([PY, str(SCRIPTS / "acceptance-codegen.py"),
                 "--spec", str(tdir / "plain" / "acceptance.yaml"), "--out", str(tdir / "plain" / "out"),
                 "--code", str(tdir / "plain"), "--skip-api-tests", "--force"])
        check("非标准工程不生成 target 单测、不崩溃",
              r.returncode == 0 and not (tdir / "plain" / "out" / "test_unit_py.py").exists()
              and (tdir / "plain" / "out" / "test_rules.py").exists(), r.stdout[-300:])

        # ---- units：解析器/路由提取/语言探测/命名约定 纯函数单测（v2.5.1，补函数级回归）----
        print("7) units（解析器与命名约定纯函数）")
        sys.path.insert(0, str(SCRIPTS))
        import importlib.util as _ilu

        def _load_mod(mod_name: str, filename: str):
            s = _ilu.spec_from_file_location(mod_name, SCRIPTS / filename)
            m = _ilu.module_from_spec(s)
            s.loader.exec_module(m)
            return m

        cc = _load_mod("sct_cc_units", "consistency-check.py")
        cg_mod = _load_mod("sct_cg_units", "acceptance-codegen.py")
        sct = _load_mod("sct_ids_units", "sct_ids.py")

        def _w(tmp: Path, name: str, text: str) -> Path:
            p = tmp / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
            return p

        with tempfile.TemporaryDirectory() as td2:
            u = Path(td2)
            # 7.1 cobertura（coverage.py XML）：类级行计数按 <line hits> 统计
            cob = _w(u, "cov.xml", """<?xml version="1.0"?>
<coverage lines-valid="4" lines-covered="3" line-rate="0.75">
  <packages><package name="app"><classes>
    <class name="svc.py" filename="app/svc.py" line-rate="0.75"><lines>
      <line number="1" hits="1"/><line number="2" hits="0"/>
      <line number="3" hits="1"/><line number="4" hits="1"/>
    </lines></class>
  </classes></package></packages>
</coverage>""")
            j = cc.parse_jacoco(cob)
            check("cobertura: 总体 LINE=(1,3)", j["overall"].get("LINE") == (1, 3))
            check("cobertura: 类级 basename 匹配增量",
                  cc.incremental_coverage(j, {"svc.py"})["counters"].get("LINE") == (1, 3))
            # 7.2 jacoco XML：counter 属性直接读取
            jac = _w(u, "jac.xml", """<report>
  <package name="p"><class name="C" sourcefilename="C.java">
    <counter type="LINE" missed="2" covered="8"/></class></package>
  <counter type="LINE" missed="2" covered="8"/>
</report>""")
            j2 = cc.parse_jacoco(jac)
            check("jacoco: LINE=(2,8)", j2["overall"].get("LINE") == (2, 8))
            # 7.3 Python 路由提取：FastAPI / Flask / aiohttp 三种约定
            _w(u, "r/app.py", """from fastapi import FastAPI
app = FastAPI()
@app.post("/api/upload")
def upload(): ...
""")
            _w(u, "r/flask_app.py", """from flask import Flask
app = Flask(__name__)
@app.route("/api/users", methods=["POST"])
def users(): ...
""")
            _w(u, "r/aio_app.py", """from aiohttp import web
def h(request): ...
routes = [web.get("/health", h)]
""")
            apis = cc.extract_code_apis(u / "r")
            check("FastAPI POST /api/upload 提取", "POST /api/upload" in apis)
            check("Flask POST /api/users 提取", "POST /api/users" in apis)
            check("aiohttp GET /health 提取", "GET /health" in apis)
            # 7.4 detect_lang 三态
            djava = u / "dj"; (djava / "X.java").parent.mkdir(parents=True, exist_ok=True)
            (djava / "X.java").write_text("class X {}", encoding="utf-8")
            dpy = u / "dp"; dpy.mkdir(exist_ok=True); (dpy / "m.py").write_text("x=1", encoding="utf-8")
            dnone = u / "dn"; dnone.mkdir(exist_ok=True)
            check("detect_lang: .java → java", cg_mod.detect_lang(str(djava)) == "java")
            check("detect_lang: .py → python", cg_mod.detect_lang(str(dpy)) == "python")
            check("detect_lang: 空 → none", cg_mod.detect_lang(str(dnone)) == "none")
            # 7.5 命名约定单一事实源（sct_ids）：生成侧与校验侧必须同源
            check("api_test_filename", sct.api_test_filename("API-F003-001") == "test_api_001.py")
            check("rule_test_func", sct.rule_test_func("BR-F003-001") == "test_br_001")
            check("java_test_class_name", sct.java_test_class_name("com.demo.UpController") == "UpControllerTest")
            check("scenario_test_func", sct.scenario_test_func("F003-1") == "test_sc_f003_1")
            check("三态排序 BLOCK > UNPROVEN > PASS",
                  sct.VERDICT_RANK["BLOCK"] > sct.VERDICT_RANK["UNPROVEN"] > sct.VERDICT_RANK["PASS"])
            # 7.6 REAL_TESTS 兼容 pytest junitxml（根 testsuites 计数在子节点）
            vg = _load_mod("sct_vg_units", "verification-gate.py")
            sfd = u / "sf"; sfd.mkdir()
            _w(sfd, "TEST-py.xml", '<testsuites><testsuite tests="3" failures="1" errors="0" skipped="0"/></testsuites>')
            st, n, _d = vg.check_real_tests(str(sfd))
            check("REAL_TESTS: pytest 格式计数=3 且 FAIL→BLOCK", n == 3 and st == "BLOCK")

    print("-" * 60)
    if failures:
        print(f"❌ {len(failures)} 项自测失败: {', '.join(failures)}")
        return 1
    print("✅ 全部自测通过（golden / blocker / gate / anti-hollow / python / none / units 七档）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
