# SCT — Spec Kit Community Extension Submission

本文件是向 **Spec Kit 官方社区目录**提交 SCT 扩展的对照清单，
把仓库内的元数据文件映射到官方提交流程所需字段。

> 官方目录页：https://github.github.io/spec-kit/community/extensions.html
> （数据源：github/spec-kit 仓库 `extensions/catalog.community.json`）
> 提交入口：向 github/spec-kit 仓库提 **Issue**（自动使用
> `.github/ISSUE_TEMPLATE/extension_submission.yml` 模板），或直接 PR 更新
> `extensions/catalog.community.json`。
> 维护者只校验目录条目完整与格式正确，**不审查扩展代码本身**——安装前自行评审。

## 1. 提交字段对照（全部可从本仓库文件取值）

| Issue 模板字段 | 值 | 来源 |
|---|---|---|
| Extension ID | `sct` | `extension.yml` `extension.id` |
| Extension Name | `Spec-Code-Test Consistency (SCT)` | `extension.yml` `extension.name` |
| Version | `1.1.0` | `extension.yml` `extension.version` |
| Description (<200 chars) | "Speckit extension implementing the SCT methodology: a single source of truth (acceptance.yaml), auto-generated write-once tests, three-way spec↔code↔test consistency checks, test-effectiveness verification, and change-impact / tier-gated workflows." | `catalog-entry.json` `description` |
| Author | `zqianqian137` | `extension.yml` `extension.author` |
| Repository URL | `https://github.com/zqianqian137/spec-kit-sct` | `extension.yml` |
| Download URL | `https://github.com/zqianqian137/spec-kit-sct/archive/refs/tags/v1.1.0.zip` | `catalog-entry.json` `download_url` |
| License | `MIT` | `extension.yml` |
| Homepage (optional) | `https://github.com/zqianqian137/spec-kit-sct` | `extension.yml` |
| Documentation (optional) | `https://github.com/zqianqian137/spec-kit-sct/blob/v1.1.0/README.md` | `catalog-entry.json` |
| Changelog (optional) | `https://github.com/zqianqian137/spec-kit-sct/blob/v1.1.0/CHANGELOG.md` | `catalog-entry.json` |
| Required Spec Kit Version | `>=0.9.0` | `extension.yml` `requires.speckit_version` |
| Required Tools (optional) | `codebase-memory-mcp`（可选，用于 sct.impact 反向追溯增强） | `extension.yml` `requires.tools` |
| Number of Commands | `6` | `catalog-entry.json` `provides.commands` |

> 版本号需与当前 GitHub release tag 一致。发布流程：
> `git tag vX.Y.Z` → push → GitHub 生成 `vX.Y.Z.zip` 归档 → 更新本文件与
> `catalog-entry.json` 的 `download_url` / `documentation` / `changelog`。

## 2. category / effect（社区目录展示用，v1.1.0 起已声明）

- `category: process` —— 跨阶段编排工作流（spec → code → test → check → verify）
- `effect: read-write` —— 生成测试文件 / 覆盖率报告 / 验证报告等产物

声明位置：`extension.yml` `extension:` 块 + `catalog-entry.json` 顶层
（两者需一致，官方目录页从 catalog 读这两个字段展示）。

## 3. 提交前自检

- [ ] `extension.yml` 与 `catalog-entry.json` 的 version 一致
- [ ] `catalog-entry.json` 含 `category` / `effect` / `provides.commands`(6)
- [ ] Download URL 指向已存在的 GitHub tag 归档（v1.1.0.zip 已发布）
- [ ] `extension.yml` 的 `schema_version: "1.0"`，命令文件位于 `commands/`
- [ ] 6 个命令文件均可被加载（`specify extension info` 可列出）
- [ ] README 有安装命令 `specify extension add sct --from <v1.1.0.zip>`
- [ ] LICENSE 存在（MIT）

## 4. 提交动作（二选一）

**A. Issue 提交（推荐，官方模板引导）**
1. 打开 https://github.com/github/spec-kit/issues/new?template=extension_submission.yml
2. 按第 1 节对照表逐项填写
3. 提交后等待维护者 triage（labels: enhancement, needs-triage）
4. 通过后维护者把条目并入 `extensions/catalog.community.json`，
   社区目录页自动展示

**B. PR 直改 catalog**
1. fork github/spec-kit
2. 编辑 `extensions/catalog.community.json`，在 `extensions` 下新增键 `sct`，
   值 = 本仓库 `catalog-entry.json` 的完整内容
3. 提交 PR

> 注意：目录条目里的 `verified / downloads / stars / created_at / updated_at`
> 由维护者/站点工具填充，提交时无需提供。

## 5. 唯一性说明（为什么值得收录）

社区 163+ 扩展中，SCT 同时具备：
- **完整前向保证链**（merge→codegen→check→impact→e2e→verify 六命令贯通）
- **确定性脚本优先**（从 SoT 机械派生断言，不靠 LLM 判断"实现是否符合规范"）
- **测试有效性验证**（sct.verify：幻影检测/编译门/真实执行数/变异得分，诚实三态）
- **独有能力**：非 HTTP 接口、多模块、AI 测试平台 intent 导出、断言不反推代码、
  8 类漂移归因
