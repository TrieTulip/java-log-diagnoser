# 示例：订单查询获取数据库连接超时（connect timed out）

考察点：**连接类故障必须先分辨 refused / timeout / unknown host**、
**"获取连接失败"不等于慢 SQL**、
**同期成功请求是最有力的反证**、**报错点（入口）与故障点（依赖边界）要分开写**。

| 项目 | 路径 |
| --- | --- |
| 输入日志 | [`logs/db-connection-timeout.log`](logs/db-connection-timeout.log)（30 行） |
| 脚本输出 | [`parsed/db-connection-timeout.json`](parsed/db-connection-timeout.json)（脚本直接生成） |
| 最终报告 | [`reports/db-connection-timeout.report.md`](reports/db-connection-timeout.report.md) |

复现：

```bash
python3 scripts/parse_java_log.py --file examples/logs/db-connection-timeout.log --app-package com.acme --pretty
```

## 1. 场景

订单服务（Spring Boot，包根 `com.acme`）在 09:15:52 的一次订单详情查询中失败。
日志 30 行，含两段互不相关的错误：主链是订单查询的连接获取失败，
另一条是 5 分钟后日报任务的目录不可写。同期还有两笔成功的订单查询。

## 2. 脚本抽取结果（节选）

```json
{
  "summary": {
    "exception_count": 4,
    "chain_count": 2,
    "primary_chain_index": 0,
    "chain_length": 3,
    "root_cause_type": "java.net.SocketTimeoutException",
    "root_cause_message": "connect timed out",
    "root_cause_log_line": 20,
    "has_business_frame": true,
    "frame_count": 15,
    "primary_signals": ["timeout", "db_error"],
    "noise_signals": []
  },
  "first_business_frame": { "class": "com.acme.order.controller.OrderController", "method": "detail", "file": "OrderController.java", "line": 36, "log_line": 10 },
  "root_business_frame":  { "class": "com.acme.order.dao.OrderDao", "method": "selectByOrderNo", "file": "OrderDao.java", "line": 47, "log_line": 8 },
  "warnings": ["日志包含 '... N more' 省略帧，堆栈不完整。"]
}
```

**三个要点**

1. **主链选对了。** 两条链节点数分别是 3 和 1，脚本取节点最多的 chain 0。
   如果按"先出现的"或"最后出现的"选，就会拿日报任务的 `IllegalStateException` 当根因。
2. **报错点与故障点分离。** `first_business_frame` 是 `OrderController.java:36`（HTTP 入口），
   `root_business_frame` 是 `OrderDao.java:47`（发起数据库调用的那一行）。
   脚本取的是"最浅节点里最靠下的业务帧"作为入口——栈帧自上而下是被调用者到调用者，
   取帧顶会拿到 DAO 而把入口认错。
3. **`noise_signals` 为空不是缺功能。** 本例两条链的信号都被判给了主链无关的归属判定，
   `signals` 里每条都带 `in_primary_chain`；分析时只能用 `primary_signals`。

## 3. Step 3.1：命中的知识

`primary_signals = [timeout, db_error]` → 读 `references/java-exceptions.md`
的 [`#connectivity`](../references/java-exceptions.md#connectivity)（连接类故障：refused / timeout / unknown host）
与 [`#database`](../references/java-exceptions.md#database)（数据库与连接池）。

前者的第一条就是：先区分连接超时（网络/端口）与读超时（对端处理慢）。
本例最深层是 `connect timed out`，属**建连阶段**，排查方向是网络与数据库主机，
不是 SQL 优化。

## 4. Step 3.2：分析中间产物

### 1. 链定位
chain_index: 0 / chain_length: 3
root_cause: java.net.SocketTimeoutException — connect timed out [L20] [事实·脚本]
discarded_chains: chain 1: 日报任务 `IllegalStateException: 报表目录不可写`（L27-L30），独立线程、1 个节点，与本次接口故障无因果关系

### 2. 代码位置
业务包: com.acme
报错点: com.acme.order.controller.OrderController.detail(OrderController.java:36) [L10] [事实·脚本]
故障点: com.acme.order.dao.OrderDao.selectByOrderNo(OrderDao.java:47) [L8] [事实·脚本]
说明: 最深的 `Caused by`（`SocketTimeoutException`，L20）全是 JDK 帧，故障点落在依赖边界——业务代码只能定位到"发起数据库调用"的 `OrderDao.java:47`，再往下是网络层。报错点（HTTP 入口 `OrderController.java:36`）与故障点相距 3 层调用，改代码要改后者，复现入口要看前者。

### 3. 语义归类
class: connectivity
knowledge_section: #connectivity
signals_used: timeout, db_error | noise: 无

### 4. 证据表（只放原文，不放结论）
E1 | L4 | > 2026-11-01 09:15:52.318 ERROR 1 --- [http-nio-8080-exec-7] c.acme.order.OrderController     : 查询订单失败
E2 | L5 | > org.springframework.jdbc.CannotGetJdbcConnectionException: Failed to obtain JDBC Connection; nested exception is java.sql.SQLTransientConnectionException: HikariPool-1 - Connection is not available, request timed out after 30000ms
E3 | L8 | > at com.acme.order.dao.OrderDao.selectByOrderNo(OrderDao.java:47)
E4 | L10 | > at com.acme.order.controller.OrderController.detail(OrderController.java:36)
E5 | L14 | > Caused by: java.sql.SQLTransientConnectionException: HikariPool-1 - Connection is not available, request timed out after 30000ms
E6 | L20 | > Caused by: java.net.SocketTimeoutException: connect timed out
E7 | L24 | > 2026-11-01 09:15:52.401  INFO 1 --- [http-nio-8080-exec-7] c.acme.order.OrderController     : 返回兜底结果
E8 | L26 | > 2026-11-01 09:16:05.090  INFO 1 --- [http-nio-8080-exec-9] c.acme.order.OrderController     : 查询成功
E9 | L27 | > 2026-11-01 09:20:11.777 ERROR 1 --- [scheduling-1] c.acme.job.ReportJob                : 日报任务异常

### 5. 假设
H1 | confidence=medium | 数据库 TCP 建连超时，HikariCP 等待 30 秒仍拿不到可用连接
- 引用: E1, E2, E3, E4, E5, E6
- 推理链: E1 失败出现在 HTTP 工作线程 `http-nio-8080-exec-7` → E4 请求入口是 `OrderController.java:36` → E3 业务代码在 `OrderDao.java:47` 发起数据库查询 → E2 最外层是获取 JDBC 连接失败，说明故障发生在执行 SQL **之前** → E5 说明 `HikariPool-1` 等待 30000ms 仍无可用连接 → E6 最深层为 `java.net.SocketTimeoutException: connect timed out`，超时落在 TCP 建连阶段，而非"连接被占满后的排队等待"，因此指向数据库主机网络层不可达或对端丢弃建连请求。
- counter_evidence: E8（L26）13 秒后同一接口查询成功 → 不支持"数据库长时间不可达"，也不支持"连接池持续耗尽"，倾向瞬时网络抖动或对端短暂不可建连。
- verify:
  1. `nc -zv <DB_HOST> <DB_PORT>` — 期望观察：超时/无响应支持网络层不可达；返回 `refused` 则改判为端口未监听。
  2. `ss -lntp | grep <DB_PORT>` — 期望观察：数据库主机上应能看到监听进程；无输出说明 DB 未监听。
  3. 打开 `OrderDao.java:47` 与 `OrderQueryService.java:88` 人工核对是否为单表主键查询 — 期望观察：若是简单查询仍等待 30 秒，则不支持"慢 SQL 占满连接"。
- basis: references/java-exceptions.md #connectivity（refused / timeout / unknown host 三者排查方向不同）

H2 | confidence=low | 连接池容量不足，峰值时排队等待超时
- 引用: E5
- 推理链: E5 的 "request timed out after 30000ms" 也可能是池内连接被占满后的排队超时。**未闭环部分**：日志未提供 `maximumPoolSize`、活跃连接数与慢 SQL 信息，无法证明池内连接确实被占满。
- counter_evidence: E6（L20）底层是建连超时，池被占满时通常不会在 TCP 建连阶段失败；E8（L26）13 秒后即恢复，若是容量不足，峰值通常持续更久。
- verify:
  1. `jstack <PID> | head -200` — 期望观察：若大量线程停在 `HikariPool.getConnection`，说明池确实被争抢；若只有少量，倾向 H1。
  2. 确认连接池 `maximumPoolSize` 与 `connectionTimeout` 的实际取值 — 期望观察：与日志中的 30000ms 对照。
- basis: references/java-exceptions.md #database

### 6. 已排除
- 数据库端口未监听（`Connection refused`）：日志全文未出现 `Connection refused`，底层是 `connect timed out` — 依据: E6
- 慢 SQL 拖垮连接池：异常发生在获取连接阶段，未进入 SQL 执行 — 依据: E2
- 日报任务故障连带：属于 chain 1，线程（`scheduling-1`）与报错时间均不同 — 依据: E9
- 全站不可用：09:16:05 另一笔订单查询成功 — 依据: E8
- 接口无兜底、直接抛 500：L24 显示本次请求返回了兜底结果 — 依据: E7

### 7. 信息缺口
- 数据库主机地址与端口、应用与数据库之间是否有防火墙或网络策略 → H1 无法区分"网络抖动"与"策略拦截"
- 连接池 `maximumPoolSize` / `connectionTimeout` 实际配置 → H2 无法闭环
- 09:15:22–09:15:52 期间数据库侧是否有主从切换、CPU 打满或连接数告警 → 无法确定触发时点
- 日志含 `... 42 more`、`... 47 more`、`... 51 more` 共三处省略帧 → 无法确认中间是否插入自定义拦截器或数据源代理

### 8. 自我审查
| # | 自查问题 | 结论 | 处置 |
| --- | --- | --- | --- |
| 1 | 每个 L 编号都在原文中存在且内容对应？ | 是 | 逐条比对 log_line，L4/L5/L8/L10/L14/L20/L24/L26/L27 均已核对 |
| 2 | E 表每段引用都与原文逐字一致？ | 是 | 从原文复制，保留 `HikariPool-1` 与多行空格对齐 |
| 3 | 每个假设都引用了真实存在的 E 编号？ | 是 | H1→E2,E5,E6；H2→E5；已排除 4 条各带 E 编号 |
| 4 | 假设里的类名/方法名/配置项都在日志或脚本输出中出现过？ | 是 | `maximumPoolSize`、`connectionTimeout` 仅在"信息缺口"中以"需确认"形式出现，未作为事实使用 |
| 5 | 是否把包装异常当成了根因？ | 否 | `CannotGetJdbcConnectionException` 只作链路节点，根因取最深 `SocketTimeoutException` |
| 6 | 无业务帧时是否仍指出了具体代码行？ | 否 | 主链存在业务帧，未越界 |
| 7 | 每条假设都有反证与可执行的验证步骤？ | 是 | H1/H2 各含 counter_evidence 与 2–3 条 verify，全部只读 |
| 8 | 是否出现"可能/大概/建议重启"这类无证据表述？ | 否 | 全文无重启、kill、改配置类操作 |
SELF_CHECK: PASS_WITH_GAPS

## 5. Step 4.1：最终报告

见 [`reports/db-connection-timeout.report.md`](reports/db-connection-timeout.report.md)。
`SELF_CHECK` 为 `PASS_WITH_GAPS`，走完整七节模板，第 6 节照搬上面的信息缺口。

## 6. 这个例子演示了什么

1. **连接类故障的分诊顺序。** `refused`（对端没监听）、`timeout`（网络或对端不响应）、
   `unknown host`（DNS）三条路完全不同。本例是 `connect timed out`，
   第一步应该是 `nc -zv` 测端口，而不是去数据库里找慢 SQL。
2. **"获取连接失败"就已经排除了慢 SQL。** 异常发生在 `DataSourceUtils.getConnection`，
   SQL 还没执行——时间花在等连接上，不是花在查询上。
3. **同期成功请求是最有力的反证。** L26 显示 13 秒后同一接口成功，
   直接否掉"数据库长时间不可达""连接池持续耗尽""全站故障"三个方向，
   也把结论从"容量不足"推向"瞬时网络抖动"。
4. **报错点与故障点要分开写。** 入口是 `OrderController.java:36`，
   真正触碰依赖的是 `OrderDao.java:47`。写混了会导致排查从错误的位置开始。
5. **低置信度假设的用法。** H2 没有被丢掉，但明确标注"仅供验证，不作为修复依据"，
   且必须写出未闭环的部分。它没有进入第 4 节修复建议。

## 7. 反面示范

| 错误做法 | 为什么错 | 正确做法 |
| --- | --- | --- |
| 把 `CannotGetJdbcConnectionException` 当根因 | 包装异常，等于让读者"去改 Spring" | 取最深 `Caused by`：`SocketTimeoutException` |
| 看到"连接池超时"就建议调大 `maximumPoolSize` | 底层是建连超时，池再大也建不上连接；且配置值日志未提供 | 先 `nc -zv` 确认连通性，配置值写进"待确认" |
| 认定"连接池容量不足导致长期耗尽" | 忽略 L26 的同期成功请求 | 把成功请求写进 `counter_evidence` |
| 把报错点写成 `OrderDao.java:47` | DAO 不是入口；入口是 `OrderController.java:36` | 入口与故障点分列，说明相距几层调用 |
| 建议"重启数据库""kill 掉连接" | 变更操作，且不做排查 | 只给只读命令，变更走评审 |
| 说"可能是网络抖动"但不给验证 | 无证据的推测 | 推测必须跟 `verify`：`nc -zv <DB_HOST> <DB_PORT>` |
