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
sct.check 自动发现后把 CodeGraph 标注与字段级漂移整合进最终测试报告。
"""
import yaml
import json
import argparse
import hashlib
import re
from pathlib import Path
from datetime import datetime


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
        # 实现标注（即生成测试文件头部的 CodeGraph 注释），供 sct.check 整合进测试报告
        annotations[api["id"]] = {
            "matched": graph is not None,
            "controller": (graph or {}).get("controller", ""),
            "service": (graph or {}).get("service", ""),
        }
        test_code = render_api_test(api, graph, base_url, global_exceptions)
        file_name = f"test_api_{api['id'].split('-')[1].lower()}.py"
        file_path = out_dir / file_name
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(test_code, encoding="utf-8")
        generated.append(str(file_path))
        # 派生异常用例数（文件内 test_*_cg_error_* 函数）
        annotations[api["id"]]["derived_error_cases"] = \
            len(derive_error_cases(api, graph, api["id"].split("-")[1].lower()))
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
    api_num = api_id.split("-")[1].lower()

    # 成功用例
    success_cases = []
    if "response" in api and "success" in api["response"]:
        success = api["response"]["success"]
        success_cases.append({
            "name": f"test_api_{api_num}_success",
            "intent": f"验证 {api_name} 接口的正常路径",
            "source": f"acceptance.yaml#apis[{api_id}].response.success",
            "given": f"服务可用，且请求体包含全部必填字段（{req_fields}）",
            "when": f"{method} {path} 提交合法请求体",
            "then": f"返回 {success.get('status', 200)}，响应结构与 success 定义一致",
            "request": build_request_example(api, graph),
            "expected_status": success.get("status", 200),
        })

    # 异常用例（两类）
    error_cases = []
    if "response" in api and "errors" in api["response"]:
        for i, err in enumerate(api["response"]["errors"]):
            then_line = f"返回 {err.get('status', 400)}"
            if err.get("message"):
                then_line += f"，且 message 包含 \"{err['message']}\""
            error_cases.append({
                "name": f"test_api_{api_num}_error_{i+1}",
                "intent": f"验证 {err.get('condition', '异常条件')} 时接口拒绝请求",
                "source": f"acceptance.yaml#apis[{api_id}].response.errors[{i+1}]",
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
"""
import pytest
import requests

BASE_URL = "{base_url}"
API_PATH = "{path}"

'''
    for case in success_cases + error_cases:
        template += f'''

def {case["name"]}():
    """[意图] {case["intent"]}

    真相来源: {case["source"]}
    依据: {spec_ref}

    Given: {case["given"]}
    When:  {case["when"]}
    Then:  {case["then"]}
    """
    # Given：构造请求体（字段来自 SoT request.body 定义）
    payload = {case["request"]}

    # When：触发单一动作
    response = requests.{method.lower()}(
        BASE_URL + API_PATH,
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


def _camel_to_snake(name: str) -> str:
    """CamelCase 转 snake_case，用于 JUnit 4 / public 修饰符友好的方法名"""
    import re as _re
    s = _re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    s = _re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)
    return s.lower()


def _render_java_test_class(rule: dict, junit_version: str):
    """生成单个 JUnit 测试类源码；返回 (file_name, source) 或 None（缺关键字段）"""
    target = rule.get("target") or {}
    cls_full = target.get("class", "")
    method = target.get("method", "")
    mocks = rule.get("mocks") or []
    test_cases = rule.get("test_cases") or []
    if not cls_full or not method or not test_cases:
        return None

    pkg, cls_simple = _java_class_name(cls_full)
    test_cls_name = cls_simple + "Test"
    file_name = test_cls_name + ".java"

    if junit_version == "5":
        imports = [
            f"import {cls_full};",
            "import org.junit.jupiter.api.Test;",
            "import org.junit.jupiter.api.extension.ExtendWith;",
            "import org.mockito.InjectMocks;",
            "import org.mockito.Mock;",
            "import org.mockito.junit.jupiter.MockitoExtension;",
            "import static org.junit.jupiter.api.Assertions.*;",
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
        ]
        class_anno = "@RunWith(MockitoJUnitRunner.class)"
        test_anno = "@Test"
        method_modifier = "public "

    # 收集 test_cases 引用的异常/类，统一 import
    referenced = set()
    for tc in test_cases:
        exp = tc.get("expect") or {}
        for k in ("throws", "returns"):
            v = exp.get(k)
            if isinstance(v, str) and "." in v:
                referenced.add(v)
    for r in sorted(referenced):
        if r != cls_full:
            imports.append(f"import {r};")
    imports = sorted(set(imports))

    # mock 字段
    mock_fields = []
    for i, m in enumerate(mocks):
        m_pkg, m_simple = _java_class_name(m)
        field_name = (m_simple[0].lower() + m_simple[1:]) if m_simple else f"mock{i}"
        mock_fields.append(f"    @Mock private {m_simple} {field_name};")
    inject_field = f"    @InjectMocks private {cls_simple} service;"

    # test 方法
    methods = []
    for tc in test_cases:
        tc_name = tc.get("name") or f"test_{method}"
        # 参数：优先用 call（整段方法调用），否则从 inputs dict 拼
        call = tc.get("call")
        if not call:
            inputs = tc.get("inputs") or {}
            if isinstance(inputs, dict) and inputs:
                args = ", ".join(_java_value(v) for v in inputs.values())
            else:
                args = ""
            call = f"service.{method}({args})"
        exp = tc.get("expect") or {}

        if "throws" in exp:
            ex_full = exp["throws"]
            ex_simple = _simple_name(ex_full)
            if junit_version == "5":
                method_body = (
                    f"        assertThrows({ex_simple}.class, () -> {{\n"
                    f"            {call};\n"
                    f"        }});"
                )
                methods.append(
                    f"    {test_anno}\n    {method_modifier}void {tc_name}() {{\n"
                    f"{method_body}\n    }}"
                )
            else:
                # JUnit 4: @Test(expected=...) 最干净
                methods.append(
                    f"    {test_anno}(expected = {ex_simple}.class)\n"
                    f"    {method_modifier}void {tc_name}() {{\n"
                    f"        {call};\n"
                    f"    }}"
                )
        elif "returns" in exp:
            ret = _java_value(exp["returns"])
            method_body = (
                f"        Object result = {call};\n"
                f"        assertEquals({ret}, result);"
            )
            methods.append(
                f"    {test_anno}\n    {method_modifier}void {tc_name}() {{\n"
                f"{method_body}\n    }}"
            )
        else:
            # 无 expect（默认 noThrow）：直接调用，让 JUnit 报告未预期异常
            methods.append(
                f"    {test_anno}\n    {method_modifier}void {tc_name}() {{\n"
                f"        {call};\n"
                f"    }}"
            )

    parts = []
    if pkg:
        parts.append(f"package {pkg};\n")
    parts.append("\n".join(imports))
    parts.append("")
    rule_id = (rule.get("id") or "RULE").upper()
    parts.append(
        f"// === Assertion authority = SoT (acceptance.yaml#rules[{rule_id}]) ===\n"
        f"// This test is derived from SoT test_cases; its expectation comes from the\n"
        f"// requirement, NOT from the implementation under test. If the implementation\n"
        f"// deviates from SoT, this test MUST fail -- do not edit this test to please code."
    )
    parts.append("")
    parts.append(class_anno)
    if junit_version == "4":
        # JUnit 4 类需 public
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
    return file_name, src


def gen_java_unit_tests(rules: list, java_test_root: str, junit_version: str) -> list:
    """为含 target+test_cases 的规则生成 JUnit + Mockito 测试类（无 Spring）

    关键约束（用户要求）：
      - 禁用 Spring Boot：不生成 @SpringBootTest / @MockBean / @Autowired
      - 用 mock 方式：@Mock / @InjectMocks + MockitoExtension(JUnit5) 或 MockitoJUnitRunner(JUnit4)
      - 不可混用：优先 JUnit 5；项目存量为 JUnit 4 则跟 4
      - 断言来源 = SoT（防被代码带偏）：本函数只读 rule.target / mocks / test_cases，
        绝不读取代码体来合成断言；代码是被测黑盒，test_cases.expect 唯一决定断言。
    """
    generated = []
    root = Path(java_test_root)
    for rule in rules:
        result = _render_java_test_class(rule, junit_version)
        if not result:
            continue
        file_name, src = result
        cls_full = (rule.get("target") or {}).get("class", "")
        pkg, _ = _java_class_name(cls_full)
        out_dir = (root / pkg.replace(".", "/")) if pkg else root
        out_dir.mkdir(parents=True, exist_ok=True)
        file_path = out_dir / file_name
        file_path.write_text(src, encoding="utf-8")
        generated.append(str(file_path))
    return generated


# =====================================================================
# Python 离线静态断言（fallback：仅当规则没有 target+test_cases 时使用）
# =====================================================================

def _gen_python_rule_fallbacks(rules: list, out_dir: Path,
                               code_root: str = "backend/src/main/java") -> list:
    """为缺少 target+test_cases 锚点的规则生成 Python 离线静态断言（fallback）

    当所有规则都有 Java 锚点时，本函数生成一个空的 test_rules.py 含说明，
    避免 pytest 报 "no tests ran"。
    """
    generated = []
    cr = str(code_root).replace("\\", "/")
    L = []
    L.append('"""AUTO-GENERATED business rules tests from acceptance.yaml - DO NOT EDIT')
    L.append('模板约定: extensions/sct/templates/unit-test-template.py')
    L.append('执行机制: 离线静态断言（无需启动服务）——验证 SoT 登记的每条业务规则')
    L.append('在代码中有对应落地证据（注解/方法/异常/常量）。')
    L.append("")
    L.append('说明：单测层首选 JUnit + Mockito 的 Java 测试（gen_java_unit_tests）。')
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
            rule_num = rule["id"].split("-")[1].lower()
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
                L.append('        pytest.fail("规则 ' + rule_ref + ' 在 Java 单测层（首选 JUnit + Mockito）和 Python fallback 层均无可执行锚点。\\n"')
                L.append('                 "  推荐：在 SoT 的 rules[' + rule_ref + '] 增加 target.class/method + test_cases 以生成 Java 单元测试；\\n"')
                L.append('                 "  或在 checks 字段声明代码证据（注解/方法/异常）。")')
    body = "\n".join(L) + "\n"
    file_path = out_dir / "test_rules.py"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(body, encoding="utf-8")
    generated.append(str(file_path))
    return generated


def gen_rule_tests(rules: list, out_dir: Path, code_root: str = "backend/src/main/java",
                   java_test_root: str = "src/test/java", junit_version: str = "5") -> list:
    """分发器：单测层首选 JUnit + Mockito Java 测试，无锚点规则保留 Python fallback

    行为：
      - 含 target.class + target.method + test_cases 的规则 → gen_java_unit_tests
        （JUnit 5: @ExtendWith(MockitoExtension.class)；JUnit 4: @RunWith(MockitoJUnitRunner.class)）
      - 其余规则 → _gen_python_rule_fallbacks（离线静态扫描，明确标注为 fallback）
    """
    java_files = gen_java_unit_tests(rules, java_test_root, junit_version)
    fallback_rules = [r for r in rules
                      if not ((r.get("target") or {}).get("class")
                              and (r.get("target") or {}).get("method")
                              and r.get("test_cases"))]
    py_files = _gen_python_rule_fallbacks(fallback_rules, out_dir, code_root)
    return java_files + py_files


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
            func_name = "test_sc_" + sc_id.lower().replace("-", "_")
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
    # 场景的可执行验证由 API 层（test_api_*.py）与 E2E 层（sct.e2e 生成的
    # Playwright）承担。若需在 SoT 为该场景补充 target_api，可在此生成接口级断言。
    pytest.fail(
        f"场景 {sc_id} 在单测层（离线静态校验）不可执行：用户旅程应经 API/E2E 触发。"
        f" 可执行验证见 test_api_*.py（参数/业务校验）与 e2e/auto_generated/*（端到端）。"
    )
'''
    file_path = out_dir / "test_scenarios.py"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(body, encoding="utf-8")
    generated.append(str(file_path))
    return generated


def gen_coverage_report(acceptance: dict, out_dir: Path, field_drifts: list = None,
                        codegraph_ref: str = "", global_exceptions: list = None,
                        api_annotations: dict = None) -> str:
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
        api_num = api["id"].split("-")[1].lower()
        file_name = f"test_api_{api_num}.py"
        case_count = 0
        resp = api.get("response", {})
        if "success" in resp:
            case_count += 1
        case_count += len(resp.get("errors", []))
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
        report += f"| {rule['id']} | {rule['text']} | {rule.get('priority', '-')} | test_rules.py::test_{rule['id'].lower().replace('-', '_')} |\n"

    report += f"""

## 验收场景覆盖

| Feature | 场景数 | 已派生 | 场景 ID（测试） |
|---------|--------|--------|-----------------|
"""
    for feat in features:
        scenarios = feat.get("acceptance_scenarios", [])
        sc_refs = ", ".join(
            f"{sc.get('id', '?')} (test_sc_{sc.get('id', '?').lower().replace('-', '_')})"
            for sc in scenarios
        )
        report += f"| {feat.get('id', '?')} {feat.get('name', '')} | {len(scenarios)} | {len(scenarios)} | {sc_refs} |\n"

    report += f"""

## 总计

- **API 接口**: {len(apis)}/{len(apis)}（目标 100%）
- **业务规则**: {len(rules)}/{len(rules)}（目标 100%）
- **验收场景**: {sum(len(f.get('acceptance_scenarios', [])) for f in features)} 个（每个场景的 given/when/then 已写入 test_scenarios.py docstring）
"""

    # 异常值覆盖（回答：是否拿到该系统的全部异常值）
    sot_err_total = sum(len(a.get("response", {}).get("errors", [])) for a in apis)
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
    parser.add_argument("--code", default="backend/src/main/java",
                        help="代码根目录（规则测试在此做离线静态断言；也可用环境变量 "
                             "SCT_CODE_ROOT 在运行时覆盖生成的默认值）")
    parser.add_argument("--java-test-root", default="src/test/java",
                        help="Java 测试根目录（有 target+test_cases 锚点的规则在此生成 "
                             "JUnit + Mockito 测试类）")
    parser.add_argument("--junit", default="auto", choices=["auto", "4", "5"],
                        help="JUnit 版本：auto(默认，按 detect_junit_version 自动识别；"
                             "优先 5；项目存量为 4 则跟 4；不可混用)、4、5")
    args = parser.parse_args()

    spec_path = Path(args.spec)
    out_dir = Path(args.out)
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
        has_tests = any(out_dir.glob("test_*.py"))
        if (prev_meta.get("sot_hash") == sot_hash
                and prev_meta.get("codegraph_hash") == cg_hash and has_tests):
            print("⚡ hash 缓存命中：SoT 与 CodeGraph 均未变化，跳过再生成（0 个文件）。")
            print("   如需强制再生成：--force")
            return

    codegraph = load_codegraph(args.codegraph)
    graph_index = build_graph_index(codegraph)
    base_url = graph_base_url(codegraph)
    global_exceptions = (codegraph or {}).get("global_exceptions") or []
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

    print("Generating API tests...")
    api_files, field_drifts, api_annotations = gen_api_tests(apis, out_dir, graph_index,
                                                             base_url, global_exceptions)
    for f in api_files:
        print(f"  + {f}")

    # --only 定向生成：合并上次 meta 的标注/漂移——meta 是 sct.check 报告的数据源，
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

    # 机器可读产物：sct.check 自动发现后整合进最终测试报告
    # （头部 CodeGraph 标注 / 3.2 实现列 / 6.2 FIELD_DRIFT 节 / 系统级异常）
    codegen_meta = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "codegraph": args.codegraph or "",
        "api_annotations": api_annotations,
        "field_drifts": field_drifts,
        "derived_error_cases_total": derived_total,
        "global_exceptions": global_exceptions,
    }
    # hash 缓存只在全量生成时推进（--only 定向生成不代表全量状态，不写 hash，
    # 下次全量运行会自然再生成，保证缓存语义正确）
    if not args.only:
        codegen_meta["sot_hash"] = sot_hash
        codegen_meta["codegraph_hash"] = cg_hash
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps(codegen_meta, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    print(f"  + {meta_path}")

    print("Generating rule tests...")
    junit_version = args.junit
    if junit_version == "auto":
        junit_version = detect_junit_version(args.java_test_root)
        print(f"JUnit version auto-detected: {junit_version}")
    else:
        print(f"JUnit version (explicit): {junit_version}")
    rule_files = gen_rule_tests(rules, out_dir, args.code, args.java_test_root, junit_version)
    for f in rule_files:
        print(f"  + {f}")

    print("Generating scenario tests...")
    scenario_files = gen_scenario_tests(features, out_dir)
    for f in scenario_files:
        print(f"  + {f}")

    print("Generating coverage report...")
    report = gen_coverage_report(acceptance, out_dir, field_drifts, args.codegraph or "",
                                 global_exceptions, api_annotations)
    print(f"  + {report}")

    print(f"\nDone. Generated {len(api_files) + len(rule_files) + len(scenario_files)} test files.")
    print(f"API coverage: {len(api_files)}/{len(apis)}")
    print(f"Rule coverage: {len(rules)}/{len(rules)}")
    print("Next: implement code to pass these tests.")


if __name__ == "__main__":
    main()
