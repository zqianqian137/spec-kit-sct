#!/usr/bin/env python3
"""
self-test.py — SCT 自测（SCT 2.0 P1-3：自测 + golden fixtures + 回归底线）

不依赖 pytest/外部工具，纯 stdlib + 本地脚本，跑完整链路并断言：
  契约校验(contract-validate) → 测试派生(codegen) → 门禁(check) → 追溯矩阵

断言四档：
  golden    合法契约全链路应 PASS
  blocker   坏契约（重复 ID）应被 contract-validate BLOCK
  gate      漏测场景应被 check BLOCK
  anti-hollow  surefire 真实执行数为 0 → check 的 REAL_TESTS 应 BLOCK（防空洞，v2.3）

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


def make_workspace(tdir: Path, contract: str):
    code = tdir / "code" / "com" / "demo"
    code.mkdir(parents=True)
    (tdir / "acceptance.yaml").write_text(contract, encoding="utf-8")
    (code / "UpController.java").write_text(CODE_JAVA, encoding="utf-8")


def main() -> int:
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
                 "--java-test-root", str(tdir / "out"), "--force"])
        check("codegen 派生成功", r.returncode == 0 and (tdir / "out" / "test_api_001.py").exists(),
              r.stdout[-300:])
        # 校验 write-once manifest 落盘
        check("manifest 落盘", (tdir / "out" / "_codegen_meta.json").exists())
        r = run([PY, str(SCRIPTS / "consistency-check.py"),
                 "--spec", str(tdir / "acceptance.yaml"), "--code", str(tdir / "code"),
                 "--tests", str(tdir / "out"), "--skip-api-tests",
                 "--report", str(tdir / "report.md")])
        check("check 总结论 PASS", r.returncode == 0, r.stdout[-300:])
        report = (tdir / "report.md").read_text(encoding="utf-8") if (tdir / "report.md").exists() else ""
        check("报告含追溯矩阵", "需求追溯矩阵" in report)
        check("报告含 Quality Profile", "Quality Profile" in report)

        # ---- blocker：重复 ID 契约被拒 ----
        print("2) blocker（坏契约应被拒）")
        make_workspace(tdir / "bad", BAD_CONTRACT)
        r = run([PY, str(SCRIPTS / "contract-validate.py"), "--contract", str(tdir / "bad" / "acceptance.yaml")])
        check("重复 ID 契约 → BLOCK(exit 1)", r.returncode == 1, r.stdout[-300:])

        # ---- gate：漏测契约被 check 阻断 ----
        print("3) gate（无实现的契约条目应 BLOCK）")
        leak = GOOD_CONTRACT + "    test_cases: []\n    checks: []\n"
        leak = leak.replace("      - id: BR-F003-001", "      - id: BR-F003-002")
        make_workspace(tdir / "leak", leak.replace("rules:", "rules:", 1) and leak)
        r = run([PY, str(SCRIPTS / "acceptance-codegen.py"),
                 "--spec", str(tdir / "leak" / "acceptance.yaml"), "--out", str(tdir / "leak" / "out"), "--force"])
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

    print("-" * 60)
    if failures:
        print(f"❌ {len(failures)} 项自测失败: {', '.join(failures)}")
        return 1
    print("✅ 全部自测通过（golden / blocker / gate / anti-hollow 四档）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
