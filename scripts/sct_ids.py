"""SCT canonical ID 层（v1.1.3，P0-4 修复）

所有脚本必须通过本模块做 ID 换算，禁止再散落 `split("-")`。

ID 形态约定：
  - SoT canonical id :  API-F003-001 / BR-F003-001 / MQ-001 / F003-1
  - 末段 suffix      :  001（生成文件/函数命名依据）
  - safe_slug        :  api_f003_001（junit/报告/缓存中需要全量唯一时使用）

铁律：同一 feature 下可有多个同前缀 ID（API-F003-001 ~ API-F003-006），
末段才是唯一区分段；任何用 `split("-")[1]` 取中段的写法都是 bug（F-2/F-5 教训）。

v2.5.1 起本模块同时是**命名约定与三态语义的单一事实源**：
  - 生成侧（codegen）与校验侧（consistency-check）的文件名/函数名/类名约定
    一律引用这里的函数与 pattern——新增 emitter 或新语言时，改约定只改这一处；
  - 三态（PASS/UNPROVEN/BLOCK）的严重度排序统一用 VERDICT_RANK，
    门禁取最严、整体取最严都以此为准。
"""
import re

# ---- 命名约定（生成侧与校验侧共用；改动即约定变更，须同步 self-test 断言）----

# 生成的 API 接口测试文件名：test_api_{suffix}.py（suffix 来自 id 末段）
API_TEST_FILE_PAT = re.compile(r"test_api_([\w]+)\.py$")
# 生成的规则测试函数名前缀：test_br_{suffix}
RULE_FUNC_PREFIX = "test_br_"
RULE_FUNC_PAT = re.compile(r"br_([\w]+)")
# 生成的场景测试函数名：test_sc_f{feat}_{seq}
SCENARIO_FUNC_PAT = re.compile(r"test_sc_f(\d+)_(\d+)")
# 无锚点规则的静态断言兜底文件
RULES_FALLBACK_FILENAME = "test_rules.py"
# Python emitter 的单测文件
PYTEST_UNIT_FILENAME = "test_unit_py.py"


def id_suffix(canonical_id: str) -> str:
    """canonical id → 末段小写后缀：'API-F003-001' → '001'；'MQ-001' → '001'"""
    return (canonical_id or "").split("-")[-1].lower()


def safe_slug(canonical_id: str) -> str:
    """canonical id → 全量唯一 slug：'API-F003-001' → 'api_f003_001'"""
    return (canonical_id or "").lower().replace("-", "_")


def api_test_filename(canonical_id: str) -> str:
    """'API-F003-001' → 'test_api_001.py'"""
    return f"test_api_{id_suffix(canonical_id)}.py"


def api_test_func_prefix(canonical_id: str) -> str:
    """'API-F003-001' → 'test_api_001'（junit 用例名与文件名共用的前缀）"""
    return f"test_api_{id_suffix(canonical_id)}"


def java_test_class_name(target_class: str) -> str:
    """'com.demo.UpController' → 'UpControllerTest'（空输入返回空串）"""
    simple = (target_class or "").split(".")[-1]
    return f"{simple}Test" if simple else ""


def rule_test_func(canonical_id: str) -> str:
    """'BR-F003-001' → 'test_br_001'"""
    return f"test_br_{id_suffix(canonical_id)}"


def scenario_test_func(scenario_id: str) -> str:
    """'F003-1' → 'test_sc_f003_1'"""
    return "test_sc_" + (scenario_id or "").lower().replace("-", "_")


# ---- 三态语义（单一事实源）：整体/整体取最严 = rank 最大者；NOT_APPLICABLE 不参与 ----
VERDICT_RANK = {"PASS": 1, "UNPROVEN": 2, "BLOCK": 3, "NOT_APPLICABLE": 0}
