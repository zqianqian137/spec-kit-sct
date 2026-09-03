# 单元测试编写规范（团队模板）

> **使用说明**：这是 SCT 项目里的占位模板，用于承载**您所在团队/银行**的单测编写规范。
> 把下面每个 `[填入…]` 占位符替换为你们行的硬性要求即可。
> 拷过去之后，建议与 CI 门禁（`testing.run` 的覆盖率/漂移门禁）和 Sonar/SpotBugs 等工具对齐——规则要能被机器校验，否则是纸面规范。

---

## 1. 框架与版本（强制）

| 项 | 要求 | 示例 |
|---|---|---|
| 测试框架 | `[JUnit5 / JUnit4]` | JUnit5：`org.junit.jupiter.api.Test` |
| 断言库 | `[AssertJ / JUnit 内置 / Hamcrest]` | AssertJ：`org.assertj.core.api.Assertions.assertThat` |
| Mock 框架 | `[Mockito 5.x]`（JDK 11+）/ `[Mockito 4.x]`（JDK 8） | `@ExtendWith(MockitoExtension.class)` |
| Spring 测试 | `[禁用 / 仅允许集成测试]` | 单元测试**禁止** `@SpringBootTest` |
| Java 版本 | `[JDK 8 / JDK 17 / JDK 21]` | 与生产一致；JDK 8 项目用 Mockito **4.x** |
| 编码 | **UTF-8**（硬性） | Maven `<project.build.sourceEncoding>UTF-8</project.build.sourceEncoding>` |

> 注：SCT `acceptance-codegen.py` 的 `--junit auto` 会跟随项目已有版本生成 4/5，二者**不混用**。
>
> ✅ **JDK 8 兼容性（v1.0.5 起已修复）**：codegen 不再生成 `var`（Java 10+ 语法），
> Act 段统一用 `Object actual = service.x(...)`；集合输入用
> `java.util.Arrays.asList(...)` / `java.util.Collections.emptyList()` / `emptyMap()`，
> 规避 Java 9+ 的 `List.of` / `Map.of`；集合形参（`List<...>` 等）会自动补
> `import java.util.*`。**JDK 8 项目生成的测试可直接编译**（`javac --release 8` 验证通过）。
> 若新项目确需 JDK 21 新特性（`var`、`List.of`），在生成后按需改写并在 review 中注明即可。

## 2. 命名规范

| 对象 | 规范 | 示例 |
|---|---|---|
| 测试方法 | `[格式：methodName_ShouldXxx_WhenYyy]` | `calculateDiscount_ShouldReturn85_WhenVip3` |
| `@DisplayName`（JUnit5 强制） | `[中文 / 英文 / 中英混排]` | `@DisplayName("BR-001: VIP3 100 元商品应返回 85 元")` |
| 命名空间 | 测试类 = 被测类 + `Test`，与被测类同包 | `OrderService` → `OrderServiceTest`，同包 `com.x.order` |
| 测试数据文件 | `[位置/命名/版本管理方式]` | `src/test/resources/fixtures/order/v3/...` |

## 3. 结构（AAA 硬性要求）

每个测试方法**只能**包含三段，且按以下顺序：

```java
@Test
@DisplayName("...")               // 意图注解
void methodName_ShouldX_WhenY() {
    // 1. Arrange — 输入与 Mock 桩
    OrderRequest input = new OrderRequest(...);   // JDK 8 无 var，一律显式类型
    when(collaborator.findById(1L)).thenReturn(...);

    // 2. Act — 调用被测方法
    Object actual = service.process(input);       // 与 codegen 输出一致（Object 兜底）

    // 3. Assert — 断言
    assertThat(actual).isEqualTo(expected);
}
```

> **JDK 8 禁止 `var`**（Java 10+ 语法），一律显式声明类型；SCT 生成的 Act 段使用
> `Object actual` 保证任意返回类型可编译。

**禁止**："一行流"（Arrange/Act/Assert 全挤在一行）、重复 Act-Assert 模式、Setup 测试方法里放业务断言。

## 4. 断言规范

- **禁用**：`assertTrue(x)` / `assertNull(x)` / `assertNotNull(x)` 这类零信息断言——必须用 AssertJ 的 `assertThat` 写明期望语义
- **断言失败信息**：每个 `assertThat` 都带 `.as("BR-xxx: ...")` 描述失败的 SoT 来源
- **浮点比较**：用 `closeTo(expected, within(0.001))`，禁用 `==`
- **集合**：用 `containsExactly` 而非顺序敏感的 `contains`
- **异常**：用 `assertThatThrownBy(...)` 或 JUnit5 `assertThrows`，禁用 try-catch + fail
- **不反推断言**：断言期望值必须来自 SoT 的 `test_cases.expect`，**禁止**为通过改测试迎合代码

## 5. Mock 规范

| 场景 | 规范 |
|---|---|
| 协作者数量 | 同一测试方法 `@Mock` 不超过 `[N]` 个；超量提示拆分测试或重构被测类 |
| Mock 桩 | 必须**显式桩**——SCT 通过 SoT 的 `given` 字段生成 `when(...).thenReturn(...)`；没有 `given` 的 Mock 默认返回 0/null，**禁止**依赖这种"意外正确" |
| 静态方法 / final | `[禁用 / 允许 + MockStatic]`，SCT 不自动覆盖 |
| 私有方法 | **禁止**通过反射测试；私有逻辑应通过公开方法覆盖 |
| 真实数据库 / HTTP / 文件 | **禁止**在单测里出现——放集成层（`@SpringBootTest` 或 Testcontainers） |
| 时间相关 | 用 Clock 注入，`LocalDate.now()` 之类**禁用** |

## 6. 必须覆盖的边界

每个 `test_cases` 至少覆盖以下几类（不全会报 BINDING_DRIFT 或缺覆盖）：

- [ ] 正常路径（happy path）
- [ ] 边界值（最小/最大/刚好越界）
- [ ] 异常路径（应抛 `XxxException`）
- [ ] 空集合 / null 入参（视业务而定）
- [ ] [其他：权限/并发/幂等等]

## 7. 覆盖率门槛（与 `testing.run` 对齐）

| 指标 | 阈值 | 数据来源 |
|---|---|---|
| 增量行覆盖率 | ≥ `[90%]` | JaCoCo XML（`--jacoco`） |
| 增量分支覆盖率 | ≥ `[60%]` | JaCoCo XML |
| SoT 范围覆盖率 | 100%（SoT 登记的每条 API/rule 必须有对应测试） | `consistency-check.py` |
| HIGH 漂移数 | 0 | `consistency-check.py` |

## 8. 编写禁单（明确禁止的写法）

- ❌ `Thread.sleep(...)` / `awaitility` 用固定等待
- ❌ 依赖测试方法执行顺序（`@Order` 不写生产断言）
- ❌ 共享可变静态状态（`@BeforeAll` 里初始化 `@Autowired` 之类）
- ❌ 单测里启动 Spring / Tomcat / 数据库
- ❌ 直接 new 出被测类所有依赖（即绕过 Mock 用真实协作者）
- ❌ 注释掉的测试代码（删掉，需要时从 git 历史找回）
- ❌ 在生成测试里手改以求通过——改 SoT，重生成

## 9. 与 SCT 的衔接（重要）

- 每条单测**必须能追溯到 SoT 一条规则**：`test_cases.name` 暗示的 rule id 在 `@DisplayName` 开头出现（如 `"BR-001: ..."`）
- SoT `test_cases.inputs` 决定 Arrange 输入值；SoT `test_cases.expect` 决定 Assert；`given` 决定桩
- **新规则**：先在 SoT 写好 `target` + `test_cases` + `given` + `checks`，再跑 `testing.cases`，**不**允许跳过 SoT 直接手写测试
- 已有测试改业务逻辑时：先改 SoT → `testing.cases` → 对比 diff → 调整（**不是**手改生成的测试）

## 10. CI / Gate

- 本地不通过的单测**禁止**提交（`mvn test` / `gradle test` 必须绿）
- 提交触发 `[Jenkins / GitLab CI / 其他]` 的 `[阶段名]` 阶段跑 `testing.run`，未达门禁阻塞 merge
- 覆盖率降级不允许（[实施日期 X] 起硬门禁）

---

## 模板填好后如何生效

1. 把这份文档 commit 到 `spec-kit-sct/docs/unit-test-standards.md`（或您银行的内部仓库）
2. 在项目 README / 新人指引里指向它
3. 把第 7 节阈值写进 `testing.run` 的门禁校验（或 CI 脚本里另加一层）
4. 在培训里以"先写 SoT、再生成测试"为示范流程

---

*模板由 SCT 团队维护，填入团队具体要求后作为内部规范生效。*