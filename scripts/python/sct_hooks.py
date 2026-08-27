#!/usr/bin/env python3
"""
sct_hooks.py
============
Speckit 扩展 `sct` 的统一入口（v1.0-W2 / INTERNAL）

架构变更（W1 → W2）：
  - W1：本文件转发到外部 ai-test-platform/tools/*.py（依赖 SCT_TOOLKIT_HOME）
  - W2：本文件直接转发到本扩展自带的 scripts/*.py（自包含，零外部依赖）

W1 demo 实现：纯转发到 ai-test-platform/tools/，W2+ 可在本文件中重写。

用法（Speckit 调用）：
  python sct_hooks.py merge  --spec <path>
  python sct_hooks.py codegen --spec <path>
  python sct_hooks.py check   --spec <path> [--ai]
  python sct_hooks.py impact  --base <ref> --head <ref>
  python sct_hooks.py e2e     --impact <path>

环境变量：
  SCT_EXT_HOME        本扩展根目录（默认从本文件位置推断）
  SILICONFLOW_API_KEY LLM API key（AI 模式必填）
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path


# ====== 路径定位：扩展自包含，无需找外部 ai-test-platform ======

def find_sct_ext_home() -> Path:
    """定位本扩展根目录 ext-sct-for-speckit/extensions/sct/

    自包含设计：直接用 __file__ 向上找 marker 文件
    """
    env = os.environ.get("SCT_EXT_HOME")
    if env:
        return Path(env).resolve()

    here = Path(__file__).resolve()
    # sct_hooks.py 在 .../sct/scripts/python/sct_hooks.py
    # 扩展根在 .../sct/
    for parent in here.parents:
        if (parent / "extension.yml").exists() and (parent / "scripts").is_dir():
            return parent

    raise FileNotFoundError(
        f"无法定位 SCT 扩展根目录（找不到 extension.yml）。\n"
        f"  本文件位置: {here}\n"
        f"  请设置环境变量 SCT_EXT_HOME 指向扩展根目录。"
    )


# ====== 工具调用：subprocess 调本地 scripts/ 下的脚本 ======

def run_script(script_name: str, args: list[str]) -> int:
    """调本扩展 scripts/ 下的 python 脚本（零外部依赖）"""
    ext_home = find_sct_ext_home()
    script_path = ext_home / "scripts" / script_name
    if not script_path.exists():
        print(f"❌ 脚本不存在: {script_path}", file=sys.stderr)
        return 1

    cmd = [sys.executable, str(script_path)] + args
    print(f"🔧 [SCT-INTERNAL] {' '.join(cmd)}")
    return subprocess.call(cmd)


# ====== 5 个命令入口（与 extension.yml commands 一一对应）======

def cmd_merge(args) -> int:
    """对应 speckit.sct.merge：生成 acceptance.yaml（SoT）"""
    spec = args.spec or _latest_spec()
    out = args.out or (Path(spec).parent / "acceptance.yaml")
    extra = ["--ai"] if args.ai else []
    # 自动发现 spec 同级的 plan/api-contracts/data-model，补全 apis/rules（W2 合并）
    spec_dir = Path(spec).parent
    cli = []
    for key, name in (("plan", "plan.md"),
                      ("api-contracts", "api-contracts.md"),
                      ("data-model", "data-model.md")):
        p = spec_dir / name
        if p.exists():
            cli += [f"--{key}", str(p)]
    return run_script("spec-merge.py", [
        "--spec", spec,
        "--out", str(out),
    ] + cli + extra)


def cmd_codegen(args) -> int:
    """对应 speckit.sct.codegen：派生后端测试代码（api/rule/scenario）

    接受 --target：backend/all 走 acceptance-codegen；
    frontend/e2e 由 speckit.sct.e2e（change-impact-e2e-bridge）负责，此处不重复。

    自动探测代码根目录并透传 --code，使规则测试能在代码上做离线静态断言。
    """
    spec = args.spec or _latest_spec()
    out = args.out or (Path(spec).parent / "tests" / "generated")
    target = (args.target or "all").lower()
    if target in ("backend", "all"):
        code_root = _detect_code_root(spec)
        cli = ["--spec", spec, "--out", str(out)]
        if code_root:
            cli += ["--code", str(code_root)]
        return run_script("acceptance-codegen.py", cli)
    print(f"⚠️  codegen target={target} 不由 acceptance-codegen 处理"
          f"（前端/E2E 请走 speckit.sct.e2e）", file=sys.stderr)
    return 0


def _detect_code_root(spec) -> Path | None:
    """探测代码根目录（覆盖 Maven/前端/混合布局）；找不到返回 None"""
    spec_path = Path(spec).resolve()
    project_root = spec_path.parent.parent  # specs/<feature>/ → project root
    candidates = [
        "src", "app/src/main", "frontend/src",
        "backend/src/main/java", "src/main/java", "main/java",
    ]
    for cand in candidates:
        p = project_root / cand
        if p.exists():
            return p
    # 兜底：直接返回常见默认相对路径（生成的测试会在运行时按 SCT_CODE_ROOT 解析）
    return Path("backend/src/main/java")


def cmd_check(args) -> int:
    """对应 speckit.sct.check：三方一致性校验"""
    spec = args.spec or _latest_spec()
    extra = ["--ai"] if args.ai else []

    # 自动检测 code / tests 路径
    spec_path = Path(spec).resolve()
    project_root = spec_path.parent.parent  # specs/<feature>/ → project root
    code_path = project_root / "src"
    tests_path = project_root / "src" / "test"

    # fallback: 扫一下常见位置（覆盖 Maven/前端/混合布局）
    if not code_path.exists():
        for cand in ["src", "app/src/main", "frontend/src",
                     "backend/src/main/java", "src/main/java"]:
            if (project_root / cand).exists():
                code_path = project_root / cand
                break
    if not tests_path.exists():
        for cand in ["src/test", "tests", "frontend/src/__tests__", "__tests__",
                     "backend/src/test/java", "src/test/java"]:
            if (project_root / cand).exists():
                tests_path = project_root / cand
                break

    return run_script("consistency-check.py", [
        "--spec", spec,
        "--code", str(code_path),
        "--tests", str(tests_path),
        "--scope", args.scope or "all",
    ] + extra)


def cmd_impact(args) -> int:
    """对应 speckit.sct.impact：变更影响清单"""
    spec = args.spec or _latest_spec()
    base = args.base or "main"
    head = args.head or "HEAD"
    out = args.out or "change-impact.md"

    return run_script("change-impact.py", [
        "--base", base,
        "--head", head,
        "--spec", spec,
        "--out", out,
    ])


def cmd_e2e(args) -> int:
    """对应 speckit.sct.e2e：影响清单 → Playwright 脚本"""
    impact = args.impact or "change-impact.md"
    spec = args.spec or _latest_spec()
    out = args.out or "e2e/auto_generated/"

    return run_script("change-impact-e2e-bridge.py", [
        "--impact", impact,
        "--spec", spec,
        "--out", out,
    ])


def _latest_spec() -> str:
    """找最新的 acceptance.yaml"""
    cwd = Path.cwd()
    candidates = sorted(cwd.glob("specs/*/acceptance.yaml"), reverse=True)
    if not candidates:
        print("❌ 未找到 acceptance.yaml，请先运行 speckit.sct.merge", file=sys.stderr)
        sys.exit(1)
    return str(candidates[0])


# ====== CLI 入口 ======

def main():
    parser = argparse.ArgumentParser(
        description="SCT Speckit Extension Entry (v1.0-W2 INTERNAL)"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--spec", help="acceptance.yaml 路径")
    common.add_argument("--out", help="输出路径")

    # merge
    p_merge = sub.add_parser("merge", parents=[common], help="生成 SoT (命令: speckit.sct.merge)")
    p_merge.add_argument("--ai", action="store_true", help="AI 自动抽取 acceptance scenarios")

    # codegen
    p_codegen = sub.add_parser("codegen", parents=[common], help="派生测试 (命令: speckit.sct.codegen)")
    p_codegen.add_argument("--target", choices=["backend", "frontend", "e2e", "all"], default="all")

    # check
    p_check = sub.add_parser("check", parents=[common], help="一致性校验 (命令: speckit.sct.check)")
    p_check.add_argument("--ai", action="store_true", help="AI 语义分析")
    p_check.add_argument("--scope", choices=["api", "rule", "scenario", "all"], default="all")
    p_check.add_argument("--strict", action="store_true")

    # impact
    p_impact = sub.add_parser("impact", parents=[common], help="变更影响 (命令: speckit.sct.impact)")
    p_impact.add_argument("--base", default="main")
    p_impact.add_argument("--head", default="HEAD")

    # e2e
    p_e2e = sub.add_parser("e2e", parents=[common], help="e2e 自动回归 (命令: speckit.sct.e2e)")
    p_e2e.add_argument("--impact", help="change-impact.md 路径")
    p_e2e.add_argument("--run", action="store_true", help="生成后立即跑 Playwright")

    args = parser.parse_args()

    handlers = {
        "merge": cmd_merge,
        "codegen": cmd_codegen,
        "check": cmd_check,
        "impact": cmd_impact,
        "e2e": cmd_e2e,
    }
    sys.exit(handlers[args.cmd](args))


if __name__ == "__main__":
    main()
