"""
acceptance-codegen.py
=====================
从 acceptance.yaml 自动生成测试代码。
默认只读 acceptance.yaml；可选 --codegraph 引入真实代码的接口图谱
（DTO 字段/类型/约束/枚举，交换格式见 templates/codegraph-template.json），
用真实代码数据增强示例值/必填判定/枚举，并输出字段级漂移（FIELD_DRIFT）。

归属：Speckit 扩展 `sct` 内置实现（v1.0-W2 / 自包含）

生成三类测试：
1. 接口测试 (test_api_*.py) - 覆盖所有 API
2. 业务规则测试 (test_rules_*.py) - 覆盖所有 BR
3. 验收场景测试 (test_scenarios.py) - 覆盖所有 acceptance_scenario

模板约定（见 templates/unit-test-template.py）：
每个测试案例必须携带「真相意图说明」，四要素缺一不可：
  [意图] 一句话说明验证什么（来自 SoT 场景/规则原文）
  真相来源 acceptance.yaml 锚点
  Given / When / Then 三段式，测试体按三段注释组织

用法：
    python $SCT_EXT_HOME/scripts/acceptance-codegen.py \\
        --spec specs/001-batch-import/acceptance.yaml \\
        --out tests/generated/ \\
        --codegraph codegraph.json    # 可选：CodeGraph 导出，增强生成

附带产物：--out 目录落盘 _codegen_meta.json（API 实现标注 + FIELD_DRIFT），
testing.run 自动发现后把 CodeGraph 标注与字段级漂移整合进最终测试报告。
"""
import yaml
import json
import argparse
import hashlib
import re
import os
from pathlib import Path
import sct_ids
from datetime import datetime

# 生成器版本：写入 _codegen_meta.json，manifest 校验时若版本不符则强制再生成
GENERATOR_VERSION = "2.1.0"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest_intact(out_dir: Path, expected: list) -> tuple:
    """校验 write-once manifest：→ (是否完整, 问题清单[缺失/被改])"""
    problems = []
    for item in expected or []:
        fp = out_dir / item.get("path", "")
        if not fp.exists():
            problems.append(f"缺失: {item.get('path')}")
        elif sha256_file(fp) != item.get("sha256"):
            problems.append(f"已被手工修改: {item.get('path')}")
    return (not problems, problems)


def load_acceptance(spec_path: Path) -> dict:
    with open(spec_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# =====================================================================
# CodeGraph 交换格式（templates/codegraph-template.json）加载与匹配
# =====================================================================

def load_codegraph(path: str | None) -> dict | None:
    """加载 CodeGraph 导出文件；未提供或不存在则返回 None（降级为纯 SoT 生成）"""
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        print(f"⚠️  CodeGraph 文件不存在，降级为纯 SoT 生成: {path}")
        return None
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def normalize_path_for_match(path: str) -> str:
    """路径归一化：{id} 与 :id 等价，忽略 /api 前缀（与 consistency-check 口径一致）"""
    p = re.sub(r'\{(\w+)\}', r':\1', path)
    p = re.sub(r'^/api/', '/', p)
    return p


def build_graph_index(codegraph: dict | None) -> dict:
    """CodeGraph.apis[] → {'METHOD path': api_graph}（归一化键）"""
    if not codegraph:
        return {}
    index = {}
    for g in codegraph.get("apis", []):
        key = f"{g.get('method', '').upper()} {normalize_path_for_match(g.get('path', ''))}"
        index[key] = g
    return index


def match_graph(api: dict, graph_index: dict) -> dict | None:
    """按 method+path 匹配 CodeGraph 条目"""
    return graph_index.get(f"{api.get('method', '').upper()} {normalize_path_for_match(api.get('path', ''))}")


def graph_base_url(codegraph: dict | None) -> str:
    """CodeGraph project.base_url（缺省 localhost:8080）"""
    if codegraph:
        return (codegraph.get("project") or {}).get("base_url", "http://localhost:8080")
    return "http://localhost:8080"


def gen_conftest(out_dir: Path, default_base_url: str) -> str:
    """为 test_api_*.py 生成 conftest.py：提供 session fixture（带 auth）、base_url。

    让生成的 API 测试"配置驱动"——pytest 启动后只读环境变量，不需要重生成代码：
      BASE_URL        默认 base_url（CLI/codegraph/兜底 三级已算好；可被环境变量覆盖）
      API_AUTH_TOKEN        可选；存在则设为 Bearer token
      API_AUTH_HEADER      可选；自定义头部名（默认 Authorization）
    """
    default = default_base_url.replace("\\", "\\\\")  # 避免反斜杠在 docstring 里被解释
    conftest_code = f'''"""
AUTO-GENERATED FROM acceptance.yaml - DO NOT EDIT
codegen: 配置驱动的 API 测试 fixture。pytest 启动时读环境变量，无需重新生成。
"""
import os
import pytest
import requests


@pytest.fixture
def session():
    """带鉴权的 requests.Session；base_url 与 Authorization 头部均从环境变量读。

    用法：
        BASE_URL=http://staging.internal:8080 \\
        API_AUTH_TOKEN=eyJhbGciOi... \\
        pytest tests/generated/

    缺 API_AUTH_TOKEN → 不发 Authorization；适用于开放接口或本地未鉴权环境。
    s.base_url 会被 generated/test_api_*.py 通过 session.base_url 取用（不要硬编码）。
    """
    s = requests.Session()
    s.base_url = os.getenv("BASE_URL", "{default}")
    token = os.getenv("API_AUTH_TOKEN")
    if token:
        header_name = os.getenv("API_AUTH_HEADER", "Authorization")
        s.headers[header_name] = f"Bearer {{token}}"
    # 关闭 keep-alive 让连接错更明显，避免复用陈旧 socket
    s.headers.setdefault("Connection", "close")
    yield s
    s.close()
'''
    path = out_dir / "conftest.py"
    path.write_text(conftest_code, encoding="utf-8")
    return str(path)


def graph_field_map(graph: dict | None) -> dict:
    """CodeGraph request_dto.fields[] → {字段名: field_graph}"""
    if not graph:
        return {}
    return {f["name"]: f for f in (graph.get("request_dto") or {}).get("fields", []) if "name" in f}


def graph_value(field_graph: dict | None):
    """从 CodeGraph 字段取示例值：example > enum[0] > 类型默认值"""
    if not field_graph:
        return None
    if field_graph.get("example") is not None:
        return field_graph["example"]
    enum = field_graph.get("enum")
    if enum:
        return enum[0]
    ftype = field_graph.get("type", "String")
    if ftype in ("Integer", "Long", "int", "long"):
        return 1
    if ftype in ("Boolean", "boolean"):
        return True
    return None


def diff_api_fields(api: dict, graph: dict | None) -> list:
    """SoT request.body vs CodeGraph request_dto.fields 字段级比对 → FIELD_DRIFT 列表"""
    drifts = []
    if graph is None:
        return drifts
    sot_fields = {f["name"]: f for f in (api.get("request") or {}).get("body") or [] if "name" in f}
    graph_fields = graph_field_map(graph)
    api_ref = f"{api.get('method', '')} {api.get('path', '')}"
    # 1) SoT 有、代码无 → 代码缺失字段（改了 SoT 没实现，或字段改名）
    for name in sorted(set(sot_fields) - set(graph_fields)):
        drifts.append({"api": api_ref, "kind": "MISSING_IN_CODE", "field": name,
                       "detail": f"SoT 定义字段 {name} 但代码 DTO 无此字段"})
    # 2) 代码有、SoT 无 → 未登记字段（增量模式下提醒登记，不算阻塞）
    for name in sorted(set(graph_fields) - set(sot_fields)):
        drifts.append({"api": api_ref, "kind": "UNSPEC_IN_SOT", "field": name,
                       "detail": f"代码 DTO 有字段 {name} 但 SoT 未登记"})
    # 3) 两边都有但 required 不一致
    for name in sorted(set(sot_fields) & set(graph_fields)):
        sot_req = bool(sot_fields[name].get("required", False))
        graph_req = bool(graph_fields[name].get("required", False))
        if sot_req != graph_req:
            drifts.append({"api": api_ref, "kind": "REQUIRED_MISMATCH", "field": name,
                           "detail": f"字段 {name} 必填性不一致：SoT={sot_req} 代码={graph_req}"})
    return drifts


# =====================================================================
# 异常值派生：CodeGraph 约束注解 → 系统性非法值用例
# =====================================================================

_MISSING = "__MISSING__"  # 缺失字段哨兵（构建请求体时移除该键）


def parse_constraints(field_graph: dict) -> list:
    """解析 constraints 字符串列表 → [(注解名, 参数dict, 原文)]"""
    out = []
    for c in field_graph.get("constraints") or []:
        m = re.match(r"@(\w+)(?:\((.*)\))?", str(c).strip())
        if not m:
            continue
        name, params_str = m.group(1), m.group(2) or ""
        params = {}
        for kv in re.finditer(r"(\w+)\s*=\s*([\w.\-\"']+)", params_str):
            params[kv.group(1)] = kv.group(2).strip("'\"")
        out.append((name, params, str(c).strip()))
    return out


def invalid_value_for(field_graph: dict, constraint: tuple):
    """针对单条约束注解返回 (非法值, 违规说明) 或 None（无法派生）

    派生规则（边界值 + 等价类违规）：
      @NotNull/@NotBlank → 缺失字段
      @Max(v)            → v+1（上边界外）
      @Min(v)            → v-1（下边界外）
      @Size(min,max)     → min-1 长度 / max+1 长度
      @Pattern/@Email    → 格式违规字符串
    """
    name, params, raw = constraint
    example = field_graph.get("example")
    if name in ("NotNull", "NotBlank"):
        return (_MISSING, f"缺失必填字段（{raw}）")
    if name == "Max":
        limit = int(float(params.get("value", params.get("limit", "0"))))
        return (limit + 1, f"超过上限 {limit}（{raw}）")
    if name == "Min":
        limit = int(float(params.get("value", params.get("limit", "0"))))
        return (limit - 1, f"低于下限 {limit}（{raw}）")
    if name == "Size":
        mn = int(float(params.get("min", "0") or 0))
        mx = int(float(params.get("max", "2147483647") or 2147483647))
        base = str(example) if example is not None else "v"
        if mn > 0:
            return (base[: max(mn - 1, 0)], f"长度低于 min={mn}（{raw}）")
        return (base * (mx + 1), f"长度超过 max={mx}（{raw}）")
    if name == "Pattern":
        return ("!!invalid-format!!", f"不符合格式要求（{raw}）")
    if name == "Email":
        return ("not-an-email", f"非法邮箱格式（{raw}）")
    return None


def build_valid_body(api: dict, graph: dict | None = None) -> dict:
    """构造全字段合法请求体（dict）——派生异常用例的基线"""
    graph_fields = graph_field_map(graph)
    body = {}
    for field in (api.get("request") or {}).get("body") or []:
        gv = graph_value(graph_fields.get(field["name"]))
        body[field["name"]] = gv if gv is not None else example_value(field)
    if graph:
        for name, fg in graph_fields.items():
            if name not in body and fg.get("required", False):
                gv = graph_value(fg)
                if gv is not None:
                    body[name] = gv
    return body


def _cg_case(api_num: str, seq: int, valid_body: dict, field: str, value,
             violation: str, dto: str, then_extra: str = "") -> dict:
    """组装一条 CodeGraph 派生异常用例（命名 test_api_{n}_cg_error_{seq}）"""
    payload = dict(valid_body)
    if value == _MISSING:
        payload.pop(field, None)
        given = f"其余字段合法，但缺少字段 {field}"
    else:
        payload[field] = value
        given = f"其余字段合法，但 {field}={value!r}"
    api_lower = api_num
    return {
        "name": f"test_api_{api_lower}_cg_error_{seq}",
        "intent": f"验证 {violation} 时接口拒绝请求",
        "source": f"codegraph:{dto}.{field}",
        "given": given,
        "when": "提交上述非法请求体",
        "then": f"返回 400（Bean Validation 拒绝）{then_extra}".rstrip(),
        "request": str(payload) if payload else "None",
        "expected_status": 400,
        "expected_message_contains": "",
    }


def derive_error_cases(api: dict, graph: dict | None, api_num: str) -> list:
    """从 CodeGraph 字段约束/枚举/类型系统性派生异常用例

    覆盖三类异常值（SoT errors[] 之外）：
      1. 约束注解违规——@NotNull/@Max/@Min/@Size/@Pattern/@Email 逐条派生
      2. 枚举非法值——enum 字段提交不在枚举内的值
      3. 类型不匹配——数值/布尔字段提交字符串
    """
    if not graph:
        return []
    cases = []
    valid = build_valid_body(api, graph)
    dto = (graph.get("request_dto") or {}).get("name", "request_dto")
    fields = (graph.get("request_dto") or {}).get("fields", [])
    for fg in fields:
        fname = fg.get("name")
        if not fname:
            continue
        # 1) 约束注解
        for c in parse_constraints(fg):
            iv = invalid_value_for(fg, c)
            if iv is not None:
                cases.append(_cg_case(api_num, len(cases) + 1, valid, fname,
                                      iv[0], iv[1], dto))
        # 2) 枚举非法值
        if fg.get("enum"):
            cases.append(_cg_case(api_num, len(cases) + 1, valid, fname,
                                  f"INVALID_{str(fname).upper()}",
                                  f"字段 {fname} 提交枚举外的非法值（合法值：{fg['enum']}）", dto))
        # 3) 类型不匹配
        if fg.get("type") in ("Integer", "Long", "int", "long", "Boolean", "boolean"):
            cases.append(_cg_case(api_num, len(cases) + 1, valid, fname,
                                  "not-a-number", f"字段 {fname} 类型不匹配（{fg['type']} 收到字符串）", dto))
    return cases


def gen_api_tests(apis: list, out_dir: Path, graph_index: dict = None,
                  base_url: str = "http://localhost:8080",
                  global_exceptions: list = None) -> tuple:
    """为每个 API 生成一个 test file；返回 (生成文件列表, 字段漂移, API 实现标注)

    实现标注含 derived_error_cases：该 API 从 CodeGraph 约束派生的异常用例数。
    """
    generated = []
    field_drifts = []
    annotations = {}
    for api in apis:
        graph = match_graph(api, graph_index) if graph_index else None
        field_drifts.extend(diff_api_fields(api, graph))
        # 实现标注（即生成测试文件头部的 CodeGraph 注释），供 testing.run 整合进测试报告
        annotations[api["id"]] = {
            "matched": graph is not None,
            "controller": (graph or {}).get("controller", ""),
            "service": (graph or {}).get("service", ""),
        }
        test_code = render_api_test(api, graph, base_url, global_exceptions)
        # F-2 修复：文件名走 sct_ids 命名约定（末段后缀），避免同 feature 多 API 互相覆盖
        api_suffix = sct_ids.id_suffix(api["id"])
        file_name = sct_ids.api_test_filename(api["id"])
        file_path = out_dir / file_name
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(test_code, encoding="utf-8")
        generated.append(str(file_path))
        # 派生异常用例数（文件内 test_*_cg_error_* 函数）
        annotations[api["id"]]["derived_error_cases"] = \
            len(derive_error_cases(api, graph, api_suffix))
    return generated, field_drifts, annotations


def required_fields(api: dict, graph: dict | None = None) -> str:
    """返回 API 必填字段名列表（用于 Given/When/Then 意图说明）

    取 SoT 标注 ∪ 代码校验注解的**并集**（不是"以代码为准"）：
    SoT 是断言的真相锚点；并入代码约束只会让测试更严——
    SoT 标必填但代码未校验 → 缺字段用例期望 4xx 而实际 2xx →
    测试失败，**暴露实现缺陷**（这是特性，不是误报）。
    反向（代码校验了 SoT 未标的字段）报 REQUIRED_MISMATCH 供人工裁决，
    测试不静默迁就代码。
    """
    body = (api.get("request") or {}).get("body") or []
    names = {f["name"] for f in body if f.get("required", False)}
    if graph:
        for fg in (graph.get("request_dto") or {}).get("fields", []):
            if fg.get("required", False):
                names.add(fg["name"])
    # 按 SoT 定义顺序输出，图谱补充的排在后面
    order = [f["name"] for f in body]
    ordered = [n for n in order if n in names] + sorted(names - set(order))
    return "、".join(ordered) if ordered else "无 body 要求"


def split_api_response_schema(api: dict) -> tuple:
    """F-3 修复：兼容两种 response schema，返回 (success_status, error_cases)

    - 新规范: response_200.fields / error_codes: [400, 404, ...]
    - 旧规范: response.success / response.errors: [{status, condition, message}, ...]

    返回 (None, []) 表示两种 schema 都未提供 → 不生成成功用例（与旧行为一致：
    没有 response 定义时 success_cases 为空，测试文件只有注释头）。
    """
    api_id = api.get("id", "?")
    if "response_200" in api:
        status = (api.get("response_200") or {}).get("status", 200)
        errs = []
        for c in (api.get("error_codes") or []):
            errs.append({"status": int(c), "condition": f"error_code_{c}",
                         "message": "", "source": f"acceptance.yaml#apis[{api_id}].error_codes"})
        return status, errs
    resp = api.get("response")
    if isinstance(resp, dict):
        if "success" in resp:
            status = resp["success"].get("status", 200)
            errs = list(resp.get("errors") or [])
            return status, errs
        # 仅 fields 形式：默认 200 成功
        return 200, list(resp.get("errors") or [])
    return None, []


def render_api_test(api: dict, graph: dict | None = None,
                    base_url: str = "http://localhost:8080",
                    global_exceptions: list = None) -> str:
    """根据 API 规约渲染 pytest 文件（遵循 templates/unit-test-template.py 约定）

    **测试独立性原则（adversarial independence）**：断言期望值的唯一来源是
    SoT（success 状态/响应结构、errors[] 业务异常）。CodeGraph 只用于
    **构造请求**（字段类型/格式/枚举值/示例值），绝不反推断言——测试若从
    代码反推期望，code 的错误会被测试合法化（自己出题自己改卷）。
    代码与 SoT 的冲突走 FIELD_DRIFT / 测试失败浮出水面，由人裁决，
    不在生成期静默吸收。

    graph 非空时（CodeGraph 交换格式）：
      - 请求示例值优先取代码 example/enum/类型默认值（仅构造，不涉断言）
      - 必填判定 = SoT ∪ 代码校验注解（并集使测试更严，见 required_fields）
      - BASE_URL 取图谱 project.base_url
      - 异常用例 = SoT errors[]（业务异常，断言锚点=SoT）
        + CodeGraph 约束派生（cg_error：技术约束自洽性检查——
          验证"代码声明的约束被代码自己执行"，锚点是注解声明层
          而非运行时行为，属对抗补充，不替代 SoT 业务断言）
    global_exceptions（@ControllerAdvice 系统级异常）写入文件头部供审查，
    不生成用例（401/500 等不可自动触发，由安全/框架测试覆盖）。
    """
    api_id = api["id"]
    api_name = api["name"]
    method = api["method"]
    path = api["path"]
    spec_ref = api.get("spec_ref", "")
    req_fields = required_fields(api, graph)
    # F-2/F-3 修复：取 ID 最后一节；兼容两种 response schema
    api_num = sct_ids.id_suffix(api_id)
    success_status, error_cases_raw = split_api_response_schema(api)

    # 成功用例（F-3：兼容 response.success / response_200 两种写法）
    success_cases = []
    if success_status is not None:
        success_cases.append({
            "name": f"test_api_{api_num}_success",
            "intent": f"验证 {api_name} 接口的正常路径",
            "source": ("acceptance.yaml#apis[{api_id}].response_200"
                       if "response_200" in api
                       else f"acceptance.yaml#apis[{api_id}].response.success"),
            "given": f"服务可用，且请求体包含全部必填字段（{req_fields}）",
            "when": f"{method} {path} 提交合法请求体",
            "then": f"返回 {success_status}，响应结构与 success 定义一致",
            "request": build_request_example(api, graph),
            "expected_status": success_status,
        })

    # 异常用例（两类；F-3：error_codes 列表或 response.errors 数组都识别）
    error_cases = []
    for i, err in enumerate(error_cases_raw):
        then_line = f"返回 {err.get('status', 400)}"
        if err.get("message"):
            then_line += f"，且 message 包含 \"{err['message']}\""
        error_cases.append({
            "name": f"test_api_{api_num}_error_{i+1}",
            "intent": f"验证 {err.get('condition', '异常条件')} 时接口拒绝请求",
            "source": (f"acceptance.yaml#apis[{api_id}].error_codes"
                       if "error_codes" in api
                       else f"acceptance.yaml#apis[{api_id}].response.errors[{i+1}]"),
            "given": f"服务可用，但请求体缺失必填字段（{req_fields}）",
            "when": f"{method} {path} 提交非法请求体",
            "then": then_line,
            "request": build_error_request(api, err, graph),
            "expected_status": err.get("status", 400),
            "expected_message_contains": err.get("message", ""),
        })
    # CodeGraph 派生异常用例（约束/枚举/类型 → 系统性异常值，真相来源 codegraph:DTO.field）
    error_cases.extend(derive_error_cases(api, graph, api_num))

    # 渲染
    graph_note = (f"CodeGraph: {graph.get('controller', '')} → {graph.get('service', '')}"
                  if graph else "CodeGraph: 未提供（示例值为 SoT 启发式，建议提供 --codegraph）")
    # 系统级异常清单（@ControllerAdvice，全接口适用，供人工审查系统异常值全集）
    gx_lines = ""
    if global_exceptions:
        gx_lines = "\n系统级异常（@ControllerAdvice，全接口适用；不可自动触发，由安全/框架测试覆盖）:"
        for gx in global_exceptions:
            gx_lines += (f"\n  - {gx.get('status')} {gx.get('code', '')}"
                         f" {gx.get('message', '')}（{gx.get('exception', '')}）")
    template = f'''"""
AUTO-GENERATED FROM acceptance.yaml - DO NOT EDIT
Source: {spec_ref}
Generated: {datetime.now().isoformat()}
模板约定: extensions/sct/templates/unit-test-template.py

断言锚点: 本文件所有断言期望值来自 SoT (acceptance.yaml)，与实现无关。
CodeGraph 仅用于构造请求（字段类型/格式/示例值），不参与断言——
即使代码先行编写，测试也不以代码行为为期望基准。

API: {api_id} {api_name}
Method: {method}
Path: {path}
{graph_note}{gx_lines}

依赖注入: BASE_URL / Authorization 都由同目录 conftest.py 提供（环境变量覆盖）：
  - BASE_URL         (默认见 conftest.py)
  - API_AUTH_TOKEN   (可选；Bearer token;  缺则不设 Authorization)
"""
import pytest
import requests

API_PATH = "{path}"
HTTP_METHOD = "{method.lower()}"
'''
    for case in success_cases + error_cases:
        template += f'''

def {case["name"]}(session):
    """[意图] {case["intent"]}

    真相来源: {case["source"]}
    依据: {spec_ref}

    Given: {case["given"]}
    When:  {case["when"]}
    Then:  {case["then"]}
    """
    # Given：构造请求体（字段来自 SoT request.body 定义）
    payload = {case["request"]}

    # When：GET 用查询参数，其余用 JSON body——避免 GET 把 payload 当 body 发出去
    if HTTP_METHOD == "get":
        response = session.get(session.base_url + API_PATH, params=payload)
    else:
        response = session.request(
            HTTP_METHOD.upper(),
            session.base_url + API_PATH,
            json=payload,
        )

    # Then：断言预期结果（只在本段断言）
    assert response.status_code == {case["expected_status"]}, \\
        f"Expected {case["expected_status"]}, got {{response.status_code}}"
'''
        if case.get("expected_message_contains"):
            template += f'''    data = response.json()
    assert "{case["expected_message_contains"]}" in data.get("message", ""), \\
        f"Message not matched: {{data}}"
'''
    return template


def build_request_example(api: dict, graph: dict | None = None) -> str:
    """构造正常请求示例

    取值优先级：CodeGraph（真实代码 example/enum/类型默认）> SoT 启发式。
    图谱有而 SoT 未登记的字段也一并带上（合法请求应满足代码校验）。
    """
    body = build_valid_body(api, graph)
    return str(body) if body else "None"


def build_error_request(api: dict, err: dict, graph: dict | None = None) -> str:
    """构造异常请求示例（基于错误条件）

    缺失字段的选取：CodeGraph required 注解优先，否则用 SoT 标注。
    """
    graph_fields = graph_field_map(graph)
    body = {}
    for field in (api.get("request") or {}).get("body") or []:
        fg = graph_fields.get(field["name"])
        # 图谱有该字段 → 并入代码校验注解（并集语义，见 required_fields：
        # 使测试更严，SoT 标必填而代码未校验时用例失败暴露缺陷）；否则用 SoT 标注
        required = fg["required"] if fg else field.get("required", False)
        if not required:
            gv = graph_value(fg)
            body[field["name"]] = gv if gv is not None else example_value(field)
        else:
            # 异常用例：故意不填必填字段
            pass
    return str(body) if body else "None"


def example_value(field: dict):
    """根据 SoT 字段定义返回示例值（无 CodeGraph 时的取值链）

    优先级：SoT `example` 标注 > enum[0] > 字段名/类型启发式。
    启发式值过不了后端校验（如 @Pattern/@Email）导致测试失败时，
    修法是给 SoT 字段补 `example` 标注再重新生成（write-once：不手改
    测试文件）。example 属于**构造侧**（让请求合法到达业务逻辑层），
    与断言期望无关——调整它不违反对抗路原则。
    """
    if field.get("example") is not None:
        return field["example"]
    name = field["name"]
    ftype = field.get("type", "String")
    enum = field.get("enum")
    if enum:
        return enum[0]
    if "url" in name.lower() or name == "targetUrl":
        return "https://example.com/test"
    if ftype.startswith("String") or ftype == "String":
        if "name" in name.lower():
            return "登录测试"
        if "text" in name.lower():
            return "打开登录页填写用户名密码点击登录"
        if "content" in name.lower() or name == "parsedContent":
            return '[{"name":"登录测试","intent":"...","type":"PLAYWRIGHT","targetUrl":"https://example.com"}]'
        return f"test_{name}"
    if ftype == "Integer" or ftype == "Long":
        return 1
    if ftype == "Boolean":
        return True
    return None


# =====================================================================
# JUnit 版本自动检测（避免与存量测试混用）
# =====================================================================

def detect_junit_version(java_test_root: str) -> str:
    """扫描 java_test_root 下现有测试文件，识别 JUnit 版本。

    规则：若项目存量测试是 JUnit 4 则跟 4，否则默认 5（与用户约定一致）。
    返回 "4" / "5"。若 JUnit 4 与 5 同时出现，打印警告并默认 5（让用户用 --junit 显式覆盖）。
    """
    root = Path(java_test_root)
    if not root.exists():
        return "5"
    has4 = has5 = False
    for f in root.rglob("*.java"):
        try:
            t = f.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if "org.junit.Test" in t or "org.junit.runner.RunWith" in t:
            has4 = True
        if "org.junit.jupiter.api.Test" in t or "org.junit.jupiter.api" in t:
            has5 = True
    if has4 and not has5:
        return "4"
    if has4 and has5:
        print("⚠️  项目中同时发现 JUnit 4 与 JUnit 5 测试。按用户规则不能混用，默认 5。"
              "如需 JUnit 4 请用 --junit=4 显式覆盖。")
        return "5"
    return "5"


# =====================================================================
# Java 源码绑定（读公共签名/依赖，不读实现体）
# —— 解决"输入参数怎么和代码对上""哪些需要 mock"：
#    值(VALUES)与期望(EXPECTATIONS)来自 SoT；形参顺序/类型/协作者来自代码公共契约。
#    这是人写单测的方式：先看方法签名，再从规格取输入与期望。不属于"被代码带偏"。
# =====================================================================

_JAVA_PRIM = {"byte","short","int","long","float","double","boolean","char",
              "Byte","Short","Integer","Long","Float","Double","Boolean","Character"}
_JAVA_VALUE_FULL = {"java.lang.String","java.math.BigDecimal","java.time.LocalDate",
                    "java.time.LocalDateTime","java.time.LocalTime","java.util.UUID",
                    "java.util.Date","java.time.Instant","java.lang.Object"}
_JAVA_COLLECTION = {"List","Set","Collection","Map","java.util.List","java.util.Set",
                    "java.util.Collection","java.util.Map","java.util.Optional"}

def _is_value_type(t: str) -> bool:
    t = (t or "").strip().split("<")[0].strip()
    return t in _JAVA_PRIM or t in _JAVA_VALUE_FULL or t in _JAVA_COLLECTION


def _unconstructible(v, type_: str) -> bool:
    """SoT 输入值能否自动转成该类型的 Java 字面量；不能则需人工补 'call' 或构造值。"""
    t = (type_ or "").strip().split("<")[0].strip()
    if t in _JAVA_PRIM or t in ("String", "java.lang.String") or t in ("boolean", "Boolean"):
        return False
    if t in ("List", "Set", "Collection", "java.util.List", "java.util.Set",
             "java.util.Collection", "java.util.Optional"):
        if isinstance(v, (list, tuple)):
            return not all(isinstance(x, (int, float, bool, str, type(None))) for x in v)
        return True  # 未提供列表
    # 复杂对象（非值类型）：dict/对象无法自动 new，标记为不可构造
    return True


def _split_params(s: str) -> list:
    """把 '(a, b)' 内参数串拆成 [{type, name}]，尊重 <> 与 () 嵌套"""
    s = (s or "").strip()
    if not s:
        return []
    parts, depth, cur = [], 0, ""
    for ch in s:
        if ch in "<(":
            depth += 1
        elif ch in ">)":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(cur); cur = ""
        else:
            cur += ch
    if cur.strip():
        parts.append(cur)
    out = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        toks = p.split()
        if len(toks) >= 2:
            name = toks[-1].rstrip("[]")
            type_ = " ".join(toks[:-1]).rstrip("[]")
        else:
            name, type_ = "arg", toks[0].rstrip("[]")
        type_ = re.sub(r"^(final|volatile|transient)\s+", "", type_)
        out.append({"type": type_, "name": name})
    return out


def find_java_source(code_root: str, cls_full: str):
    """按包路径定位 .java；找不到则 rglob 简单类名"""
    root = Path(code_root)
    if not root.exists():
        return None
    pkg, simple = _java_class_name(cls_full)
    cand = root / (pkg.replace(".", "/") if pkg else "") / (simple + ".java")
    if cand.exists():
        return cand
    hits = list(root.rglob(simple + ".java"))
    return hits[0] if hits else None


def parse_java_class(source_path, cls_full: str) -> dict:
    """读类的公共契约：目标方法形参 + 协作者类型（构造器/字段依赖）。不读方法体。"""
    text = Path(source_path).read_text(encoding="utf-8", errors="ignore")
    pkg, simple = _java_class_name(cls_full)
    methods = {}
    # 目标方法（按名定位）；也顺带记所有 public 方法供回退
    for mm in re.finditer(r"\b([A-Za-z_]\w*)\s*\(([^)]*)\)\s*(?:throws[\w,\s.<>]+?)?\{", text):
        methods.setdefault(mm.group(1), _split_params(mm.group(2)))
    # 协作者：构造器参数 + private/@Autowired 字段，过滤掉值类型
    collaborators = []
    cm = re.search(r"\b" + re.escape(simple) + r"\s*\(([^)]*)\)", text)
    if cm:
        for p in _split_params(cm.group(1)):
            if not _is_value_type(p["type"]):
                collaborators.append(p["type"])
    for fm in re.finditer(r"(?:@Autowired\s*)?private\s+(?:final\s+)?([\w<>\[\],\s.]+?)\s+([A-Za-z_]\w*)\s*;", text):
        t = fm.group(1).strip()
        if not _is_value_type(t):
            collaborators.append(t)
    # 去重保序
    seen, uniq = set(), []
    for c in collaborators:
        if c not in seen:
            seen.add(c); uniq.append(c)
    return {"methods": methods, "collaborators": uniq}


def _java_value_typed(value, type_: str) -> str:
    """按声明类型把 SoT 值转 Java 字面量；复杂对象无字面量时给 null 并标记"""
    t = (type_ or "").strip().split("<")[0].strip()
    if t in ("List","Set","Collection","java.util.List","java.util.Set","java.util.Collection"):
        # JDK8 兼容：List.of/Map.of 是 Java9+ API，改用 Arrays.asList / Collections.emptyXxx
        if isinstance(value, (list, tuple)):
            elems = ", ".join(_java_value(v) for v in value)
            return f"java.util.Arrays.asList({elems})" if elems else "java.util.Collections.emptyList()"
        return "java.util.Collections.emptyList()"
    if t in ("Map","java.util.Map"):
        return "java.util.Collections.emptyMap()"
    if t in ("boolean","Boolean"):
        return "true" if value else "false"
    if t in ("int","long","short","byte","Integer","Long","Short","Byte"):
        try:
            return str(int(value))
        except Exception:
            return "0"
    if t in ("double","float","Double","Float"):
        try:
            return str(float(value)) + ("d" if t == "double" else "f")
        except Exception:
            return "0.0"
    if t in ("char","Character"):
        return _java_value(value)
    if t in ("String","java.lang.String") or value is None:
        return _java_value(value)
    # 复杂对象：SoT 未给可构造字面量 → null（调用方应标 BINDING_DRIFT）
    return "null"


# =====================================================================
# Java 单元测试生成（JUnit + Mockito，零 Spring）
# =====================================================================

def _java_value(v) -> str:
    """把 Python 字面量转成 Java 字面量（数字/布尔/字符串/null）"""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if v is None:
        return "null"
    s = str(v).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{s}"'


def _java_class_name(full: str) -> tuple[str, str]:
    """拆分 'com.demo.Foo' → ('com.demo', 'Foo')；无包名则包名返回空串"""
    parts = full.rsplit(".", 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return "", parts[0]


def _simple_name(full: str) -> str:
    return full.rsplit(".", 1)[-1]


def _display_name(rule_text: str, rid: str, tc: dict, exp: dict, inputs) -> str:
    """生成 @DisplayName 中文意图注解：规则文本 + 输入摘要 + 预期结果"""
    base = (rule_text or rid or "业务规则").strip()
    if isinstance(inputs, dict) and inputs:
        ins = ", ".join(f"{k}={_java_value(v)}" for k, v in inputs.items())
    elif isinstance(inputs, list):
        ins = ", ".join(_java_value(v) for v in inputs)
    else:
        ins = "无显式输入"
    if "throws" in exp:
        tail = f"输入 {ins} 时应抛出 {_simple_name(exp['throws'])}"
    elif "returns" in exp:
        tail = f"输入 {ins} 时应返回 {_java_value(exp['returns'])}"
    else:
        tail = f"输入 {ins} 时应正常执行"
    name = f"{rid}: {base} | {tail}" if rid else f"{base} | {tail}"
    return name.replace('"', '\\"')


def _infer_type(v) -> str:
    """根据 SoT 期望值推断 Java 字面量类型（用于声明 expectedResult）"""
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, int):
        return "int"
    if isinstance(v, float):
        return "double"
    if isinstance(v, str):
        return "String"
    return "Object"


def _literal_for_type(v, t: str) -> str:
    """把 SoT 期望值规范化为与声明类型匹配的字面量（避免 int/double 类型错配）"""
    lit = _java_value(v)
    t = (t or "Object").strip()
    if t in ("int", "long", "short", "byte"):
        s = lit.replace('"', '')
        try:
            num = float(s)
            return f"{int(num)}L" if t == "long" else str(int(num))
        except ValueError:
            return lit
    if t in ("double", "float"):
        s = lit.replace('"', '')
        try:
            num = float(s)
            suffix = "F" if t == "float" else ""
            if num.is_integer():
                return f"{int(num)}.0{suffix}"
            return f"{num}{suffix}"
        except ValueError:
            return lit
    return lit


def _camel_to_snake(name: str) -> str:
    """CamelCase 转 snake_case，用于 JUnit 4 / public 修饰符友好的方法名"""
    import re as _re
    s = _re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    s = _re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)
    return s.lower()


def _render_java_test_class(rules: list, junit_version: str, class_info: dict = None):
    """为同一目标类(同 cls_full 的多个规则)生成单个 JUnit 测试类；
    返回 (file_name, source, binding_drifts)。一个类只落一个测试文件，避免多规则互相覆盖。"""
    first = rules[0]
    target = first.get("target") or {}
    cls_full = target.get("class", "")
    # 每规则的 (rule_id, method) 用于 METHOD_NOT_FOUND 检测与逐案例绑定
    rule_methods = [(r.get("id", ""), (r.get("target") or {}).get("method", "")) for r in rules]
    rule_mocks = []
    for r in rules:
        rule_mocks.extend(r.get("mocks") or [])
    all_test_cases = []
    for r in rules:
        all_test_cases.extend(r.get("test_cases") or [])
    if not cls_full or not all_test_cases:
        return None

    binding_drifts = []
    params_cache = {}
    collaborators = []
    if class_info:
        collaborators = class_info.get("collaborators") or []
        for rid, m in rule_methods:
            pm = class_info.get("methods", {}).get(m)
            params_cache[m] = pm
            if pm is None:
                binding_drifts.append({
                    "rule": rid, "class": cls_full, "method": m,
                    "kind": "METHOD_NOT_FOUND",
                    "detail": f"SoT 目标方法 {cls_full}.{m} 未在代码公共契约中找到"
                              f"（改名/删除/签名变更）→ 需人工裁决：改 SoT 还是改代码",
                })

    pkg, cls_simple = _java_class_name(cls_full)
    test_cls_name = sct_ids.java_test_class_name(cls_full)
    file_name = test_cls_name + ".java"

    if junit_version == "5":
        imports = [
            f"import {cls_full};",
            "import org.junit.jupiter.api.Test;",
            "import org.junit.jupiter.api.DisplayName;",
            "import org.junit.jupiter.api.extension.ExtendWith;",
            "import org.mockito.InjectMocks;",
            "import org.mockito.Mock;",
            "import org.mockito.junit.jupiter.MockitoExtension;",
            "import static org.junit.jupiter.api.Assertions.*;",
            "import static org.mockito.Mockito.when;",
        ]
        class_anno = "@ExtendWith(MockitoExtension.class)"
        test_anno = "@Test"
        method_modifier = ""
    else:  # JUnit 4
        imports = [
            f"import {cls_full};",
            "import org.junit.Test;",
            "import org.mockito.InjectMocks;",
            "import org.mockito.Mock;",
            "import org.mockito.runners.MockitoJUnitRunner;",
            "import static org.junit.Assert.*;",
            "import static org.mockito.Mockito.when;",
        ]
        class_anno = "@RunWith(MockitoJUnitRunner.class)"
        test_anno = "@Test"
        method_modifier = "public "

    # 收集 test_cases 引用的异常/类，统一 import
    referenced = set()
    for tc in all_test_cases:
        exp = tc.get("expect") or {}
        for k in ("throws", "returns"):
            v = exp.get(k)
            if isinstance(v, str) and "." in v:
                referenced.add(v)
    for r in sorted(referenced):
        if r != cls_full:
            imports.append(f"import {r};")
    # mock 来源：SoT 显式 mocks > 自动协作者(构造器/字段依赖) > 无
    mocks = list(dict.fromkeys(rule_mocks))
    if not mocks and collaborators:
        mocks = collaborators
    # 跨包协作者需 import（同包/简单名不加，避免非法 import）
    for m in mocks:
        if "." in m and m != cls_full:
            imports.append(f"import {m};")
    # 形参类型若是 java.util 常见集合的简单名（如 List<Integer>），补 import 否则编译失败；
    # FQN 类型（java.util.List<...>）原样可编译，无需 import
    JUTIL_SIMPLE = {"List", "Set", "Map", "Collection", "ArrayList", "LinkedList",
                    "HashMap", "HashSet", "Queue", "Deque", "Iterator", "Optional"}
    for _, pm in params_cache.items():
        if not pm:
            continue
        for p in pm:
            top = (p.get("type") or "").split("<")[0].strip().rstrip("[]")
            if top in JUTIL_SIMPLE:
                imports.append(f"import java.util.{top};")
    imports = sorted(set(imports))

    # mock 字段
    mock_fields = []
    for i, m in enumerate(mocks):
        m_pkg, m_simple = _java_class_name(m)
        field_name = (m_simple[0].lower() + m_simple[1:]) if m_simple else f"mock{i}"
        mock_fields.append(f"    @Mock private {m_simple} {field_name};")
    inject_field = (
        "    // 被测对象：由 Mockito 将下方 @Mock 协作者注入，等价于 Arrange 阶段的实例化\n"
        f"    @InjectMocks private {cls_simple} service;"
    )

    # test 方法：逐规则 → 逐案例，按各自方法的公共签名绑定
    methods = []
    if class_info and any((params_cache.get(m) is None) for _, m in rule_methods):
        drift_msg = "; ".join(d["detail"] for d in binding_drifts)
        fail_call = ("org.junit.jupiter.api.Assertions.fail" if junit_version == "5"
                     else "org.junit.Assert.fail")
        methods.append(
            f"    {test_anno}\n    {method_modifier}void test_BINDING_DRIFT() {{\n"
            f"        // BINDING_DRIFT: SoT 与代码公共契约不一致，需人工确认 SoT 还是代码错。\n"
            f"        {fail_call}(\"{_java_value(drift_msg)}\");\n"
            f"    }}"
        )
    for r in rules:
        rid = r.get("id", "")
        rtext = r.get("text", "")
        m = (r.get("target") or {}).get("method", "")
        params = params_cache.get(m) if class_info else None
        for tc in (r.get("test_cases") or []):
            if params is None and class_info:
                continue  # 方法缺失已记录 drift，跳过逐案例生成
            tc_name = tc.get("name") or f"test_{m}"
            inputs = tc.get("inputs") or {}
            exp = tc.get("expect") or {}
            display = _display_name(rtext, rid, tc, exp, inputs)
            dn5 = f'    @DisplayName("{display}")\n' if junit_version == "5" else ""

            # ---- Arrange：按公共签名把 SoT 输入绑定为具名局部变量 ----
            arrange = []
            call = tc.get("call")
            if not call:
                if params:
                    arg_vars = []
                    for i, p in enumerate(params):
                        vname = p["name"] or f"arg{i}"
                        vtype = p["type"] or "Object"
                        provided = False
                        v = None
                        if isinstance(inputs, dict):
                            if vname in inputs:
                                v = inputs[vname]; provided = True
                            elif isinstance(inputs, list) and i < len(inputs):
                                v = inputs[i]; provided = True
                        if provided:
                            if _unconstructible(v, vtype):
                                binding_drifts.append({
                                    "rule": rid, "class": cls_full, "method": m,
                                    "kind": "UNCONSTRUCTABLE_ARG",
                                    "detail": f"形参 {vname}:{vtype} 的 SoT 输入无法自动构造 Java 字面量"
                                              f"（复杂对象/对象列表）。请在 SoT 该 test_case 提供 'call' 整段调用，"
                                              f"或给出可构造值；已置 null 使测试编译但运行失败，交由人工补齐。",
                                })
                                val = "null"
                            else:
                                val = _java_value_typed(v, vtype)
                        else:
                            val = _java_value_typed(None, vtype)
                            binding_drifts.append({
                                "rule": rid, "class": cls_full, "method": m,
                                "kind": "MISSING_INPUT",
                                "detail": f"形参 {vname}:{vtype} 在 SoT test_cases.inputs 中无对应值"
                                          f"（请补 inputs 或确认参数已移除）",
                            })
                        arrange.append(f"        {vtype} {vname} = {val};")
                        arg_vars.append(vname)
                    call = f"service.{m}({', '.join(arg_vars)})"
                elif isinstance(inputs, dict) and inputs:
                    # 方法存在但公共签名零参数，SoT 却给了 inputs——签名分歧，
                    # 报 BINDING_DRIFT 交人工裁决；不把参数硬塞进调用（会编译失败）
                    binding_drifts.append({
                        "rule": rid, "class": cls_full, "method": m,
                        "kind": "SIGNATURE_MISMATCH",
                        "detail": f"方法 {cls_full}.{m}() 公共签名无参数，"
                                  f"SoT test_cases.inputs 却提供了 {list(inputs.keys())}——"
                                  f"请确认参数是否已被移除（改 SoT）或实现缺失（改代码）",
                    })
                    call = f"service.{m}()"
                elif isinstance(inputs, list):
                    arg_vars = [f"arg{i}" for i in range(len(inputs))]
                    for i, v in enumerate(inputs):
                        arrange.append(f"        Object arg{i} = {_java_value(v)};")
                    call = f"service.{m}({', '.join(arg_vars)})"
                else:
                    call = f"service.{m}()"

            # ---- given：SoT 锚定的 mock 协作者桩（Arrange 的一部分，call 已确定后处理） ----
            given = tc.get("given") or []
            stub_lines = []
            for g in given:
                gcall = g.get("call") or g.get("when")
                gret = g.get("returns")
                if gcall and gret is not None:
                    stub_lines.append(f"        when({gcall}).thenReturn({_java_value(gret)});")
            arrange_final = list(arrange)
            arrange_final.extend(stub_lines)
            if mocks and not given and ("returns" in exp or "throws" in exp):
                binding_drifts.append({
                    "rule": rid, "class": cls_full, "method": m,
                    "kind": "MOCK_NOT_STUBBED",
                    "detail": f"方法 {m} 依赖 mock 协作者 {mocks}，但 SoT test_case 未提供 given 桩；"
                              f"测试可能因 mock 默认返回值(0/null)而失败。请在 test_case 补 given: "
                              f"[{{ call: '<mockVar>.<method>()', returns: <值> }}]。",
                })
                arrange_final.append(
                    "        // 注意：本测试依赖 mock 协作者，但 SoT 未提供 given 桩；"
                    "断言可能因 mock 默认返回值(0/null)失败，请补 given。")
            arrange_block = "\n".join(arrange_final) if arrange_final else "        // （无显式输入）"
            arr_comment = (
                "        // ==========================\n"
                "        // 1. Arrange (准备/输入)\n"
                "        // ==========================\n"
            )

            if "throws" in exp:
                ex_simple = _simple_name(exp["throws"])
                msg = f"{rid}: {rtext} 异常场景未按预期抛出 {ex_simple}"
                if junit_version == "5":
                    methods.append(
                        f"    {test_anno}\n{dn5}"
                        f"    {method_modifier}void {tc_name}() throws Exception {{\n"
                        f"{arr_comment}{arrange_block}\n"
                        "        // ==========================\n"
                        "        // 2 & 3. Act & Assert (执行与断言)\n"
                        "        // ==========================\n"
                        f"        assertThrows({ex_simple}.class, () -> {{\n"
                        f"            {call};\n"
                        f"        }}, \"{msg}\");\n    }}"
                    )
                else:
                    methods.append(
                        f"    {test_anno}(expected = {ex_simple}.class)\n"
                        f"    {method_modifier}void {tc_name}() throws Exception {{\n"
                        f"{arr_comment}{arrange_block}\n"
                        "        // ==========================\n"
                        "        // 2 & 3. Act & Assert (执行与断言)\n"
                        "        // ==========================\n"
                        f"        {call};  // 预期抛出 {ex_simple}\n    }}"
                    )
            elif "returns" in exp:
                ret_val = exp["returns"]
                ret_type = _infer_type(ret_val)
                ret_lit = _literal_for_type(ret_val, ret_type)
                msg = f"{rid}: {rtext} 返回值与预期不符"
                if junit_version == "5":
                    methods.append(
                        f"    {test_anno}\n{dn5}"
                        f"    {method_modifier}void {tc_name}() throws Exception {{\n"
                        f"{arr_comment}{arrange_block}\n"
                        f"        {ret_type} expectedResult = {ret_lit};  // 预期结果\n"
                        "        // ==========================\n"
                        "        // 2. Act (执行)\n"
                        "        // ==========================\n"
                        f"        Object actual = {call};  // JDK8 兼容：不写 var(Java10+)\n"
                        "        // ==========================\n"
                        "        // 3. Assert (断言)\n"
                        "        // ==========================\n"
                        f"        assertEquals(expectedResult, actual, \"{msg}\");\n    }}"
                    )
                else:
                    methods.append(
                        f"    {test_anno}\n"
                        f"    {method_modifier}void {tc_name}() throws Exception {{\n"
                        f"{arr_comment}{arrange_block}\n"
                        f"        {ret_type} expectedResult = {ret_lit};  // 预期结果\n"
                        "        // ==========================\n"
                        "        // 2 & 3. Act & Assert (执行与断言)\n"
                        "        // ==========================\n"
                        f"        assertEquals(expectedResult, {call}, \"{msg}\");\n    }}"
                    )
            else:
                methods.append(
                    f"    {test_anno}\n{dn5}"
                    f"    {method_modifier}void {tc_name}() throws Exception {{\n"
                    f"{arr_comment}{arrange_block}\n"
                    "        // ==========================\n"
                    "        // 2. Act (执行)\n"
                    "        // ==========================\n"
                    f"        {call};\n    }}"
                )

    parts = []
    if pkg:
        parts.append(f"package {pkg};\n")
    parts.append("\n".join(imports))
    parts.append("")
    rule_ids = ", ".join(sorted({r.get("id", "").upper() for r in rules if r.get("id")}))
    parts.append(
        f"// === Assertion authority = SoT (acceptance.yaml#rules[{rule_ids}]) ===\n"
        f"// 本文件由 SCT 依据 SoT(acceptance.yaml) 自动生成，采用经典 AAA 结构：\n"
        f"//   Arrange 准备输入(值来自 SoT test_cases) -> Act 执行被测方法 -> Assert 断言(期望来自 SoT)。\n"
        f"// 输入'值'取自 SoT；'形状'(形参类型/顺序)取自代码公共契约；协作者由 Mockito 自动 mock。\n"
        f"// 编码提示：本文件含中文 @DisplayName/注释，编译须以 UTF-8 读取\n"
        f"//   (javac -encoding UTF-8；Maven 请设 <project.build.sourceEncoding>UTF-8</project.build.sourceEncoding>)。\n"
        f"// 测试失败 = 代码与 SoT 的分歧信号，绝不静默改测试变绿；交人工裁决：\n"
        f"//   代码错 -> 改代码；SoT/测试错 -> 改 SoT 后重新生成。两种修正都须追溯到需求。"
    )
    parts.append("")
    parts.append(class_anno)
    if junit_version == "4":
        parts.append(f"public class {test_cls_name} {{")
    else:
        parts.append(f"class {test_cls_name} {{")
    if mock_fields:
        parts.append("\n".join(mock_fields))
        parts.append("")
    parts.append(inject_field)
    if methods:
        parts.append("")
        parts.append("\n\n".join(methods))
    parts.append("}")
    src = "\n".join(parts) + "\n"
    return file_name, src, binding_drifts


def gen_java_unit_tests(rules: list, java_test_root: str, junit_version: str,
                        code_root: str = "") -> tuple:
    """为含 target+test_cases 的规则生成 JUnit + Mockito 测试类（无 Spring）

    关键约束（用户要求）：
      - 禁用 Spring Boot：不生成 @SpringBootTest / @MockBean / @Autowired
      - 用 mock 方式：@Mock / @InjectMocks + MockitoExtension(JUnit5) 或 MockitoJUnitRunner(JUnit4)
      - 不可混用：优先 JUnit 5；项目存量为 JUnit 4 则跟 4
      - 断言来源 = SoT（防被代码带偏）：只读 rule.target/mocks/test_cases 取"值/期望"，
        绝不读取方法体来合成断言
      - 公共契约绑定（新增，回答"输入怎么对上"）：若提供 code_root，解析目标类公共契约
        （方法形参 + 协作者），用于按签名绑定输入、自动 mock，并检测 METHOD_NOT_FOUND /
        MISSING_INPUT 等 BINDING_DRIFT 交人工裁决；不读方法体，不反推断言。
    返回 (生成文件列表, binding_drifts 列表)
    """
    generated = []
    all_drifts = []
    root = Path(java_test_root)
    # 按目标类分组：同一 cls_full 的多个规则合并进一个测试文件（避免互相覆盖）
    groups = {}
    for rule in rules:
        cls_full = (rule.get("target") or {}).get("class", "")
        method = (rule.get("target") or {}).get("method", "")
        test_cases = rule.get("test_cases") or []
        if not cls_full or not method or not test_cases:
            continue
        groups.setdefault(cls_full, []).append(rule)
    for cls_full, grp in groups.items():
        class_info = None
        if code_root and cls_full:
            sp = find_java_source(code_root, cls_full)
            if sp:
                class_info = parse_java_class(sp, cls_full)
        result = _render_java_test_class(grp, junit_version, class_info)
        if not result:
            continue
        file_name, src_code, drifts = result
        all_drifts.extend(drifts)
        pkg, _ = _java_class_name(cls_full)
        out_dir = (root / pkg.replace(".", "/")) if pkg else root
        out_dir.mkdir(parents=True, exist_ok=True)
        file_path = out_dir / file_name
        file_path.write_text(src_code, encoding="utf-8")
        generated.append(str(file_path))
    return generated, all_drifts


# =====================================================================
# Python 离线静态断言（fallback：仅当规则没有 target+test_cases 时使用）
# =====================================================================

def _gen_python_rule_fallbacks(rules: list, out_dir: Path,
                               code_root: str = "backend/src/main/java",
                               unit_layer_note: str = "") -> list:
    """为缺少 target+test_cases 锚点的规则生成 Python 离线静态断言（fallback）

    当所有规则都有锚点时，本函数生成一个空的 test_rules.py 含说明，
    避免 pytest 报 "no tests ran"。unit_layer_note 描述本工程单测层由谁承载
    （v2.5.2 起按 --lang 探测结果生成，避免 Java 优先措辞出现在 Python 工程）。
    """
    generated = []
    cr = str(code_root).replace("\\", "/")
    L = []
    L.append('"""AUTO-GENERATED business rules tests from acceptance.yaml - DO NOT EDIT')
    L.append('模板约定: extensions/sct/templates/unit-test-template.py')
    L.append('执行机制: 离线静态断言（无需启动服务）——验证 SoT 登记的每条业务规则')
    L.append('在代码中有对应落地证据（注解/方法/异常/常量）。')
    L.append("")
    L.append('说明：' + (unit_layer_note
             or '单测层首选 JUnit + Mockito 的 Java 测试（gen_java_unit_tests）。'))
    L.append('本文件仅作为 fallback，对没有 target+test_cases 锚点的规则做声明存在性扫描。')
    L.append('推荐做法：在 SoT 的 rules[].target.class/method/test_cases 提供完整 Java 锚点，')
    L.append('本文件将退化为仅含说明的空 pytest 文件。')
    L.append('"""')
    L.append("import os")
    L.append("import pytest")
    L.append("import re")
    L.append("from pathlib import Path")
    L.append("")
    L.append('CODE_ROOT = Path(os.environ.get("SCT_CODE_ROOT", r"' + cr + '"))')
    L.append('_SRC_EXTS = (".java", ".kt", ".py", ".go", ".ts", ".js", ".cs")')
    L.append("")
    L.append("")
    L.append('def _scan_code(expect, kind="text", target=None):')
    L.append('    """在 CODE_ROOT 源码中搜索规则证据；返回 (found, where)。"""')
    L.append("    if not expect:")
    L.append("        return False, None")
    L.append("    files = []")
    L.append("    if target:")
    L.append("        for ext in _SRC_EXTS:")
    L.append("            files += list(CODE_ROOT.rglob(f\"*{target}*{ext}\"))")
    L.append("    if not files:")
    L.append("        for ext in _SRC_EXTS:")
    L.append("            files += list(CODE_ROOT.rglob(f\"*{ext}\"))")
    L.append("    pats = [expect]")
    L.append("    if kind == \"annotation\":")
    L.append("        pats.append(expect.lstrip(\"@\"))")
    L.append("    for f in files:")
    L.append("        try:")
    L.append("            t = f.read_text(encoding=\"utf-8\", errors=\"ignore\")")
    L.append("        except Exception:")
    L.append("            continue")
    L.append("        for p in pats:")
    L.append("            if p and p in t:")
    L.append("                return True, f.name")
    L.append("    return False, None")
    L.append("")
    L.append("")
    L.append("def _loose_tokens(text):")
    L.append('    """从规则文本提取候选搜索 token（大写词/长英文词/多位数字）。"""')
    L.append("    toks = set(re.findall(r\"[A-Z][A-Za-z0-9]{2,}\", text))")
    L.append("    toks |= set(re.findall(r\"\\b\\d{2,}\\b\", text))")
    L.append("    toks |= set(re.findall(r\"[a-zA-Z][a-zA-Z0-9]{3,}\", text))")
    L.append("    return [t for t in toks if len(t) >= 2]")
    L.append("")
    L.append("")

    if not rules:
        # 所有规则都有 Java 锚点 → 仅占位说明，避免 pytest "no tests ran"
        L.append("# 全部规则已在 Java 层（JUnit + Mockito）覆盖，本文件无测试。")
    else:
        for rule in rules:
            # F-5 修复：取 ID 最后一节（BR-F003-001→001），避免同 feature 多规则
            # 因 split('-')[1] 取到相同中段而生成重名函数（pytest 只跑最后一个）
            rule_num = sct_ids.id_suffix(rule["id"])
            rule_id = f"br_{rule_num}"
            rule_ref = rule["id"].upper()
            priority = rule.get("priority", "")
            text = rule.get("text", "")
            checks = rule.get("checks") or []
            intent_extra = f"（优先级 {priority}）" if priority else ""
            L.append("")
            L.append("def test_" + rule_id + "():")
            L.append('    """[意图] ' + text + intent_extra)
            L.append("")
            L.append("    真相来源: acceptance.yaml#rules[" + rule_ref + "]（derived_from: " + rule.get("derived_from", "") + "）")
            L.append("")
            L.append("    Given: 依据规则 " + rule_ref + " 的前置条件构造约束上下文")
            L.append("    When:  代码应声明并实现该约束")
            L.append("    Then:  在代码中发现对应落地证据（注解/方法/异常/常量）")
            L.append('    """')
            if checks:
                L.append("    checks = [")
                for c in checks:
                    kind = c.get("kind", "text")
                    expect = c.get("expect", "")
                    target = c.get("target")
                    L.append("        {\"kind\": " + repr(kind) + ", \"expect\": " + repr(expect) + ", \"target\": " + repr(target) + "},")
                L.append("    ]")
                L.append("    for c in checks:")
                L.append("        found, where = _scan_code(c[\"expect\"], c.get(\"kind\", \"text\"), c.get(\"target\"))")
                L.append('    assert found, ("规则 ' + rule_ref + ' 未找到代码证据: " + str(c["expect"]) + " (kind=" + str(c.get("kind")) + "; 代码根=" + str(CODE_ROOT) + ")")')
            else:
                L.append("    # 无任何锚点：宽松文本匹配 + 明确提示补 Java 或 checks 锚点")
                L.append("    tokens = _loose_tokens(" + repr(text) + ")")
                L.append("    found_any = False")
                L.append("    for tok in tokens:")
                L.append("        ok, _ = _scan_code(tok)")
                L.append("        if ok:")
                L.append("            found_any = True")
                L.append("            break")
                L.append("    if not found_any:")
                L.append('        pytest.skip("UNPROVEN: 规则 ' + rule_ref + ' 在单测层（target emitter）和静态断言层均无可执行锚点。\\n"')
                L.append('                 "  推荐：在 SoT 的 rules[' + rule_ref + '] 增加 target.class/method + test_cases 以生成 Java 单元测试；\\n"')
                L.append('                 "  或在 checks 字段声明代码证据（注解/方法/异常）。")')
    body = "\n".join(L) + "\n"
    file_path = out_dir / sct_ids.RULES_FALLBACK_FILENAME
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(body, encoding="utf-8")
    generated.append(str(file_path))
    return generated


def detect_lang(code_root: str) -> str:
    """探测工程语言，决定单测层 emitter（v2.5 语言中立第一步）：
      java   — 向上找到 pom.xml / build.gradle(.kts)（与 verification-gate 编译门同思路）
      python — code root 下存在 .py 源文件或 pyproject.toml / setup.py
      none   — 非标准工程（无构建标记、无 .py）：只保留 test_rules.py 静态断言层
    """
    p = Path(code_root)
    for cand in [p, *p.parents]:
        if (cand / "pom.xml").exists() \
                or (cand / "build.gradle").exists() \
                or (cand / "build.gradle.kts").exists():
            return "java"
    if p.exists():
        try:
            if any(p.rglob("*.java")):
                return "java"
            if any(p.rglob("*.py")):
                return "python"
        except OSError:
            pass
        for marker in ("pyproject.toml", "setup.py", "requirements.txt"):
            if (p / marker).exists():
                return "python"
    return "none"


def gen_pytest_unit_tests(rules: list, out_dir: Path, code_root: str = ".") -> tuple:
    """Python 单测 emitter（v2.5 语言中立）：为带 target+test_cases 的规则生成
    pytest 原生单测（test_unit_py.py，函数名 test_br_{suffix}——与规则覆盖率
    提取、追溯矩阵的既有约定兼容）。红线与 Java emitter 完全一致：
      - 输入'值'来自 SoT test_cases；'形状'经 inspect.signature 读公共签名（不读方法体）；
      - 断言期望只来自 SoT（returns / throws），绝不反推自代码；
      - SoT 与代码分歧 → BINDING_DRIFT（模块缺失/签名不匹配/缺输入/未打桩），不静默；
      - 构造器依赖用 stdlib unittest.mock.MagicMock 注入（零外部依赖）。
    返回 (生成文件列表, binding_drifts 列表)
    """
    code_path = Path(code_root).resolve()
    header = [
        '"""',
        "AUTO-GENERATED FROM acceptance.yaml - DO NOT EDIT",
        "Emitter: python (pytest 原生单测；Java 项目请用默认 JUnit emitter)",
        "",
        "断言锚点: 本文件所有断言期望值来自 SoT (acceptance.yaml)，与实现无关。",
        "输入'值'取自 SoT test_cases；'形状'(形参名/默认值)经 inspect 读公共签名，",
        "不读方法体——不能也不会反推断言。构造器依赖由 unittest.mock 自动 mock。",
        "测试失败 = 代码与 SoT 的分歧信号，绝不静默改测试变绿；交人工裁决：",
        "  代码错 -> 改代码；SoT/测试错 -> 改 SoT 后重新生成。",
        '"""',
        "import importlib",
        "import inspect",
        "import sys",
        "from pathlib import Path",
        "from unittest.mock import MagicMock",
        "",
        "import pytest",
        "",
        f"_SCT_CODE_ROOT = Path({str(code_path)!r})",
        "sys.path.insert(0, str(_SCT_CODE_ROOT))",
        "",
        "",
        "def _sct_resolve_exc(name):",
        '    """SoT throws 字段 → 异常类（builtins 短名或 module.Class 全名）。"""',
        "    if isinstance(name, type):",
        "        return name",
        "    mod, _, cls = str(name).rpartition('.')",
        "    if not mod:",
        "        import builtins",
        "        return getattr(builtins, cls)",
        "    return getattr(importlib.import_module(mod), cls)",
        "",
        "",
        "def _sct_make(cls):",
        '    """实例化被测类：无参直接构造；构造器有必填参数时用 MagicMock 注入。"""',
        "    try:",
        "        return cls(), {}",
        "    except TypeError:",
        "        sig = inspect.signature(cls.__init__)",
        "        kwargs, mocks = {}, {}",
        "        for n, prm in sig.parameters.items():",
        '            if n == "self" or prm.kind in (prm.VAR_POSITIONAL, prm.VAR_KEYWORD):',
        "                continue",
        "            if prm.default is inspect.Parameter.empty:",
        f"                mocks[n] = MagicMock(name=n)",
        "                kwargs[n] = mocks[n]",
        "        return cls(**kwargs), mocks",
        "",
    ]
    body: list[str] = []
    drifts: list[dict] = []
    generated: list[str] = []
    anchored: set[str] = set()

    for r in rules:
        rid = r.get("id") or "?"
        target = r.get("target") or {}
        cls_full = target.get("class") or ""
        method = target.get("method") or ""
        cases = r.get("test_cases") or []
        if not (cls_full and method and cases):
            continue
        anchored.add(rid)
        suffix = sct_ids.id_suffix(rid)
        rtext = (r.get("text", "") or "")[:50]

        mod_name, _, cls_name = cls_full.rpartition(".")
        mod_name = mod_name or cls_name
        mod_path = code_path.joinpath(*mod_name.split("."))
        mod_file = mod_path.with_suffix(".py")
        if not (mod_file.exists() or (mod_path / "__init__.py").exists()):
            drifts.append({
                "rule": rid, "class": cls_full, "method": method,
                "kind": "MODULE_NOT_FOUND",
                "detail": f"模块 {mod_name} 在代码根 {code_path} 下未找到（{mod_file.name}）——"
                          f"请确认 target.class 包路径与 --code 根一致（改 SoT 或传对 --code）",
            })

        # MOCK_NOT_STUBBED 对齐（v2.5.2，与 Java emitter 同语义，仅提示不阻断）：
        # gen 时用 ast 读构造器 __init__ 的**签名形状**（必填参数 = 无默认值的参数），
        # 不读方法体、不反推断言——与 Oracle Independence 红线一致。
        # 协作者必填但 SoT 未给 given 桩 → 运行时测试会因 mock 默认值诚实失败，
        # 这里补一个指向根因的信号。
        ctor_required: list[str] = []
        if mod_file.exists():
            try:
                import ast as _ast
                _tree = _ast.parse(mod_file.read_text(encoding="utf-8"))
                for _node in _ast.walk(_tree):
                    if isinstance(_node, _ast.ClassDef) and _node.name == cls_name:
                        for _item in _node.body:
                            if isinstance(_item, _ast.FunctionDef) and _item.name == "__init__":
                                _args = [a.arg for a in _item.args.args if a.arg != "self"]
                                _ndef = len(_item.args.defaults)
                                ctor_required = _args[:len(_args) - _ndef] if _ndef else _args
                        break
            except (OSError, SyntaxError, ValueError):
                ctor_required = []  # 读不到签名就不判（宁缺毋滥，避免误报）
        given_bases = {(g.get("call") or g.get("when") or "").split("(")[0].split(".")[0]
                       for g in (r.get("given") or [])}
        if ctor_required and not (set(ctor_required) & given_bases):
            drifts.append({
                "rule": rid, "class": cls_full, "method": method,
                "kind": "MOCK_NOT_STUBBED",
                "detail": f"构造器协作者 {', '.join(ctor_required)} 必填但 SoT test_case 未提供 "
                          f"given 桩；测试可能因 mock 默认值失败。请补 given: "
                          f"[{{ call: '<协作者>.<method>()', returns: <值> }}]。",
            })
            ctor_note = (f"    # ⚠️ MOCK_NOT_STUBBED：构造器协作者 {', '.join(ctor_required)} 未在 "
                         f"SoT given 打桩——断言可能因 mock 默认值失败，请补 given。\n")
        else:
            ctor_note = ""

        body.append(f"def {sct_ids.rule_test_func(rid)}():")
        body.append(f'    """[意图] {rid}: {rtext}')
        body.append("")
        body.append("    真相来源: acceptance.yaml#rules[" + rid + "].test_cases")
        body.append("    Given: 按公共签名构造被测实例（依赖自动 mock）")
        body.append("    When:  以 SoT inputs 调用 target 方法")
        body.append("    Then:  断言 returns / throws（只来自 SoT）")
        body.append('    """')
        body.append(f'    _mod_path = {mod_name!r}')
        body.append(f'    _cls_name = {cls_name!r}')
        body.append(f'    _method = {method!r}')
        body.append("    try:")
        body.append("        _cls = getattr(importlib.import_module(_mod_path), _cls_name)")
        body.append("    except (ImportError, AttributeError) as e:")
        body.append("        pytest.fail(")
        body.append('            f"SCT BINDING_DRIFT: SoT target {_mod_path}.{_cls_name} 无法导入（{e}）。"')
        body.append('            f" 请人工裁决：改 SoT 或修代码。",)')
        body.append("    _svc, _mocks = _sct_make(_cls)")
        if ctor_note:
            for _line in ctor_note.rstrip("\n").split("\n"):
                body.append(_line)
        body.append("    _sig = inspect.signature(getattr(_cls, _method))")
        for g in (r.get("given") or []):
            gcall = g.get("call") or g.get("when") or ""
            gret = g.get("returns")
            base = gcall.split("(")[0].split(".")[0] if gcall else ""
            chain = gcall.split("(")[0].split(".")[1:] if gcall else []
            if base and gret is not None:
                if chain:
                    body.append(f"    _mocks[{base!r}]." + ".".join(chain) + f".return_value = {gret!r}")
                else:
                    body.append(f"    # SoT given: {gcall} 返回 {gret!r}（call 未给方法链，跳过打桩）")
            else:
                body.append(f"    # SoT given 未提供 call/returns，跳过打桩")
        cases_lit = repr(cases)
        body.append(f"    _cases = {cases_lit}")
        body.append("    for _tc in _cases:")
        body.append("        _inputs = _tc.get('inputs') or {}")
        body.append("        _exp = _tc.get('expect') or {}")
        body.append("        _kwargs = {}")
        body.append("        for _n, _p in _sig.parameters.items():")
        body.append('            if _n == "self" or _p.kind in (_p.VAR_POSITIONAL, _p.VAR_KEYWORD):')
        body.append("                continue")
        body.append("            if _n in _inputs:")
        body.append("                _kwargs[_n] = _inputs[_n]")
        body.append("            else:")
        body.append("                pytest.fail(")
        body.append('                    f"SCT BINDING_DRIFT MISSING_INPUT: 参数 {_n} 在 SoT inputs 中无对应值"')
        body.append('                    f"（请补 inputs 或确认参数已移除）。",)')
        body.append("        for _k in _inputs:")
        body.append("            if _k not in _sig.parameters:")
        body.append("                pytest.fail(")
        body.append('                    f"SCT BINDING_DRIFT SIGNATURE_MISMATCH: 方法 {_method} 公共签名无参数 {_k}，"')
        body.append('                    f" SoT inputs 却提供了——请确认参数是否已移除（改 SoT）或实现缺失（改代码）。",)')
        body.append("        _fn = getattr(_svc, _method)")
        body.append("        if 'throws' in _exp:")
        body.append("            with pytest.raises(_sct_resolve_exc(_exp['throws'])):")
        body.append("                _fn(**_kwargs)")
        body.append("        elif 'returns' in _exp:")
        body.append("            _actual = _fn(**_kwargs)")
        body.append(f"            assert _actual == _exp['returns'], \\")
        body.append(f"                f\"{rid} 返回值与预期不符: 期望 {{_exp['returns']!r}} 实际 {{_actual!r}}\"")
        body.append("        else:")
        body.append("            _fn(**_kwargs)  # SoT 未声明 returns/throws：只执行（冒烟），断言留待 SoT 补充")
        body.append("")

    if not body:
        return [], []

    out = "\n".join(header) + "\n\n" + "\n".join(body)
    fp = out_dir / sct_ids.PYTEST_UNIT_FILENAME
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(out, encoding="utf-8")
    generated.append(str(fp))
    return generated, drifts


def gen_rule_tests(rules: list, out_dir: Path, code_root: str = "backend/src/main/java",
                   java_test_root: str = "src/test/java", junit_version: str = "5",
                   lang: str = "auto") -> tuple:
    """分发器（v2.5 语言中立）：按 lang 选择单测层 emitter。
      java   — JUnit + Mockito（默认，向后兼容）
      python — pytest 原生单测（test_unit_py.py，inspect + MagicMock，零外部依赖）
      none   — 非标准工程：不生成 target 单测，只保留 test_rules.py 静态断言层
      auto   — 按工程标记探测（pom/gradle → java；.py/pyproject → python；否则 none）
    无锚点规则一律保留 Python fallback（静态断言）。返回 (生成文件列表, binding_drifts)
    """
    if lang == "auto":
        lang = detect_lang(code_root)
    # fallback 头注释按实际承载层生成（v2.5.2：消除 Python 工程里的 Java 优先措辞）
    unit_notes = {
        "java": "单测层首选 JUnit + Mockito 的 Java 测试（gen_java_unit_tests）。",
        "python": "本工程单测层由 pytest emitter 承载（test_unit_py.py，inspect + unittest.mock）。",
        "none": "非标准工程：无 target 单测层，本文件是规则证据层的唯一载体（建议补 checks 锚点）。",
    }
    java_files, java_drifts = ([], [])
    if lang == "java":
        java_files, java_drifts = gen_java_unit_tests(rules, java_test_root, junit_version, code_root)
    elif lang == "python":
        java_files, java_drifts = gen_pytest_unit_tests(rules, out_dir, code_root)
    # lang == none：不生成 target 单测（静态断言层兜底，门禁按无锚点规则处理）
    fallback_rules = [r for r in rules
                      if not ((r.get("target") or {}).get("class")
                              and (r.get("target") or {}).get("method")
                              and r.get("test_cases"))]
    py_files = _gen_python_rule_fallbacks(fallback_rules, out_dir, code_root,
                                          unit_layer_note=unit_notes.get(lang, ""))
    return java_files + py_files, java_drifts


def gen_scenario_tests(features: list, out_dir: Path) -> list:
    """为每个验收场景生成一个测试（G/W/T 原文取自 SoT，保证意图说明与真相一致）"""
    generated = []
    if not features:
        return generated
    body = (
        '"""AUTO-GENERATED scenario tests from acceptance.yaml - DO NOT EDIT\n'
        '模板约定: extensions/sct/templates/unit-test-template.py\n"""\n'
        "import pytest\n\n"
    )
    for feat in features:
        feat_id = feat.get("id", "?")
        for sc in feat.get("acceptance_scenarios", []):
            sc_id = sc.get("id", "?")
            func_name = sct_ids.scenario_test_func(sc_id)
            body += f'''

def {func_name}():
    """[意图] {sc.get("given", "")}时，{sc.get("when", "")}，应{sc.get("then", "")}

    真相来源: acceptance.yaml#features[{feat_id}].acceptance_scenarios[{sc_id}]

    Given: {sc.get("given", "")}
    When:  {sc.get("when", "")}
    Then:  {sc.get("then", "")}
    """
    # Given：{sc.get("given", "")}
    # TODO: prepare preconditions

    # When：{sc.get("when", "")}
    # TODO: trigger the single action

    # Then：{sc.get("then", "")}
    # TODO: assert the observable outcome
    # 说明：验收场景是端到端用户旅程，单测层（离线静态校验）不在此执行。
    # 状态建模（v1.1.3）：未绑定可执行 adapter = UNPROVEN（skip），不是 BLOCK（fail）。
    # 场景的可执行验证由 API 层（test_api_*.py）与 E2E 层（testing.design 生成的
    # Playwright）承担；gap 明细见 _scenario_gaps.json。
    pytest.skip(
        f"UNPROVEN: 场景 {sc_id} 在单测层无可执行 adapter（用户旅程应经 API/E2E 触发）；"
        f"可执行验证见 test_api_*.py 与 e2e/auto_generated/*"
    )
'''
    file_path = out_dir / "test_scenarios.py"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(body, encoding="utf-8")
    generated.append(str(file_path))

    # P0-3 修复：gap artifact —— 机器可读的 UNPROVEN 清单，供 check/verify 消费
    gaps = [
        {"scenario_id": sc.get("id", "?"), "feature_id": feat.get("id", "?"),
         "status": "UNPROVEN", "reason": "no executable adapter at unit-test layer",
         "required_adapter": "api | playwright",
         "source": f"acceptance.yaml#features[{feat.get('id', '?')}].acceptance_scenarios[{sc.get('id', '?')}]"}
        for feat in features for sc in feat.get("acceptance_scenarios", [])
    ]
    if gaps:
        (out_dir / "_scenario_gaps.json").write_text(
            json.dumps({"version": 1, "kind": "scenario_gaps", "gaps": gaps},
                       ensure_ascii=False, indent=2), encoding="utf-8")
    return generated


def scan_generated_scenario_funcs(out_dir: Path) -> set:
    """F-7 修复：扫描实际生成的 test_scenarios.py，返回已生成的场景测试函数名集合
    （函数名小写、'-'→'_' 归一化，与 gen_scenario_tests 命名一致）"""
    funcs = set()
    for f in out_dir.rglob("test_scenarios*.py"):
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            continue
        for m in re.finditer(r"def (test_sc_\w+)", text):
            funcs.add(m.group(1))
    return funcs


def gen_coverage_report(acceptance: dict, out_dir: Path, field_drifts: list = None,
                        codegraph_ref: str = "", global_exceptions: list = None,
                        api_annotations: dict = None, binding_drifts: list = None) -> str:
    """生成覆盖率报告：spec → test 映射表（结构对齐 templates/coverage-report-template.md）"""
    apis = acceptance.get("apis", [])
    rules = acceptance.get("rules", [])
    features = acceptance.get("features", [])
    spec_ref = acceptance.get("_meta", {}).get("source_spec", "")

    report = f"""# Spec-Test Coverage Report

**Generated**: {datetime.now().isoformat()}
**SoT**: `{spec_ref}`
**CodeGraph**: `{'已接入（示例值/必填/异常值派生取自真实代码，见 FIELD_DRIFT / 异常值覆盖节）' if codegraph_ref else '未提供（示例值为 SoT 启发式，无异常值派生）'}`
**Tool**: acceptance-codegen.py

## API 覆盖

| API ID | 接口名 | 方法 | 路径 | 测试文件 | 用例数 | 其中派生异常 |
|--------|--------|------|------|----------|--------|--------------|
"""
    for api in apis:
        # F-2/F-3 修复：报告命名与 gen_api_tests 完全一致（走 sct_ids 命名约定）
        file_name = sct_ids.api_test_filename(api["id"])
        api_num = sct_ids.id_suffix(api["id"])
        case_count = 0
        s_status, s_errs = split_api_response_schema(api)
        if s_status is not None:
            case_count += 1
        case_count += len(s_errs)
        derived = (api_annotations or {}).get(api["id"], {}).get("derived_error_cases", 0)
        case_count += derived
        report += (f"| {api['id']} | {api['name']} | {api['method']} | `{api['path']}` "
                   f"| {file_name} | {case_count} | {derived or '-'} |\n")

    report += f"""

## 业务规则覆盖

| Rule ID | 规则 | 优先级 | 测试 |
|---------|------|--------|------|
"""
    for rule in rules:
        # F-8 修复：与 gen_rule_tests 的命名完全一致（取 [-1]），报告与代码对得上
        rule_suffix = sct_ids.id_suffix(rule["id"])
        report += f"| {rule['id']} | {rule['text']} | {rule.get('priority', '-')} | test_rules.py::test_br_{rule_suffix} |\n"

    report += f"""

## 验收场景覆盖

| Feature | 场景数 | 已派生 | 场景 ID（测试） |
|---------|--------|--------|-----------------|
"""
    for feat in features:
        scenarios = feat.get("acceptance_scenarios", [])
        # F-7 修复：已覆盖数 = 实际生成文件中存在的场景测试函数数（不再是场景数本身）
        gen_funcs = scan_generated_scenario_funcs(out_dir)
        covered_in_feat = sum(
            1 for sc in scenarios
            if "test_sc_" + sc.get("id", "?").lower().replace("-", "_") in gen_funcs
        )
        sc_refs = ", ".join(
            f"{sc.get('id', '?')} (test_sc_{sc.get('id', '?').lower().replace('-', '_')})"
            for sc in scenarios
        )
        report += (f"| {feat.get('id', '?')} {feat.get('name', '')} | {len(scenarios)} "
                   f"| {covered_in_feat} | {sc_refs} |\n")

    report += f"""

## 总计

- **API 接口**: {len(apis)}/{len(apis)}（目标 100%）
- **业务规则**: {len(rules)}/{len(rules)}（目标 100%）
- **验收场景**: {sum(len(f.get('acceptance_scenarios', [])) for f in features)} 个（每个场景的 given/when/then 已写入 test_scenarios.py docstring）
"""

    # 异常值覆盖（回答：是否拿到该系统的全部异常值）；F-3：兼容两种 schema
    sot_err_total = sum(len(split_api_response_schema(a)[1]) for a in apis)
    derived_total = sum((api_annotations or {}).get(a["id"], {}).get("derived_error_cases", 0)
                        for a in apis)
    report += f"""
## 异常值覆盖

异常值三个来源，逐层补全：

| 来源 | 覆盖内容 | 用例命名 | 数量 |
|------|----------|----------|------|
| SoT `errors[]` | 业务异常（规格登记的拒绝条件） | `test_api_x_error_n` | {sot_err_total} |
| CodeGraph 约束派生 | 字段校验异常：@NotNull 缺失 / @Max 越上界 / @Min 越下界 / @Size 长度 / @Pattern 格式 / 枚举外值 / 类型不匹配 | `test_api_x_cg_error_n` | {derived_total} |
| 系统级异常 | @ControllerAdvice 全局错误码（全接口适用） | 不生成用例（不可自动触发），见下表 | {len(global_exceptions or [])} |
"""
    if global_exceptions:
        report += """
**系统级异常清单（@ControllerAdvice，人工审查系统异常值全集）**：

| Status | Code | Message | Exception | 覆盖方式 |
|--------|------|---------|-----------|----------|
"""
        for gx in global_exceptions:
            report += (f"| {gx.get('status')} | {gx.get('code', '')} | {gx.get('message', '')} "
                       f"| {gx.get('exception', '')} | 安全/框架测试（如 401 需无 token、500 需故障注入） |\n")
    elif codegraph_ref:
        report += "\n> CodeGraph 未登记 `global_exceptions`（@ControllerAdvice），无法列出系统级异常全集。\n"

    # 字段级漂移（仅 --codegraph 接入时输出）
    if field_drifts:
        report += f"""
## FIELD_DRIFT（SoT ↔ 代码 DTO 字段比对）

> 来源：CodeGraph `{codegraph_ref}`。`MISSING_IN_CODE` 需优先处理（SoT 改了代码没跟上）；
> `UNSPEC_IN_SOT` 增量模式下建议补登记；`REQUIRED_MISMATCH` 核对必填口径。

| API | 字段 | 类型 | 说明 |
|-----|------|------|------|
"""
        for d in field_drifts:
            report += f"| {d['api']} | {d['field']} | {d['kind']} | {d['detail']} |\n"

    # 绑定漂移（回答"输入/签名/mock 怎么和代码对上"；SoT↔代码公共契约不一致，需人工裁决）
    if binding_drifts:
        report += f"""
## BINDING_DRIFT（SoT ↔ 代码公共契约比对）

> 来源：--code 解析目标类公共契约。这些不是"测试失败"，而是 **SoT 与代码不一致的信号**，
> 需人工裁决：改 SoT（重新生成）还是改代码。**切勿静默改测试凑绿**。

| Rule | 类.方法 | 类型 | 说明 |
|------|---------|------|------|
"""
        for d in binding_drifts:
            report += f"| {d.get('rule','')} | {d.get('class','')}.{d.get('method','')} | {d.get('kind','')} | {d.get('detail','')} |\n"

    report += f"""

## 单元测试行覆盖率目标

≥ 80% (JaCoCo 报告)
"""
    file_path = out_dir / "COVERAGE_REPORT.md"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(report, encoding="utf-8")
    return str(file_path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", required=True, help="Path to acceptance.yaml")
    parser.add_argument("--out", required=True, help="Output directory for generated tests")
    parser.add_argument("--codegraph", help="CodeGraph 导出 JSON（交换格式见 templates/"
                                            "codegraph-template.json）；提供后示例值/必填/枚举"
                                            "取自真实代码，并输出 FIELD_DRIFT")
    parser.add_argument("--force", action="store_true",
                        help="忽略 hash 缓存强制再生成（默认 SoT/CodeGraph 均未变化时秒退）")
    parser.add_argument("--only",
                        help="只生成指定 API 的接口测试（逗号分隔 API ID，如 API-001,API-003）；"
                             "规则/场景测试不受影响；定向生成不推进 hash 缓存")
    parser.add_argument("--skip-unit-tests", action="store_true",
                        help="跳过单测层（规则/Java 测试；仅生成接口测试 + conftest；纯 API-only 项目用）")
    parser.add_argument("--skip-api-tests", action="store_true",
                        help="跳过接口测试层（仅生成单测 + test_rules；纯库/工具项目用）")
    parser.add_argument("--only-rules",
                        help="只生成指定 rule 的测试（逗号分隔 rule ID，如 BR-001,BR-002；"
                             "配合 --skip-api-tests 用于精准单测再生成")
    parser.add_argument("--code", default="backend/src/main/java",
                        help="代码根目录（规则测试在此做离线静态断言；也可用环境变量 "
                             "SCT_CODE_ROOT 在运行时覆盖生成的默认值）")
    parser.add_argument("--java-test-root", default="src/test/java",
                        help="Java 测试根目录（有 target+test_cases 锚点的规则在此生成 "
                             "JUnit + Mockito 测试类）")
    parser.add_argument("--junit", default="auto", choices=["auto", "4", "5"],
                        help="JUnit 版本：auto(默认，按 detect_junit_version 自动识别；"
                             "优先 5；项目存量为 4 则跟 4；不可混用)、4、5")
    parser.add_argument("--lang", default="auto", choices=["auto", "java", "python", "none"],
                        help="单测层 emitter 语言（v2.5 语言中立）：auto(默认，按工程标记探测："
                             "pom/gradle→java，*.py/pyproject→python，否则 none=非标准工程只留静态断言层)、"
                             "java、python、none")
    parser.add_argument("--base-url",
                        help="接口测试 base_url（优先级：CLI --base-url > 环境变量 BASE_URL > "
                             "codegraph.project.base_url > 默认 http://localhost:8080）。"
                             "实际生效值由生成的 conftest.py 在 pytest 启动时读取环境变量 BASE_URL，"
                             "此处仅作为 conftest.py 的默认值")
    parser.add_argument("--module", default="",
                        help="F-19 增强：微服务模块名；指定后生成到 {out}/{module}/ 子目录隔离"
                             "（多模块项目按模块出产物，避免互相覆盖）")
    args = parser.parse_args()

    spec_path = Path(args.spec)
    # F-19 增强：--module 时输出隔离到 {out}/{module}/ 子目录
    out_dir = (Path(args.out) / args.module) if args.module else Path(args.out)
    meta_path = out_dir / "_codegen_meta.json"

    print(f"Loading acceptance spec: {spec_path}")
    acceptance = load_acceptance(spec_path)

    # ---- hash 短路缓存（SOP 时长控制）----
    # SoT 与 CodeGraph 均未变化且测试文件已存在 → 直接退出，0 个文件再生成。
    # --only 定向生成不参与/不推进缓存（部分再生成不能代表全量状态）。
    sot_hash = hashlib.sha256(spec_path.read_bytes()).hexdigest()
    cg_hash = (hashlib.sha256(Path(args.codegraph).read_bytes()).hexdigest()
               if args.codegraph and Path(args.codegraph).exists() else "")
    if not args.force and not args.only and meta_path.exists():
        try:
            prev_meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            prev_meta = {}
        # P0-5 修复：缓存命中必须满足——SoT/CodeGraph hash 一致 + 生成器版本一致
        # + write-once manifest 完整（手改/删文件/半生成状态都会击穿缓存再生成）
        expected = prev_meta.get("expected_outputs") or []
        intact, problems = manifest_intact(out_dir, expected)
        version_ok = prev_meta.get("generator_version") == GENERATOR_VERSION
        if (prev_meta.get("sot_hash") == sot_hash
                and prev_meta.get("codegraph_hash") == cg_hash
                and version_ok and expected and intact):
            print("⚡ hash 缓存命中：SoT 与 CodeGraph 均未变化，manifest 完整，跳过再生成（0 个文件）。")
            print("   如需强制再生成：--force")
            return
        if prev_meta.get("sot_hash") == sot_hash and not intact and expected:
            print(f"⚠️  manifest 校验发现 {len(problems)} 处异常（{'; '.join(problems[:3])}"
                  f"{'…' if len(problems) > 3 else ''}），击穿缓存重新生成。")
        elif not version_ok and prev_meta.get("generator_version"):
            print(f"ℹ️  生成器版本变化（{prev_meta.get('generator_version')} → {GENERATOR_VERSION}），重新生成。")

    codegraph = load_codegraph(args.codegraph)
    graph_index = build_graph_index(codegraph)
    # base_url 解析顺序：CLI --base-url > 环境变量 BASE_URL > codegraph.project.base_url > 默认
    graph_default = graph_base_url(codegraph)
    base_url = args.base_url or os.getenv("BASE_URL") or graph_default
    global_exceptions = (codegraph or {}).get("global_exceptions") or []

    # 预检：若将生成 API 测试但 BASE_URL 用的是兜底值且无 token 提示，提醒用户运行需环境变量
    if not args.skip_api_tests:
        if base_url == "http://localhost:8080" and not codegraph and not args.base_url:
            print("ℹ️  base_url 用的是默认值 http://localhost:8080（未传 --base-url / 未提供 codegraph）。")
            print("    生成的 test_api_*.py 需要运行前设置：")
            print("      BASE_URL=http://your-host:port   API_AUTH_TOKEN=xxx   pytest tests/generated/")
            print("    也可以用 --base-url 显式传入，或 --skip-api-tests 跳过本层生成。")
    if codegraph:
        print(f"CodeGraph loaded: {len(graph_index)} APIs, base_url={base_url}, "
              f"global_exceptions={len(global_exceptions)}")
        unmatched = len(acceptance.get("apis", [])) - sum(
            1 for a in acceptance.get("apis", []) if match_graph(a, graph_index))
        if unmatched:
            print(f"⚠️  {unmatched} 个 SoT API 未在 CodeGraph 中匹配到（将按纯 SoT 生成）")

    apis = acceptance.get("apis", [])
    rules = acceptance.get("rules", [])
    features = acceptance.get("features", [])

    if args.only_rules:
        keep_rules = {x.strip() for x in args.only_rules.split(",") if x.strip()}
        rules = [r for r in rules if r.get("id") in keep_rules]
        print(f"--only-rules：只生成 {len(rules)} 条 rule（{sorted(keep_rules)}）")

    if args.only:
        keep = {x.strip().upper() for x in args.only.split(",") if x.strip()}
        apis = [a for a in apis if str(a.get("id", "")).upper() in keep]
        missing = keep - {str(a.get("id", "")).upper() for a in apis}
        if missing:
            print(f"⚠️  未在 SoT 中找到: {', '.join(sorted(missing))}")
        print(f"--only 定向生成: {len(apis)} 个 API"
              f"（{', '.join(str(a['id']) for a in apis) or '无'}）")

    print(f"Found {len(apis)} APIs, {len(rules)} business rules, "
          f"{sum(len(f.get('acceptance_scenarios', [])) for f in features)} scenarios")

    # 规则测试（含 BINDING_DRIFT 检测）：在 codegen_meta 落盘前生成，以便写入 meta
    print("Generating rule tests...")
    junit_version = args.junit
    if junit_version == "auto":
        junit_version = detect_junit_version(args.java_test_root)
        print(f"JUnit version auto-detected: {junit_version}")
    else:
        print(f"JUnit version (explicit): {junit_version}")
    rule_files, binding_drifts = ([], [])
    if not args.skip_unit_tests:
        emitter = args.lang
        if emitter == "auto":
            emitter = detect_lang(args.code)
        print(f"Unit-test emitter language: {emitter}"
              + ("（auto 探测）" if args.lang == "auto" else ""))
        rule_files, binding_drifts = gen_rule_tests(rules, out_dir, args.code,
                                                    args.java_test_root, junit_version,
                                                    lang=emitter)
        for f in rule_files:
            print(f"  + {f}")
        if binding_drifts:
            print(f"⚠️  {len(binding_drifts)} 个绑定漂移（BINDING_DRIFT），详见 COVERAGE_REPORT.md（需人工裁决 SoT 还是代码）")
    else:
        print("⏭️  --skip-unit-tests：跳过单测层生成")

    api_files, field_drifts, api_annotations = ([], [], {})
    conftest_path = None
    if not args.skip_api_tests:
        print("Generating API tests...")
        api_files, field_drifts, api_annotations = gen_api_tests(apis, out_dir, graph_index,
                                                                 base_url, global_exceptions)
        for f in api_files:
            print(f"  + {f}")

        # 生成 conftest.py：把 BASE_URL 与 auth 留给 pytest 启动时按环境变量读
        conftest_path = gen_conftest(out_dir, base_url)
        print(f"  + {conftest_path}  (BASE_URL={base_url} ; set API_AUTH_TOKEN for auth)")
    else:
        print("⏭️  --skip-api-tests：跳过接口测试生成")

    # --only 定向生成：合并上次 meta 的标注/漂移——meta 是 testing.run 报告的数据源，
    # 不能因定向生成丢失未涉及 API 的实现标注与 FIELD_DRIFT
    if args.only and meta_path.exists():
        try:
            prev_meta_only = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            prev_meta_only = {}
        prev_ann = prev_meta_only.get("api_annotations") or {}
        merged_ann = {k: v for k, v in prev_ann.items() if k not in api_annotations}
        merged_ann.update(api_annotations)
        api_annotations = merged_ann
        # 漂移按 (api, field, kind) 去重合并，本轮结果优先
        seen = {(d.get("api"), d.get("field"), d.get("kind")) for d in field_drifts}
        field_drifts = field_drifts + [
            d for d in prev_meta_only.get("field_drifts") or []
            if (d.get("api"), d.get("field"), d.get("kind")) not in seen]
        if not codegraph:
            global_exceptions = prev_meta_only.get("global_exceptions") or []

    if field_drifts:
        print(f"⚠️  {len(field_drifts)} 个字段级漂移（FIELD_DRIFT），详见 COVERAGE_REPORT.md")
    derived_total = sum(a.get("derived_error_cases", 0) for a in api_annotations.values())
    if codegraph:
        print(f"  派生异常用例（约束/枚举/类型）: {derived_total} 个（test_*_cg_error_*）")

    # 机器可读产物：testing.run 自动发现后整合进最终测试报告
    # （头部 CodeGraph 标注 / 3.2 实现列 / 6.2 FIELD_DRIFT 节 / 系统级异常）
    # 注：expected_outputs（write-once manifest）在全部文件生成完后补充（见 main 末尾）
    codegen_meta = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "generator_version": GENERATOR_VERSION,
        "codegraph": args.codegraph or "",
        "api_annotations": api_annotations,
        "field_drifts": field_drifts,
        "binding_drifts": binding_drifts,
        "derived_error_cases_total": derived_total,
        "global_exceptions": global_exceptions,
    }
    # hash 缓存只在全量生成时推进（--only 定向生成不代表全量状态，不写 hash，
    # 下次全量运行会自然再生成，保证缓存语义正确）
    if not args.only:
        codegen_meta["sot_hash"] = sot_hash
        codegen_meta["codegraph_hash"] = cg_hash

    # 规则测试已在上方（API 测试之前）生成，含 BINDING_DRIFT 检测

    print("Generating scenario tests...")
    scenario_files = gen_scenario_tests(features, out_dir)
    for f in scenario_files:
        print(f"  + {f}")

    print("Generating coverage report...")
    report = gen_coverage_report(acceptance, out_dir, field_drifts, args.codegraph or "",
                                 global_exceptions, api_annotations, binding_drifts)
    print(f"  + {report}")

    # ---- write-once manifest（P0-5 修复）：记录全部生成文件的 sha256，
    # check 侧据此验证"生成测试未被手改"；缓存命中也要求 manifest 完整匹配。
    all_outputs = list(api_files) + list(rule_files) + list(scenario_files)
    conftest = out_dir / "conftest.py"
    if conftest.exists():
        all_outputs.append(str(conftest))
    manifest = []
    for f in all_outputs:
        fp = Path(f)
        if fp.exists():
            # 记录相对 out_dir 的路径（Java 单测带包路径，如 com/demo/UpControllerTest.java）
            try:
                rel = str(fp.resolve().relative_to(out_dir.resolve())).replace("\\", "/")
            except ValueError:
                rel = fp.name
            manifest.append({
                "path": rel,
                "sha256": hashlib.sha256(fp.read_bytes()).hexdigest(),
            })
    codegen_meta["expected_outputs"] = manifest
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps(codegen_meta, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    print(f"  + {meta_path}")

    print(f"\nDone. Generated {len(api_files) + len(rule_files) + len(scenario_files)} test files.")
    print(f"API coverage: {len(api_files)}/{len(apis)}")
    print(f"Rule coverage: {len(rules)}/{len(rules)}")
    print("Next: implement code to pass these tests.")


if __name__ == "__main__":
    main()
