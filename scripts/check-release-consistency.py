#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check-release-consistency.py —— SCT 发布前一致性自检

用 SCT 自己的规矩守 SCT 自己的发布：文档与元数据必须彼此一致，否则不许发版。
本脚本是「确定性引擎」：不给建议，只判 PASS / BLOCK / UNPROVEN。

检查项（每项独立判定，整体取最严 BLOCK > UNPROVEN > PASS）：

  1. VERSION       extension.yml / catalog-entry.json / README 安装链接 版本一致
  2. COMMANDS      catalog 的 provides.commands 与 extension.yml 实际命令数一致
  3. HOOKS         catalog 的 provides.hooks 与 extension.yml 实际 hook 数一致
  4. DESCRIPTION   extension.yml 与 catalog-entry.json 的 description 文案一致
  5. TAGS          两处 tags 集合一致
  6. LEGACY_CMD    全仓 .md 无残留旧命令名 speckit.sct.*（CHANGELOG 历史除外；
                   嵌套 git 仓库 / 嵌套扩展根除外——不扫别人家地盘）
  7. PROFILE_DOC   README 不把覆盖率硬编码成单一数字（应声明为 profile 驱动）

退出码：PASS 0 · BLOCK 1 · UNPROVEN 2

用法：
    python scripts/check-release-consistency.py [root1] [root2] ...   # 默认 .
    python scripts/check-release-consistency.py . ../spec-kit-sct
"""

import argparse
import json
import os
import re
import sys

try:
    import yaml  # type: ignore
    _HAS_YAML = True
except ImportError:  # 内网离线环境可能没有 pyyaml —— 降级为 UNPROVEN，不假装通过
    _HAS_YAML = False

PASS, BLOCK, UNPROVEN = "PASS", "BLOCK", "UNPROVEN"
_SEVERITY = {PASS: 0, UNPROVEN: 1, BLOCK: 2}

# 历史文件：CHANGELOG 合法地记载旧命令名，不参与残留扫描
_EXCLUDE_FROM_SCAN = {"CHANGELOG.md"}
_LEGACY_CMD_RE = re.compile(r"speckit\.sct\.(merge|codegen|check|impact|e2e|verify)\b")
_VERSION_IN_URL_RE = re.compile(r"tags/v([0-9]+\.[0-9]+\.[0-9]+)\.zip")


def _worst(statuses):
    if not statuses:
        return UNPROVEN  # 什么都没检查到 = 证据不足，不是通过
    return max(statuses, key=lambda s: _SEVERITY[s])


class Report(object):
    def __init__(self, root):
        self.root = root
        self.rows = []  # (check, status, detail)

    def add(self, check, status, detail):
        self.rows.append((check, status, detail))

    @property
    def status(self):
        return _worst([r[1] for r in self.rows])


# ---------------------------------------------------------------- 读取元数据

def _read_text(path):
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _load_yaml(path):
    """YAML 缺失时抛异常，由调用方降级为 UNPROVEN。"""
    if not _HAS_YAML:
        raise RuntimeError("pyyaml 不可用")
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _regex_count_commands(text):
    """无 pyyaml 时的降级提取：数 `provides.commands` 下的 `- name:` 条目。

    不写死缩进宽度：`commands:` 与 `- name:` 的实际缩进随文件布局变化
    （当前 extension.yml 为 2/4 空格）。先捕获 `commands:` 的缩进，再以
    「缩进小于它」的行作为块结束边界——这样即使 provides 段内有同缩进的
    注释说明行，也不会误截或误计。
    """
    m = re.search(r"^provides:\s*$", text, re.M)
    if not m:
        return 0
    tail = text[m.end():]
    m2 = re.search(r"^(?P<ind>[ \t]+)commands:\s*$", tail, re.M)
    if not m2:
        return 0
    indent = m2.group("ind")
    block = tail[m2.end():]
    nxt = re.search(r"^[ \t]{0,%d}\S" % max(0, len(indent) - 1), block, re.M)
    if nxt:
        block = block[:nxt.start()]
    return len(re.findall(r"^\s+- name:\s*\S", block, re.M))


def _regex_count_hooks(text):
    m = re.search(r"^hooks:\s*$", text, re.M)
    if not m:
        return 0
    block = text[m.end():]
    nxt = re.search(r"^\S", block, re.M)
    if nxt:
        block = block[:nxt.start()]
    return len(re.findall(r"^\s{2}[A-Za-z_][A-Za-z0-9_]*:\s*$", block, re.M))


def _regex_version(text):
    m = re.search(r'^  version:\s*"?([0-9]+\.[0-9]+\.[0-9]+)"?\s*$', text, re.M)
    return m.group(1) if m else None


# ---------------------------------------------------------------- 各项检查

def check_root(root, args_exclude=None):
    rep = Report(root)
    yml_path = os.path.join(root, "extension.yml")
    cat_path = os.path.join(root, "catalog-entry.json")
    readme_path = os.path.join(root, "README.md")

    if not (os.path.isfile(yml_path) and os.path.isfile(cat_path)):
        rep.add("METADATA", UNPROVEN, "%s 缺少 extension.yml 或 catalog-entry.json，跳过" % root)
        return rep

    yml_text = _read_text(yml_path)
    try:
        cat = json.loads(_read_text(cat_path))
    except ValueError as exc:
        rep.add("CATALOG_JSON", BLOCK, "catalog-entry.json 非法 JSON：%s" % exc)
        return rep

    # ---- 解析 extension.yml（pyyaml 缺失则降级）
    try:
        yml = _load_yaml(yml_path)
        y_version = str(yml["extension"]["version"])
        y_cmds = yml.get("provides", {}).get("commands", []) or []
        y_cmd_names = [c.get("name", "") for c in y_cmds]
        y_hooks = yml.get("hooks") or {}
        y_desc = str(yml["extension"].get("description", ""))
        y_tags = list(yml.get("tags") or [])
        degraded = False
    except Exception:
        y_version = _regex_version(yml_text)
        y_cmd_names = ["?"] * _regex_count_commands(yml_text)
        y_hooks = {"?": {}} if _regex_count_hooks(yml_text) else {}
        y_desc = None
        y_tags = None
        degraded = True

    if degraded:
        rep.add("YAML_PARSE", UNPROVEN,
                "pyyaml 不可用，字段走正则降级提取，VERSION/COMMANDS/HOOKS 结果可能不准")

    if y_version is None:
        rep.add("VERSION", UNPROVEN, "无法从 extension.yml 解析版本号")
    else:
        # 1. VERSION
        c_version = str(cat.get("version", ""))
        detail = "extension.yml=%s, catalog=%s" % (y_version, c_version)
        if c_version != y_version:
            rep.add("VERSION", BLOCK, "版本不一致 — " + detail)
        elif os.path.isfile(readme_path):
            urls = set(_VERSION_IN_URL_RE.findall(_read_text(readme_path)))
            if not urls:
                rep.add("VERSION", UNPROVEN, "README 未找到 tags/vX.Y.Z.zip 安装链接，无法校验")
            elif urls != {y_version}:
                rep.add("VERSION", BLOCK,
                        "README 安装链接版本 %s 与元数据 %s 不一致" % (sorted(urls), y_version))
            else:
                rep.add("VERSION", PASS, detail + ", README 链接一致")
        else:
            rep.add("VERSION", PASS, detail + "（无 README，跳过链接校验）")

    # 2. COMMANDS
    c_cmds = (cat.get("provides") or {}).get("commands")
    if not isinstance(c_cmds, int):
        rep.add("COMMANDS", UNPROVEN, "catalog-entry.json 的 provides.commands 缺失或非整数：%r" % c_cmds)
    elif c_cmds != len(y_cmd_names):
        rep.add("COMMANDS", BLOCK,
                "命令数不一致 — catalog=%d, extension.yml=%d (%s)"
                % (c_cmds, len(y_cmd_names), ", ".join(y_cmd_names)))
    else:
        rep.add("COMMANDS", PASS, "commands=%d 一致：%s" % (c_cmds, ", ".join(y_cmd_names)))

    # 3. HOOKS
    c_hooks = (cat.get("provides") or {}).get("hooks")
    if not isinstance(c_hooks, int):
        rep.add("HOOKS", UNPROVEN, "catalog-entry.json 的 provides.hooks 缺失或非整数：%r" % c_hooks)
    elif c_hooks != len(y_hooks):
        rep.add("HOOKS", BLOCK,
                "hook 数不一致 — catalog=%d, extension.yml=%d (%s)"
                % (c_hooks, len(y_hooks), ", ".join(sorted(y_hooks)) or "无"))
    else:
        rep.add("HOOKS", PASS, "hooks=%d 一致" % c_hooks)

    # 4. DESCRIPTION
    c_desc = cat.get("description")
    if y_desc is None or not c_desc:
        rep.add("DESCRIPTION", UNPROVEN, "extension.yml 或 catalog 的 description 无法读取")
    elif y_desc.strip() != str(c_desc).strip():
        rep.add("DESCRIPTION", BLOCK,
                "描述文案不一致\n      extension.yml: %s\n      catalog     : %s"
                % (y_desc.strip()[:90], str(c_desc).strip()[:90]))
    else:
        rep.add("DESCRIPTION", PASS, "description 文案一致")

    # 5. TAGS
    c_tags = list(cat.get("tags") or [])
    if y_tags is None or not c_tags:
        rep.add("TAGS", UNPROVEN, "tags 无法读取（pyyaml 缺失或 catalog 无 tags）")
    elif sorted(y_tags) != sorted(c_tags):
        only_yml = sorted(set(y_tags) - set(c_tags))
        only_cat = sorted(set(c_tags) - set(y_tags))
        rep.add("TAGS", BLOCK, "tags 不一致 — 仅 extension.yml: %s / 仅 catalog: %s"
                % (only_yml or "无", only_cat or "无"))
    else:
        rep.add("TAGS", PASS, "tags 一致（%d 个）" % len(c_tags))

    # 6. LEGACY_CMD —— 旧命令名残留
    hits = []
    exclude = set(args_exclude or ())
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames
            if d not in (".git", "node_modules", "__pycache__", ".workbuddy")
            and d not in exclude
            # 嵌套的另一个 git 仓库（如上游 spec-kit 克隆）不归本扩展管，
            # 其散置文档（评审材料等）可能合法地引用历史命令名
            and not os.path.isdir(os.path.join(dirpath, d, ".git"))
            # 嵌套的另一个扩展根有自己的 extension.yml，不归本扩展管
            and not (os.path.join(dirpath, d) != root
                     and os.path.isfile(os.path.join(dirpath, d, "extension.yml")))
        ]
        for fn in filenames:
            if not fn.endswith(".md") or fn in _EXCLUDE_FROM_SCAN:
                continue
            path = os.path.join(dirpath, fn)
            try:
                text = _read_text(path)
            except (OSError, UnicodeDecodeError):
                continue
            for i, line in enumerate(text.splitlines(), 1):
                if _LEGACY_CMD_RE.search(line):
                    hits.append("%s:%d" % (os.path.relpath(path, root), i))
    if hits:
        rep.add("LEGACY_CMD", BLOCK,
                "残留旧命令名 speckit.sct.*（%d 处）：%s" % (len(hits), ", ".join(hits[:6])))
    else:
        rep.add("LEGACY_CMD", PASS, "无 speckit.sct.* 残留")

    # 7. PROFILE_DOC —— 覆盖率口径不得硬编码成单一数字
    if not os.path.isfile(readme_path):
        rep.add("PROFILE_DOC", UNPROVEN, "无 README.md，跳过")
    else:
        text = _read_text(readme_path)
        has_hardcode = bool(re.search(r"coverage\s*[≥>]=?\s*\*{0,2}9[05]\s*\*{0,2}%", text))
        has_profile = "profile" in text.lower()
        if has_hardcode and not has_profile:
            rep.add("PROFILE_DOC", BLOCK,
                    "README 硬编码覆盖率门禁却未提 --profile（口径应声明为 profile 驱动）")
        elif has_hardcode:
            rep.add("PROFILE_DOC", PASS, "覆盖率已声明为 profile 驱动")
        else:
            rep.add("PROFILE_DOC", PASS, "README 未硬编码覆盖率数字")

    return rep


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="SCT 发布前一致性自检（PASS 0 / BLOCK 1 / UNPROVEN 2）")
    parser.add_argument("roots", nargs="*", default=["."],
                        help="扩展根目录（可多个），默认当前目录")
    parser.add_argument("--exclude", action="append", metavar="DIRNAME",
                        help="扫描时排除的子目录名（可重复），"
                             "用于跳过嵌套的上游仓库副本，如 --exclude spec-kit-main")
    parser.add_argument("--json", action="store_true", help="输出 JSON 而非表格")
    args = parser.parse_args(argv)

    reports = [check_root(r, args.exclude) for r in (args.roots or ["."])]
    overall = _worst([r.status for r in reports])

    if args.json:
        print(json.dumps({
            "status": overall,
            "roots": [{"root": r.root, "status": r.status,
                       "checks": [{"check": c, "status": s, "detail": d} for c, s, d in r.rows]}
                      for r in reports],
        }, ensure_ascii=False, indent=2))
    else:
        for r in reports:
            print("\n=== %s ===" % r.root)
            for check, status, detail in r.rows:
                print("  [%-8s] %-12s %s" % (status, check, detail))
            print("  → %s" % r.status)
        print("\n" + "=" * 60)
        print("OVERALL: %s   (PASS 0 · BLOCK 1 · UNPROVEN 2)" % overall)
        if overall == UNPROVEN:
            print("注意：UNPROVEN ≠ PASS —— 证据不足不得当作通过。")

    return {PASS: 0, BLOCK: 1, UNPROVEN: 2}[overall]


if __name__ == "__main__":
    sys.exit(main())
