# SCT 扩展 — 社区发布提交包

本目录是一个**可直接发布到 Spec Kit 社区扩展目录**的独立扩展仓库。
下方是提交所需的全部材料与步骤。

> ✅ 本包已指向真实仓库 `zqianqian137/spec-kit-sct`，所有 `extension.yml`、
> `README.md`、`catalog-entry.json`、`LICENSE` 中的地址/作者均已替换完毕，
> 发布时无需再手动替换。

---

## 一、提交方式（重要）

社区 **扩展** 与 **preset** 提交方式不同：

- **扩展走 Issue 模板**，不要直接开 PR 改 `extensions/catalog.community.json`。
- 打开 Issue 模板：
  https://github.com/github/spec-kit/issues/new?template=extension_submission.yml
- 维护者审核通过后，会把条目写进 `extensions/catalog.community.json` 并更新
  `docs/community/extensions.md` 表格。

## 二、发布前本地准备（已指向 zqianqian137/spec-kit-sct）

```bash
cd spec-kit-sct
git init && git add -A && git commit -m "SCT extension v1.0.0"
git branch -M main
git remote add origin https://github.com/zqianqian137/spec-kit-sct.git
git tag v1.0.0
git push -u origin main --tags     # 也需在 GitHub 上创建 Release（tag v1.0.0）
```

Release 归档地址（即 `download_url`，已写入各文件）：

```text
https://github.com/zqianqian137/spec-kit-sct/archive/refs/tags/v1.0.0.zip
```

> 🔐 **认证说明（重要）**：GitHub 自 2021-08-13 起已**停止支持账号密码**
> 进行 Git over HTTPS 操作，推送必须用 **Personal Access Token (PAT)**。
> 邮箱 + 密码 `qian191996` 作为账号密码**无法用于 `git push`**，会被拒绝
> （`remote: Support for password authentication was removed`）。
> 请用以下任一方式：
> 1. 生成 PAT（`repo` 权限）：GitHub → Settings → Developer settings →
>    Personal access tokens → Tokens (classic) → Generate new token，勾选 `repo`。
> 2. 推送时用 PAT 代替密码：
>    `git push https://1737306921%40qq.com:<YOUR_PAT>@github.com/zqianqian137/spec-kit-sct.git --tags`
>    （邮箱中的 `@` 需转义为 `%40`。）
> 3. 或配置 SSH key 后改用 `git@github.com:zqianqian137/spec-kit-sct.git`。

本地自测（可选但建议）：

```bash
specify extension add --dev /path/to/spec-kit-sct
specify extension info sct
specify extension add sct --from https://github.com/zqianqian137/spec-kit-sct/archive/refs/tags/v1.0.0.zip
```

## 三、Issue 提交内容（填入 extension_submission 模板）

```text
## Extension Submission

Extension ID:        sct
Extension Name:      Spec-Code-Test Consistency (SCT)
Version:             1.0.0
Author:              zqianqian137
License:             MIT
Repository:          https://github.com/zqianqian137/spec-kit-sct
Download URL:        https://github.com/zqianqian137/spec-kit-sct/archive/refs/tags/v1.0.0.zip
Documentation:       https://github.com/zqianqian137/spec-kit-sct/blob/v1.0.0/README.md
Required Spec Kit:   >=0.9.0
Tool dependencies:   codebase-memory-mcp (optional, required: false)
Commands provided:   5  (speckit.sct.merge / codegen / check / impact / e2e)
Hooks provided:      4  (after_implement x2, after_plan x1, after_e2e x1)
Tags:                sct, spec-code-test, consistency, test-automation, change-impact

Description:
  Speckit extension implementing the SCT methodology: a single source of truth
  (acceptance.yaml), auto-generated write-once tests, three-way spec<->code<->test
  consistency checks, and change-impact / tier-gated workflows.

Key features:
  - Single source of truth (acceptance.yaml) built from spec/plan/data-model/api-contracts
  - Write-once derived unit + e2e tests (no manual edits)
  - Three-way consistency check with human-review report (JaCoCo incremental coverage,
    API execution, rule verification, change-point audit)
  - Reverse change-impact tracing (P0/P1/P2) + L1/L2/L3 tier decision
  - Playwright e2e auto-regression bridge
  - Optional --ai LLM extraction / semantic drift; optional codebase-memory-mcp enrichment
  - Brownfield incremental mode, CodeGraph request enrichment, full exception-value coverage

Testing confirmation:
  Tested locally with `specify extension add --dev` and `specify extension add --from <archive>`.
```

## 四、catalog 条目（供维护者直接写入 extensions/catalog.community.json）

见同目录 `catalog-entry.json`（已按社区扩展 catalog schema 写齐，可直接粘贴）。

## 五、提交前 Checklist

- [ ] `extension.yml` 的 `repository` / `homepage` 已改为真实仓库地址
- [ ] 已创建 GitHub Release `v1.0.0`（tag 已 push）
- [ ] `README.md` 含有效的 `specify extension add ... --from <download_url>` 命令
- [ ] `LICENSE` 文件存在（MIT）
- [ ] `CHANGELOG.md` 已填写
- [ ] `catalog-entry.json` 的 `download_url` / `documentation` 与真实 Release 一致
- [ ] 本地 `specify extension add --dev` 安装验证通过
- [ ] 5 个命令文件 + 脚本 + 模板均随仓库发布（已包含在本次包中）

## 六、目录结构（本发布包）

```text
spec-kit-sct/
├── extension.yml              # 扩展清单（已按社区 schema 修正）
├── README.md                  # 本扩展文档（含安装命令）
├── LICENSE                    # MIT
├── CHANGELOG.md
├── catalog-entry.json         # 社区目录条目（提交用）
├── SCT-COMMUNITY-SUBMISSION.md # 本文件
├── commands/                  # 5 个 speckit.sct.* 命令
├── scripts/                   # Python 引擎（merge/codegen/check/impact/e2e + 钩子入口）
└── templates/                 # 产物模板（SoT / 报告 / e2e / 单元测试约定等）
```

## 七、与 presets 页的关系（澄清）

`extensions/sct/` 的核心能力在**脚本与钩子**里，而社区 **presets** 只能携带
`templates/` 和 `commands/` 覆盖，无法携带脚本/钩子。因此 SCT 作为**扩展**
提交到社区扩展目录（本包）才是完整形态。若还想在 `presets.html` 露脸，可另发
一个配套 preset（仅含 4 个核心命令覆盖 `speckit.specify/plan/implement/constitution`
+ 方法论文档，不含引擎）——但那是缩水版，需单独提交。
