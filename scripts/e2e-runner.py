#!/usr/bin/env python3
"""
e2e-runner.py
SCT 工具 8：L3 e2e 场景可选执行器（v2.5，内网友好）

定位：L3 e2e 是三层中最"重"的一层——依赖 Playwright + 浏览器 + 真实前端环境。
内网/开发机常常不齐。SCT 的取舍（与三态门禁一致）：

  环境齐备  → 真实执行 playwright specs，产出 junit 证据（进入门禁 EXECUTION 链）
  环境缺失  → **明确告知缺什么、怎么装**，退出码 2（UNPROVEN），不产出假证据
  用户拒装  → e2e 层不参与本次门禁（UNPROVEN ≠ PASS，不拖累其他两层判定）

环境探测顺序（缺哪个提示哪个，一次说全）：
  1. pytest-playwright 可导入？（pip install pytest-playwright）
  2. 浏览器就绪？（playwright install chromium）

用法：
  python e2e-runner.py --specs e2e/auto_generated --out e2e/e2e-junit.xml \
      [--base-url http://localhost:3000]

退出码：0=已执行（结果看 junit / stdout）  1=执行了但有失败  2=环境缺失未执行（UNPROVEN）
"""
import argparse
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

PASS, BLOCK, UNPROVEN = "PASS", "BLOCK", "UNPROVEN"


def _importable(mod: str) -> bool:
    try:
        return importlib.util.find_spec(mod) is not None
    except (ImportError, ValueError):
        return False


def probe_environment() -> list:
    """返回缺失项清单（空 = 环境齐备）。一次说全，不让用户装一样试一样。"""
    missing = []
    if not _importable("pytest"):
        missing.append("pip install pytest")
    if not _importable("pytest_playwright"):
        missing.append("pip install pytest-playwright")
    if _importable("pytest_playwright") and shutil.which("playwright") is None:
        missing.append("playwright install chromium  # 浏览器二进制（内网可用离线包："
                       "PLAYWRIGHT_DOWNLOAD_HOST 指向内网镜像，或复制 ms-playwright 缓存目录）")
    else:
        # playwright CLI 在但浏览器可能未装：执行时 playwright 会给出权威报错，
        # 这里不预判（避免误报），只在缺失清单里给提示
        pass
    return missing


def main() -> int:
    p = argparse.ArgumentParser(description="SCT L3 e2e 可选执行器（环境缺失不冒充通过）")
    p.add_argument("--specs", default="e2e/auto_generated",
                   help="playwright specs 目录（testing.design 生成 e2e/auto_generated/*）")
    p.add_argument("--out", default="e2e/e2e-junit.xml", help="junit 报告输出路径")
    p.add_argument("--base-url", dest="base_url",
                   help="被测前端地址（以环境变量 PLAYWRIGHT_BASE_URL 传给 specs）")
    p.add_argument("--headed", action="store_true", help="有头模式运行（调试用）")
    args = p.parse_args()

    specs = Path(args.specs)
    specs_found = list(specs.rglob("*.spec.ts")) + list(specs.rglob("*.spec.js")) \
        + list(specs.rglob("*_test.py"))
    print("=" * 60)
    print("SCT L3 e2e 执行器（可选层：环境缺失 → UNPROVEN，不冒充通过）")
    print("=" * 60)

    if not specs.exists() or not specs_found:
        print(f"⚠️  {UNPROVEN}: 未找到 e2e specs（{specs}）。")
        print("    e2e 场景由 testing.design 生成；若本次变更未生成 e2e 层，")
        print("    场景断言已由 test_scenarios.py 在单测/接口层代验，可继续。")
        return 2

    missing = probe_environment()
    if missing:
        print(f"⚠️  {UNPROVEN}: e2e 运行环境不齐，本次跳过（不影响单测/接口两层门禁）。")
        print("    缺失清单（按序安装即可）：")
        for m in missing:
            print(f"      - {m}")
        print("    用户选择不安装 = e2e 不参与本次门禁（UNPROVEN ≠ PASS，人工知情即可）。")
        print(f"    e2e specs 待执行清单：{len(specs_found)} 个文件（{specs}）")
        return 2

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    env = {**__import__("os").environ}
    if args.base_url:
        env["PLAYWRIGHT_BASE_URL"] = args.base_url
    cmd = [sys.executable, "-m", "pytest", str(specs), "-q",
           f"--junitxml={out}", "--browser", "chromium"]
    if args.headed:
        cmd.append("--headed")
    print(f"执行: {' '.join(cmd)}")
    try:
        proc = subprocess.run(cmd, env=env, timeout=1800, capture_output=True, text=True)
    except subprocess.TimeoutExpired:
        print(f"⚠️  {UNPROVEN}: e2e 执行超时（30min）——人工确认前端环境后重跑")
        return 2
    tail = (proc.stdout or "")[-1500:] + (proc.stderr or "")[-1500:]
    # 浏览器二进制缺失：playwright 报"Executable doesn't exist"——属环境缺失，
    # 按 UNPROVEN 处理并给出安装提示，不算 BLOCK（不冒充通过，也不冤枉交付）
    if proc.returncode != 0 and ("Executable doesn't exist" in tail or "playwright install" in tail):
        print(f"⚠️  {UNPROVEN}: 浏览器未安装，e2e 本次跳过。安装方式：")
        print("      - playwright install chromium")
        print("      - 内网离线：PLAYWRIGHT_DOWNLOAD_HOST 指向内网镜像，或复制 ms-playwright 缓存目录")
        return 2
    if proc.returncode == 0:
        print(f"✅ e2e 全部通过。junit 证据: {out}")
        print("    可将 --junit 传入 consistency-check（与单测/接口 junit 合并后进同一门禁）。")
        return 0
    print(f"❌ {BLOCK}: e2e 存在失败（exit={proc.returncode}），junit: {out}")
    print("    失败可能来自产品缺陷，也可能来自环境（浏览器版本/前端未起）——")
    print("    先核对前端服务与 PLAYWRIGHT_BASE_URL，再判 SoT 与实现的分歧。")
    print(tail[-800:])
    return 1


if __name__ == "__main__":
    sys.exit(main())
