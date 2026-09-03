"""SCT canonical ID 层（v1.1.3，P0-4 修复）

所有脚本必须通过本模块做 ID 换算，禁止再散落 `split("-")`。

ID 形态约定：
  - SoT canonical id :  API-F003-001 / BR-F003-001 / MQ-001 / F003-1
  - 末段 suffix      :  001（生成文件/函数命名依据）
  - safe_slug        :  api_f003_001（junit/报告/缓存中需要全量唯一时使用）

铁律：同一 feature 下可有多个同前缀 ID（API-F003-001 ~ API-F003-006），
末段才是唯一区分段；任何用 `split("-")[1]` 取中段的写法都是 bug（F-2/F-5 教训）。
"""


def id_suffix(canonical_id: str) -> str:
    """canonical id → 末段小写后缀：'API-F003-001' → '001'；'MQ-001' → '001'"""
    return (canonical_id or "").split("-")[-1].lower()


def safe_slug(canonical_id: str) -> str:
    """canonical id → 全量唯一 slug：'API-F003-001' → 'api_f003_001'"""
    return (canonical_id or "").lower().replace("-", "_")


def api_test_filename(canonical_id: str) -> str:
    """'API-F003-001' → 'test_api_001.py'"""
    return f"test_api_{id_suffix(canonical_id)}.py"


def rule_test_func(canonical_id: str) -> str:
    """'BR-F003-001' → 'test_br_001'"""
    return f"test_br_{id_suffix(canonical_id)}"


def scenario_test_func(scenario_id: str) -> str:
    """'F003-1' → 'test_sc_f003_1'"""
    return "test_sc_" + (scenario_id or "").lower().replace("-", "_")
