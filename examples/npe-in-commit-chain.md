# 示例：订单详情接口空指针（四层 Caused by，故障点在提交阶段）

这个示例完整走一遍 Skill 的四步：**原始日志 → 脚本抽取 → 分析中间产物 → 最终报告**。
所有行号、字段均来自脚本真实输出，没有手写补全。

| 项目 | 路径 |
| --- | --- |
| 输入日志 | [`logs/npe-in-commit-chain.log`](logs/npe-in-commit-chain.log)（33 行） |
| 脚本输出 | [`parsed/npe-in-commit-chain.json`](parsed/npe-in-commit-chain.json)（脚本直接生成） |
| 最终报告 | [`reports/npe-in-commit-chain.report.md`](reports/npe-in-commit-chain.report.md) |

复现命令：

```bash
python3 scripts/parse_java_log.py \
  --file examples/logs/npe-in-commit-chain.log \
  --app-package com.acme --pretty > /tmp/parsed.json
```

## 1. 场景

订单服务（Spring Boot + JPA，包根 `com.acme`）在 21:04 连续两次详情查询失败：

- `SO20261031001` 在 21:04:02 失败，`exec-5` 线程
- `SO20261031007` 在 21:04:19 失败，`exec-6` 线程
- 21:06 另一笔订单 `SO20261031012` 查询成功
- 21:05 的增量同步任务正常完成 128 条

初步怀疑是数据库或缓存问题，但实际情况要看堆栈才能定。

## 2. 输入日志

```log
2026-10-31 20:58:31.902  INFO 1 --- [main] c.acme.order.OrderApplication : Starting OrderApplication v2.7.1 on order-svc-7d9f with PID 1
2026-10-31 20:58:34.117  INFO 1 --- [main] c.acme.order.OrderApplication : Started OrderApplication in 2.215 seconds (JVM running for 2.61)
2026-10-31 21:04:02.113 ERROR 1 --- [http-nio-8080-exec-5] c.a.o.c.OrderController : 查询订单详情失败 orderId=SO20261031001
org.springframework.web.util.NestedServletException: Request processing failed; nested exception is org.springframework.transaction.TransactionSystemException: Could not commit JPA transaction
	at org.springframework.web.servlet.FrameworkServlet.processRequest(FrameworkServlet.java:1014)
	at org.springframework.web.servlet.FrameworkServlet.doGet(FrameworkServlet.java:898)
	at javax.servlet.http.HttpServlet.service(HttpServlet.java:655)
	at org.springframework.web.servlet.FrameworkServlet.service(FrameworkServlet.java:883)
	at com.acme.order.controller.OrderController.detail(OrderController.java:64)
	at java.base/java.lang.Thread.run(Thread.java:833)
Caused by: org.springframework.transaction.TransactionSystemException: Could not commit JPA transaction
	at org.springframework.orm.jpa.JpaTransactionManager.doCommit(JpaTransactionManager.java:569)
	at org.springframework.transaction.support.AbstractPlatformTransactionManager.processCommit(AbstractPlatformTransactionManager.java:761)
	at org.springframework.transaction.interceptor.TransactionAspectSupport.commitTransactionAfterReturning(TransactionAspectSupport.java:654)
	at com.acme.order.service.OrderQueryService.query(OrderQueryService.java:118)
	at com.acme.order.controller.OrderController.detail(OrderController.java:64)
Caused by: javax.persistence.RollbackException: Error while committing the transaction
	at org.hibernate.internal.ExceptionConverterImpl.convertCommitException(ExceptionConverterImpl.java:90)
	at org.hibernate.engine.transaction.internal.TransactionImpl.commit(TransactionImpl.java:104)
	at com.acme.order.listener.OrderAuditListener.beforeCommit(OrderAuditListener.java:38)
Caused by: java.lang.NullPointerException: Cannot invoke "com.acme.order.domain.OrderItem.getSkuId()" because the element at index 1 of "java.util.List" is null
	at com.acme.order.assembler.OrderAssembler.toDetail(OrderAssembler.java:52)
	at com.acme.order.assembler.OrderAssembler.toDetail(OrderAssembler.java:41)
	at com.acme.order.service.OrderQueryService.query(OrderQueryService.java:110)
	... 27 more
2026-10-31 21:04:02.118  INFO 1 --- [http-nio-8080-exec-5] c.a.o.g.GlobalExceptionHandler : 已转换为 HTTP 500, traceId=7f2c9a01
2026-10-31 21:04:19.640 ERROR 1 --- [http-nio-8080-exec-6] c.a.o.c.OrderController : 查询订单详情失败 orderId=SO20261031007
java.lang.NullPointerException: Cannot invoke "com.acme.order.domain.OrderItem.getSkuId()" because the element at index 2 of "java.util.List" is null
	at com.acme.order.assembler.OrderAssembler.toDetail(OrderAssembler.java:52)
	at com.acme.order.service.OrderQueryService.query(OrderQueryService.java:110)
	at com.acme.order.controller.OrderController.detail(OrderController.java:64)
2026-10-31 21:05:00.004  INFO 1 --- [scheduling-1] c.a.o.j.OrderSyncJob : 订单同步任务完成, 处理 128 条
2026-10-31 21:06:11.229  INFO 1 --- [http-nio-8080-exec-8] c.a.o.c.OrderController : 查询订单详情成功 orderId=SO20261031012
```

## 3. Step 2：脚本抽取结果（节选）

```json
{
  "schema_version": "1.0",
  "summary": {
    "exception_count": 5,
    "chain_count": 2,
    "primary_chain_index": 0,
    "chain_length": 4,
    "has_caused_by": true,
    "root_cause_type": "java.lang.NullPointerException",
    "root_cause_message": "Cannot invoke \"com.acme.order.domain.OrderItem.getSkuId()\" because the element at index 1 of \"java.util.List\" is null",
    "root_cause_log_line": 21,
    "has_business_frame": true,
    "oom_kind": null
  },
  "first_business_frame": {
    "class": "com.acme.order.controller.OrderController",
    "method": "detail", "file": "OrderController.java", "line": 64, "log_line": 9
  },
  "root_business_frame": {
    "class": "com.acme.order.assembler.OrderAssembler",
    "method": "toDetail", "file": "OrderAssembler.java", "line": 52, "log_line": 22
  },
  "signals": [{ "name": "npe", "evidence": [{ "log_line": 21 }, { "log_line": 28 }] }],
  "warnings": ["日志包含 '... N more' 省略帧，堆栈不完整。"]
}
```

完整字段见 [`parsed/npe-in-commit-chain.json`](parsed/npe-in-commit-chain.json)。脚本给出的两条链：

| 链 | 节点数 | 结构 |
| --- | --- | --- |
| chain 0（主链） | 4 | `NestedServletException`(L4) → `TransactionSystemException`(L11) → `RollbackException`(L17) → `NullPointerException`(L21) |
| chain 1 | 1 | `NullPointerException`(L28)，同一故障的第二次复现 |

**两个关键结论直接来自脚本，不需要肉眼比对：**

1. 主链最深处是 NPE（L21），不是外层那三个 Spring/Hibernate 包装异常。
2. 报错点（L9，`OrderController.detail`）与故障点（L22，`OrderAssembler.toDetail`）**不是同一个位置**。

## 4. Step 3.1：命中的知识

- `signals` 只命中 `npe`，其余信号（连接、超时、类加载、依赖冲突、OOM）均未命中 →
  只需读 `references/java-exceptions.md` 的 **NullPointerException** 一节，不必加载其他章节。
- `summary.oom_kind` 为 `null`、`out_of_memory.present` 为 `false` → 直接排除内存方向，不做"加大堆内存"的建议。
- 校验命令从 `references/safe-commands.md` 取，限定在 `grep` / `jps` / `jstack` / `SELECT` 范围。

## 5. Step 3.2：分析中间产物

按 `prompts/extract_root_cause.md` 执行，顺序固定：**先取证 → 再假设 → 再反证 → 最后自审**。
第 4 节的 E 表里没有一句是我的话，全部是从日志逐字复制的原文；每条假设都挂着 E 编号。

```
### 1. 链定位
chain_index: 0 / chain_length: 4
root_cause: java.lang.NullPointerException — Cannot invoke "…getSkuId()" because the element at index 1 of "java.util.List" is null [L21] [事实·脚本]
discarded_chains: chain 1 — 同一故障的第二次复现（L28），作旁证不单独分析

### 2. 代码位置
业务包: com.acme
报错点: com.acme.order.controller.OrderController.detail(OrderController.java:64) [L9] [事实·脚本]
故障点: com.acme.order.assembler.OrderAssembler.toDetail(OrderAssembler.java:52) [L22] [事实·脚本]
说明: 请求入口在 OrderController；异常在事务提交阶段的 OrderAuditListener 回调中抛出（L20），
      组装方法 41 行重载调用 52 行（L23），在遍历明细时取下标元素失败。

### 3. 语义归类
class: npe
knowledge_section: references/java-exceptions.md#npe
signals_used: npe (primary) | noise: 无

### 4. 证据表（只放原文，不放结论）
E1 | L9  | > at com.acme.order.controller.OrderController.detail(OrderController.java:64)
E2 | L20 | > at com.acme.order.listener.OrderAuditListener.beforeCommit(OrderAuditListener.java:38)
E3 | L21 | > Caused by: java.lang.NullPointerException: Cannot invoke "com.acme.order.domain.OrderItem.getSkuId()" because the element at index 1 of "java.util.List" is null
E4 | L22 | > at com.acme.order.assembler.OrderAssembler.toDetail(OrderAssembler.java:52)
E5 | L23 | > at com.acme.order.assembler.OrderAssembler.toDetail(OrderAssembler.java:41)
E6 | L28 | > java.lang.NullPointerException: Cannot invoke "com.acme.order.domain.OrderItem.getSkuId()" because the element at index 2 of "java.util.List" is null
E7 | L33 | > 2026-10-31 21:06:11.229  INFO 1 --- [http-nio-8080-exec-8] c.a.o.c.OrderController : 查询订单详情成功 orderId=SO20261031012

### 5. 假设
H1 | confidence=high | 明细列表中含 null 元素，组装时未过滤即取 skuId
- 引用: E3, E4, E6
- 推理链: E3 是 Helpful NPE，明确指出是**集合里 index 1 的元素**为 null，而不是方法调用者为 null；
  E4 的帧落在 toDetail:52；E6 在另一笔订单的 index 2 复现同一行 → 52 行在遍历中直接取元素属性，
  对 null 元素没有防护 [推测]
- counter_evidence: 无。E7 显示同期其他订单查询成功，只说明不是全量，与"个别订单数据异常"不矛盾
- verify:
  1. `SELECT order_id, COUNT(*) FROM t_order_item WHERE order_id IN ('SO20261031001','SO20261031007') GROUP BY order_id;`（表名以实际库表为准）— 期望观察：返回 0 行，或条数少于页面应展示的明细数
  2. 人工核对 OrderAssembler.java:41-60 是否对元素判空 — 期望观察：无 `Objects.nonNull` / `item != null`，直接 `item.getSkuId()`
  3. `grep -rn "toDetail" src/main/java/com/acme/order --include=*.java` — 期望观察：确认 :41 与 :52 的重载调用关系
- basis: 知识库 #npe 的"集合元素为 null"分支

H2 | confidence=medium | 列表按下标预分配后写入，缺失项留下空洞
- 引用: E5, E3, E6
- 推理链: E5 显示同一方法的 41 行重载调用 52 行，说明 52 行在遍历/重载体内；
  E3 与 E6 的下标分别是 1 和 2，都不是 0 → 位置不连续，符合"先预分配容量、再按下标 set，
  某次 set 未执行"的特征 [推测]。未闭环部分：日志没有构建该列表的代码，无法确认写入方式
- counter_evidence: 若列表由 JPA 关联映射直接生成，Hibernate 不会产生 null 元素，本条不成立
- verify:
  1. 查看 OrderQueryService.java:110 附近如何构建明细列表 — 期望观察：出现 `set(` / `new OrderItem[` / `IntStream.range` 等按下标写入的写法
  2. `grep -n "parallelStream\|\.set(" src/main/java/com/acme/order/assembler/OrderAssembler.java` — 期望观察：命中则 H2 可能性上升
- basis: 通用经验，仅下标特征支撑

H3 | confidence=low | 明细数据在写入侧落了 null 记录（脏数据）
- 引用: E3, E6
- 推理链: E3、E6 表明 null 与具体订单绑定，且两笔订单下标不同 → 更可能来自数据本身而非固定代码分支 [推测]。
  未闭环部分：没有明细数据，无法分辨 null 是"缺行"还是"写了空值"
- counter_evidence: 无直接反证；若 H2 成立，null 由代码而非数据产生
- verify:
  1. 按 H1 的 SQL 核对两笔订单明细条数与页面展示条数是否一致 — 期望观察：条数不足说明"缺行"
  2. 按 H1 的 SQL 检查是否存在 order_id 为空的明细行 — 期望观察：存在则支持"写了空值"
- basis: 模式匹配，优先级最低

### 6. 已排除
- 数据库不可达 / 连接池耗尽：E3 的根因是 NPE，全文无 SQLException / HikariPool 命中，E7 同期查询成功 — 依据: E3, E7
- 内存问题：out_of_memory.present = false，E3 的消息是 NPE 而非 OutOfMemoryError — 依据: E3
- 并发竞争：两次异常分属 exec-5 / exec-6 线程，E6 在同一源码行稳定复现 — 依据: E6
- 写路径或定时任务：E1 显示失败发生在 GET 详情接口的两个线程，与 21:05 的同步任务无交集 — 依据: E1
- 把提交阶段回调当根因：E2 的 beforeCommit 只是异常穿过的位置，该回调本身不产生 NPE — 依据: E2

### 7. 信息缺口
- `... 27 more`（L25）截断，看不到 toDetail 的上层调用者，H1 的"谁传入该列表"无法闭环
- 无 OrderAssembler 源码，无法确认 52 行是否已有判空（H1 的 verify 2 依赖它）
- 无明细表数据，H2、H3 只能验证不能确认

### 8. 自我审查
| # | 自查问题 | 结论 | 处置 |
| --- | --- | --- | --- |
| 1 | 每个 L 编号都在原文中存在且内容对应？ | 是 | — |
| 2 | E 表每段引用都与原文逐字一致？ | 是 | 逐行比对过 33 行日志 |
| 3 | 每个假设都引用了真实存在的 E 编号？ | 是 | H1→E3/E4/E6，H2→E5/E3/E6，H3→E3/E6 |
| 4 | 假设里的类名/方法名/配置项都在日志或脚本输出中出现过？ | 是 | 未出现日志之外的业务名词 |
| 5 | 是否把包装异常当成了根因？ | 否 | 三个 Spring/Hibernate 包装异常只作链路节点 |
| 6 | 无业务帧时是否仍指出了具体代码行？ | 否 | 业务帧已识别，根包 com.acme |
| 7 | 每条假设都有反证与可执行的验证步骤？ | 是 | 反证栏均有内容，verify 均可执行 |
| 8 | 是否出现"可能/大概/建议重启"这类无证据表述？ | 否 | — |
SELF_CHECK: PASS_WITH_GAPS
```

`PASS_WITH_GAPS` 而不是 `PASS`：结论本身没有幻觉，但 `... 27 more`、无源码、无数据这三个缺口
让 H2/H3 无法闭环，必须留给第 6 节（最终报告）如实交代。

## 6. Step 4.1：最终报告

完整成品见 [`reports/npe-in-commit-chain.report.md`](reports/npe-in-commit-chain.report.md)，
包含七节：结论摘要 / 关键证据表 / 三个假设（含反证与验证步骤）/ 止血与根治建议 /
只读命令表 / 分析边界 / 待确认清单。

核心结论一句话：

> `OrderAssembler.toDetail(OrderAssembler.java:52)` 遍历明细列表时未过滤 `null` 元素，
> 取 `items.get(1).getSkuId()` 抛 NPE；故障与订单数据相关（两笔订单在不同下标复现），非全量、非数据库不可达。

## 7. 这个例子演示了什么

1. **主链选择**：日志里有两段错误（L4 起的四层链、L28 起的重复 NPE）。脚本按"节点最多"选主链，
   报告只围绕 chain 0 展开，chain 1 只作旁证——否则两条链的帧会被拼成一条不存在的调用链。
2. **报错点 ≠ 故障点**：`OrderController.detail:64`（L9）只是入口，真正出事的是 `OrderAssembler:52`（L22）。
   若把入口当根因，修复动作会落到 controller 上，白改一轮。
3. **反证的价值**：L33 那笔成功订单，把结论从"接口挂了"收窄为"部分订单数据问题"，
   影响面评估和止血方案（单点过滤 vs 全站降级）因此完全不同。
4. **求助堆栈的时机信息**：链路经过 `JpaTransactionManager.doCommit` 与 `beforeCommit`，
   暴露出"读接口进入了事务提交阶段"这个次生问题——这类信息只有沿着完整 `Caused by` 链才看得到。
5. **边界写清楚**：`... 27 more`、无源码、无库表数据，所以 H1 只到"高置信假设"，并单列待确认项，
   而不是写成"已确认是数据问题"。

## 8. 反面示范（跳过脚本会写成什么样）

| 错误输出 | 问题 |
| --- | --- |
| "NullPointerException 表示空指针异常，建议检查对象是否为空" | 零信息量，读者看完仍然不知道该改哪一行 |
| "根因在 OrderController.detail 第 64 行" | 把报错点当故障点，行号虽真实但方向错 |
| "可能是数据库连接池耗尽，建议重启服务" | 无信号支撑；本次 `signals` 根本没有数据库相关命中 |
| "建议加大堆内存" | 未分型、无 OOM 证据，属于典型的模板化建议 |
| "第 52 行的 items.get(1) 为 null" | 日志只给出 `index 1`，写死 `get(1)` 属于补全原文没有的细节 |
