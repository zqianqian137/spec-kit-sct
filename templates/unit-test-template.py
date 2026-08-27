# =====================================================================
# 单元测试代码模板约定（SCT 阶段 2：speckit.sct.codegen）
# ---------------------------------------------------------------------
# 本文件是所有 SCT 单元测试（自动生成 + 手写）的唯一编码约定。
# consistency-check.py 按「真相意图说明」解析测试与 SoT 的映射，
# 缺失意图说明的测试会被判定为 MISSING_TEST 漂移。
#
# ============================= 硬性约定 =============================
# 1. 文件头：声明 AUTO-GENERATED（禁止手改）或 HAND-WRITTEN，并给出 SoT 锚点
# 2. 命名：
#      API 用例    test_api_{序号}_success / test_api_{序号}_error_{n}
#      规则用例    test_br_{序号}
#      场景用例    test_sc_{feature_id}_{序号}（如 test_sc_f001_1）
# 3. 每个测试案例必须包含「真相意图说明」docstring，四要素缺一不可：
#      [意图]     一句话说明本案例验证什么（来自 SoT 的场景/规则原文）
#      真相来源   acceptance.yaml 锚点（apis[] / rules[] / scenarios[]）
#      Given      前置状态（可验证的客观条件，非操作步骤）
#      When       触发动作（单一动作；多个动作应拆分为多个案例）
#      Then       可观测的预期结果（断言目标）
# 4. 测试体按 Given → When → Then 三段注释组织，断言只能出现在 Then 段
# 5. write-once：生成后禁止手改；需求变更必须改 SoT 再重新生成
# 6. 断言锚点（测试独立性）：Then 的期望值唯一来源是 SoT——禁止从实现代码
#    反推期望（读了代码写"实际返回什么就断言什么"= 自己出题自己改卷，
#    code 的错误会被测试合法化）。CodeGraph/代码只允许辅助**构造** Given/When
#    （字段类型、格式、示例值），永不进入 Then。测试失败时举证责任在 code 侧：
#    默认 SoT 是真相，除非有证据证明 spec 本身错了才改 SoT（连带改 spec 再重生成）。
# =====================================================================

"""
AUTO-GENERATED FROM acceptance.yaml - DO NOT EDIT
Source: specs/001-batch-import/acceptance.yaml
Generated: 2026-01-01T00:00:00
Scope: API-001 创建批量导入任务 / BR-001 单次导入上限
"""

import pytest
import requests

BASE_URL = "http://localhost:8080"
API_PATH = "/api/batch-tasks"


# ---------------------------------------------------------------------
# API 用例（正常路径）
# 命名：test_api_{序号}_success
# ---------------------------------------------------------------------
def test_api_001_success():
    """[意图] 验证创建批量导入任务接口的正常路径（对应场景 F001-1）

    真相来源: acceptance.yaml#apis[API-001].response.success

    Given: 服务可用，且请求体包含全部必填字段（fileName、content）
    When:  POST /api/batch-tasks 提交合法请求体
    Then:  返回 200，响应体包含非空 taskId
    """
    # Given：构造合法请求体（字段来自 SoT request.body 定义）
    payload = {"fileName": "tasks.csv", "content": "Base64..."}

    # When：触发单一动作
    response = requests.post(BASE_URL + API_PATH, json=payload)

    # Then：断言预期结果（只在本段断言）
    assert response.status_code == 200, \
        f"Expected 200, got {response.status_code}"
    data = response.json()
    assert data.get("taskId"), f"taskId missing: {data}"


# ---------------------------------------------------------------------
# API 用例（异常路径）
# 命名：test_api_{序号}_error_{n}（n 对应 SoT response.errors 下标，从 1 起）
# ---------------------------------------------------------------------
def test_api_001_error_1():
    """[意图] 验证必填字段缺失时接口拒绝请求并返回 400

    真相来源: acceptance.yaml#apis[API-001].response.errors[1]

    Given: 服务可用，但请求体缺失必填字段 fileName
    When:  POST /api/batch-tasks 提交非法请求体
    Then:  返回 400，且 message 包含 "fileName is required"
    """
    # Given：构造缺失必填字段的请求体
    payload = {"content": "Base64..."}

    # When：触发单一动作
    response = requests.post(BASE_URL + API_PATH, json=payload)

    # Then：断言错误码与错误信息
    assert response.status_code == 400, \
        f"Expected 400, got {response.status_code}"
    data = response.json()
    assert "fileName is required" in data.get("message", ""), \
        f"Message not matched: {data}"


# ---------------------------------------------------------------------
# 业务规则用例
# 命名：test_br_{序号}；规则断言由实现者按 SoT 规则补全
# ---------------------------------------------------------------------
def test_br_001():
    """[意图] 单次导入不超过 1000 条用例

    真相来源: acceptance.yaml#rules[BR-001]（derived_from: spec.md#数据约束）

    Given: 已创建批量任务，且上传 CSV 恰好包含 1000 条合法用例
    When:  服务端执行导入校验
    Then:  校验通过，任务进入 PENDING 状态（不触发超限拒绝）
    """
    # Given：按规则构造边界数据（1000 条，处于上限）
    rows = make_rows(1000)
    task = create_batch_task(rows)

    # When：触发规则校验
    result = task.validate()

    # Then：断言规则预期（实现者按 BR-001 补全）
    assert result.ok, "TODO: implement assertion based on BR-001"
    assert not result.rejected


# ---------------------------------------------------------------------
# 场景用例（可选：当 SoT 场景无法由单一 API/规则表达时生成）
# 命名：test_sc_{feature_id小写}_{序号}
# ---------------------------------------------------------------------
def test_sc_f001_2():
    """[意图] 重复上传同名文件应返回 409 冲突

    真相来源: acceptance.yaml#features[F001].acceptance_scenarios[F001-2]

    Given: 已登录用户，且已存在同名批量任务
    When:  再次上传相同文件名的 CSV
    Then:  返回 409，且不产生新的批量任务
    """
    # Given：先创建同名任务
    create_batch_task(file_name="tasks.csv")

    # When：再次上传同名文件
    response = requests.post(BASE_URL + API_PATH,
                             json={"fileName": "tasks.csv", "content": "..."})

    # Then：断言冲突且任务数不变
    assert response.status_code == 409
    assert count_batch_tasks() == 1
