# 示例：`NoSuchMethodError`——依赖版本冲突

考察点：**`NoSuchMethodError` 与 `ClassNotFoundException` 的区别**、**日志没给版本时不得写出具体版本号**、
**启动期 Bean 包装异常怎么剥**。

| 项目 | 路径 |
| --- | --- |
| 输入日志 | [`logs/dependency-conflict.log`](logs/dependency-conflict.log)（12 行） |
| 脚本输出 | [`parsed/dependency-conflict.json`](parsed/dependency-conflict.json)（脚本直接生成） |
| 最终报告 | [`reports/dependency-conflict.report.md`](reports/dependency-conflict.report.md) |

复现：

```bash
python3 scripts/parse_java_log.py --file examples/logs/dependency-conflict.log --app-package com.acme --pretty
```

## 1. 场景

订单服务 v2.7.2 升级后启动失败。表面错误是"`orderFacade` Bean 创建失败"，实际情况与 Bean 配置无关。

## 2. 脚本抽取结果（节选）

```json
{
  "summary": {
    "chain_count": 1, "chain_length": 3,
    "root_cause_type": "java.lang.NoSuchMethodError",
    "root_cause_message": "'void com.google.common.base.Preconditions.checkArgument(boolean, java.lang.String, java.lang.Object)'",
    "root_cause_log_line": 10,
    "primary_signals": ["version_conflict", "spring_context"]
  },
  "first_business_frame": { "method": "orderFacade", "file": "FacadeConfig.java", "line": 41, "log_line": 9 },
  "root_business_frame": { "class": "com.acme.order.facade.OrderFacade", "method": "<init>", "file": "OrderFacade.java", "line": 34, "log_line": 11 }
}
```

三层链：

| 层 | 异常 | 行 | 含义 |
| --- | --- | --- | --- |
| 0 | `BeanCreationException` | L4 | 哪个 Bean 创建失败（`orderFacade`） |
| 1 | `BeanInstantiationException: Constructor threw exception` | L7 | 失败方式：构造器抛异常 |
| 2 | `NoSuchMethodError: '... checkArgument(boolean, String, Object)'` | L10 | **根因**：运行期没有这个方法 |

## 3. 为什么这条消息本身就是证据

`NoSuchMethodError` 的消息格式是 **`返回类型 全限定类名.方法名(参数类型)`**，这是编译期写入字节码的符号引用。
运行期加载到同名类但没有这个签名，JVM 就抛这个错误。由此可以推出两件事：

1. **类存在**——否则会是 `NoClassDefFoundError` / `ClassNotFoundException`。所以"依赖没打进包"这个方向可以排除。
2. **版本不一致**——同一 artifact 的不同版本方法集合不同。这是版本冲突的典型指纹。

但**日志没有给出任何版本号**（`Starting ... v2.7.2` 是应用版本，不是 guava 版本）。因此：

- 可以写"运行期 guava 缺少该重载"（事实，来自 L10）；
- 不能写"升级到 guava 32.1.3 即可"（编造，日志中不存在该版本信息）；
- 正确写法是给出 `unzip -l <app.jar> | grep -i guava` 这类命令，让版本由使用者确认后回填。

## 4. Step 3.1：命中的知识

- `version_conflict` → `references/java-exceptions.md#dependency-conflict`
- `spring_context` → 用于确认外层两层是包装异常（`#startup` 的"怎么读 BeanCreationException 链"）
- 命令取自 `references/safe-commands.md` 第 6 节（依赖与制品）

## 5. Step 3.2：分析中间产物

按 `prompts/extract_root_cause.md` 执行。`NoSuchMethodError` 的关键不是"报错了"，而是
**类加载成功、方法签名不匹配**——这两件事指向完全不同的修法。

```
### 1. 链定位
chain_index: 0 / chain_length: 3
root_cause: java.lang.NoSuchMethodError — 'void com.google.common.base.Preconditions.checkArgument(boolean, java.lang.String, java.lang.Object)' [L10] [事实·脚本]
discarded_chains: 无（日志只有一条链）

### 2. 代码位置
业务包: com.acme
报错点: com.acme.order.config.FacadeConfig.orderFacade(FacadeConfig.java:41) [L9] [事实·脚本]
故障点: com.acme.order.facade.OrderFacade.<init>(OrderFacade.java:34) [L11] [事实·脚本]
说明: @Bean 方法创建 Facade 时，构造器调用了运行期不存在的 guava 三参重载

### 3. 语义归类
class: dependency-conflict
knowledge_section: references/java-exceptions.md#dependency-conflict
signals_used: version_conflict (primary), spring_context (primary) | noise: 无

### 4. 证据表（只放原文，不放结论）
E1 | L10 | > Caused by: java.lang.NoSuchMethodError: 'void com.google.common.base.Preconditions.checkArgument(boolean, java.lang.String, java.lang.Object)'
E2 | L11 | > 	at com.acme.order.facade.OrderFacade.<init>(OrderFacade.java:34)
E3 | L9  | > 	at com.acme.order.config.FacadeConfig.orderFacade(FacadeConfig.java:41)
E4 | L1  | > 2026-11-01 10:22:41.003  INFO 1 --- [main] c.acme.order.OrderApplication        : Starting OrderApplication v2.7.2 using Java 17.0.9 with PID 1
E5 | L2  | > 2026-11-01 10:22:41.881  INFO 1 --- [main] c.a.o.c.FeatureFlags                 : 功能开关加载完成，共 12 项

### 5. 假设
H1 | confidence=high | 运行期 guava 版本低于编译期，缺少该三参重载
- 引用: E1, E2, E4
- 推理链: E1 是 `NoSuchMethodError`（方法级），说明类已加载成功、仅方法签名对不上；
  E2 显示调用发生在业务构造器；E4 给出制品版本 v2.7.2 → 编译期与运行期依赖树不一致 [推测]
- counter_evidence: 无。若类根本不在制品里，异常会是 ClassNotFoundException / NoClassDefFoundError
- verify:
  1. `unzip -l <app.jar> | grep -i guava` — 期望观察：包内 guava 版本低于编译期
  2. `mvn dependency:tree -Dincludes=com.google.guava:guava` — 期望观察：出现多版本或 omitted
- basis: 知识库 #dependency-conflict 章节

H2 | confidence=medium | 中间件 SDK 自带 shaded guava 抢占同名类
- 引用: E1, E2
- 推理链: E1 的类名是原始包名 `com.google.common.base`，E2 的调用在业务构造器 → 可能是某个 SDK
  把 guava 一起打了进来，运行期先加载了旧版 [推测]。未闭环部分：无制品清单
- counter_evidence: 若为 shade 且做了 relocation，类名会带前缀，E1 显示的是原始包名，用 shade 解释需要额外条件
- verify:
  1. `unzip -l <app.jar> | grep -i "guava\|shaded"` — 期望观察：多个 jar 含同名包
- basis: 经验，需制品清单佐证

H3 | confidence=low | 编译产物与运行制品不一致（跑的不是这次构建的包）
- 引用: E4
- 推理链: E4 只能给出"当前运行的制品版本"，说明不了编译时用的依赖 [推测]。
  未闭环部分：无构建日志、无镜像 digest
- counter_evidence: 无回滚/多版本痕迹，缺乏支撑
- verify:
  1. `unzip -l <app.jar> | grep -i "order-service"` — 期望观察：业务 jar 版本与预期构建一致
- basis: 模式匹配，优先级最低

### 6. 已排除
- 依赖未打包 / 类缺失：E1 是 `NoSuchMethodError`，类已加载成功，不是 "没打进包" — 依据: E1
- 配置错误：E5 显示功能开关已加载完成，失败点是构造器执行而非属性注入 — 依据: E5
- Bean 循环依赖：无 BeanCurrentlyInCreationException，链路是构造器抛错而非依赖解析 — 依据: E3

### 7. 信息缺口
- 日志未提供 guava 版本，无法给出"应该用哪个版本"，只能给定位命令
- 无 pom / 制品清单 / 构建日志，H2、H3 无法闭环
- 无 Spring Boot 版本，无法判断是否有官方 dependencyManagement 可对齐

### 8. 自我审查
| # | 自查问题 | 结论 | 处置 |
| --- | --- | --- | --- |
| 1 | 每个 L 编号都在原文中存在且内容对应？ | 是 | — |
| 2 | E 表每段引用都与原文逐字一致？ | 是 | 由日志逐行复制 |
| 3 | 每个假设都引用了真实存在的 E 编号？ | 是 | H1→E1/E2/E4，H2→E1/E2，H3→E4 |
| 4 | 假设里的类名/方法名/配置项都在日志或脚本输出中出现过？ | 是 | guava 由包名 `com.google.common` 得出，未编造版本号 |
| 5 | 是否把包装异常当成了根因？ | 否 | BeanCreationException、BeanInstantiationException 只作链路节点 |
| 6 | 无业务帧时是否仍指出了具体代码行？ | 否 | 业务帧已识别 |
| 7 | 每条假设都有反证与可执行的验证步骤？ | 是 | — |
| 8 | 是否出现"可能/大概/建议重启"这类无证据表述？ | 否 | 未给"升级到某版本"这类无据建议 |
SELF_CHECK: PASS_WITH_GAPS
```

`PASS_WITH_GAPS`：结论可执行（定位命令明确），但日志没有版本号，**不写"升级到 32.x"这类具体版本**——
那是编造，宁可留成待确认项。

## 6. Step 4.1：最终报告

见 [`reports/dependency-conflict.report.md`](reports/dependency-conflict.report.md)。一句话结论：

> 运行期 guava 缺少编译期使用的 `checkArgument(boolean, String, Object)` 重载（L10），属版本不一致；
> 类本身存在，所以不是"没打进包"。具体版本需用 `unzip -l` / `dependency:tree` 确认后再定。

## 7. 这个例子演示了什么

1. **异常类型的精确含义**：`NoSuchMethodError` 只说"方法对不上"，不等于"类没有"，二者的排查路径完全不同。
2. **不编造版本号**：日志里没有的版本，一律写成"需确认"，并用命令给出确认方式。
3. **包装异常的剥离**：`BeanCreationException` 常让人直接去查 Bean 配置，真正的线索在最深一层。
4. **`<init>` 也是有效业务帧**：脚本把它识别为 `OrderFacade.<init>`（L11），构造器里的失败同样要定位到行。

## 8. 反面示范

| 错误输出 | 问题 |
| --- | --- |
| "guava 版本冲突，升级到 33.0.0-jre 即可" | 日志里没有任何版本号，33.0.0 是编造的 |
| "缺少 guava 依赖，请检查 pom" | 类已加载，说明依赖存在；诊断方向错误 |
| "`orderFacade` Bean 配置有误，检查 @Bean 方法" | 停在包装层，没有沿 Caused by 走到底 |
| "建议执行 `mvn dependency:tree` 后重启" | 缺具体过滤参数，且把只读排查与变更操作混在一起 |
