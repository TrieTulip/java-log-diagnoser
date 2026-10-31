# 诊断报告：订单查询接口获取数据库连接超时（HikariPool 等待 30 秒）

> 日志来源：`examples/logs/db-connection-timeout.log` · 分析行数：30（共 30 行） · 分析工具：java-log-diagnoser
> 主链：chain 0（L5–L22） · 根因：`java.net.SocketTimeoutException: connect timed out` · 业务包：`com.acme`

## 1. 结论摘要

- **根因（置信度：中）**：`OrderDao.selectByOrderNo(OrderDao.java:47)` 触发数据库查询时，
  HikariCP 在 30 秒内没能拿到可用连接，最底层是 `java.net.SocketTimeoutException: connect timed out`——
  超时发生在 **TCP 建连阶段**，不是 SQL 执行慢，也不是连接池被占满后的排队等待。
- **影响面**：单笔订单查询失败并返回兜底结果（L24）；13 秒后另一笔订单查询成功（L26），
  属**瞬时、间歇性**故障，不是持续性不可用。
- **建议动作**：先按 4.1 验证数据库连通性并收敛超时时间；再按 4.2 排查应用到数据库的网络链路与连接数水位。

## 2. 关键证据

| # | 日志行 | 证据（逐字原文） | 说明 |
| --- | --- | --- | --- |
| E1 | L4 | `2026-11-01 09:15:52.318 ERROR 1 --- [http-nio-8080-exec-7] c.acme.order.OrderController     : 查询订单失败` | **[事实]** 失败发生在 HTTP 工作线程 `http-nio-8080-exec-7` |
| E2 | L5 | `org.springframework.jdbc.CannotGetJdbcConnectionException: Failed to obtain JDBC Connection; nested exception is java.sql.SQLTransientConnectionException: HikariPool-1 - Connection is not available, request timed out after 30000ms` | **[事实]** 包装异常，仅说明"获取连接"失败；`HikariPool-1` 等待 30000ms |
| E3 | L8 | `at com.acme.order.dao.OrderDao.selectByOrderNo(OrderDao.java:47)` | **[事实]** 业务代码中发起数据库查询的位置 |
| E4 | L10 | `at com.acme.order.controller.OrderController.detail(OrderController.java:36)` | **[事实]** HTTP 请求入口，业务调用链最外层 |
| E5 | L14 | `Caused by: java.sql.SQLTransientConnectionException: HikariPool-1 - Connection is not available, request timed out after 30000ms` | **[事实]** 第一层原因：连接池 30 秒内无可用连接 |
| E6 | L20 | `Caused by: java.net.SocketTimeoutException: connect timed out` | **[事实]** 最深层原因：TCP 建连超时，是本次故障的落点 |
| E7 | L24 | `2026-11-01 09:15:52.401  INFO 1 --- [http-nio-8080-exec-7] c.acme.order.OrderController     : 返回兜底结果` | **[事实]** 接口有兜底，未直接抛出 500 |
| E8 | L26 | `2026-11-01 09:16:05.090  INFO 1 --- [http-nio-8080-exec-9] c.acme.order.OrderController     : 查询成功` | **[事实]** 13 秒后成功，反证"持续不可用"与"连接池长期耗尽" |

> 证据链：请求入口（E4/L10）→ DAO 查询（E3/L8）→ 获取连接失败（E2/L5）→ 池等待 30 秒（E5/L14）
> → TCP 建连超时（E6/L20）→ 兜底返回（E7/L24）→ 13 秒后恢复（E8/L26）。

## 3. 根因假设

### H1 数据库 TCP 建连超时，HikariCP 等待 30 秒仍拿不到可用连接（置信度：中）

- **依据**：E2 说明失败发生在获取 JDBC 连接阶段（SQL 尚未执行）；E5 说明 `HikariPool-1` 等待 30000ms；
  E6 最深层为 `connect timed out`，超时落在 TCP 建连阶段，指向数据库主机网络层不可达或对端丢弃建连请求。
- **反证**：E8（L26）13 秒后同一接口查询成功，不支持"数据库长时间不可达"或"连接池持续耗尽"，倾向瞬时抖动。
- **验证步骤**：
  1. `nc -zv <DB_HOST> <DB_PORT>` — 期望观察：超时/无响应支持网络层不可达；返回 `refused` 则改判端口未监听。
  2. `ss -lntp | grep <DB_PORT>` — 期望观察：数据库主机上应能看到监听；无输出说明 DB 进程未监听。
  3. 打开 `OrderDao.java:47` 与 `OrderQueryService.java:88` 核对是否为简单单表查询 —
     期望观察：若是简单查询仍等待 30 秒，则不支持"慢 SQL 占满连接"。
- **若验证不成立**：转向 H2（连接池容量不足导致排队超时）。

### H2 连接池容量不足，峰值时排队等待超时（置信度：低，**仅供验证，不作为修复依据**）

- **依据**：E5 的 "request timed out after 30000ms" 也可能是池内连接被占满后的排队超时。
- **未闭环部分**：日志未提供 `maximumPoolSize`、活跃连接数与慢 SQL 信息，无法证明池内连接确实被占满。
- **反证**：E6 底层是建连超时，池被占满时通常不会在 TCP 建连阶段失败；E8 显示 13 秒后即恢复。
- **验证步骤**：
  1. `jstack <PID> | head -200` — 期望观察：大量线程停在 `HikariPool.getConnection` 说明池被争抢；少量则倾向 H1。
  2. 确认连接池 `maximumPoolSize` 与 `connectionTimeout` 的实际取值 — 期望观察：与日志中的 30000ms 对照。

### 已排除

| 候选原因 | 排除依据 |
| --- | --- |
| 数据库端口未监听（`Connection refused`） | 日志未出现 `Connection refused`，底层是 `connect timed out`（E6/L20） |
| 慢 SQL 拖垮连接池 | 异常发生在获取连接阶段，未进入 SQL 执行（E2/L5） |
| 日报任务故障连带 | 属另一条链（chain 1），线程为 `scheduling-1`，与本次接口无关（L27） |
| 全站不可用 | 09:16:05 另一笔订单查询成功（E8/L26） |
| 接口直接抛 500 无兜底 | L24 显示本次请求返回了兜底结果（E7） |

## 4. 修复建议

> H1 置信度为"中"，以下建议**先验证再落地**；H2 为低置信度，未纳入本节。

### 4.1 止血（分钟级，风险低）

1. 按第 5 节第 1、2 条确认数据库当前是否可达、端口是否正常监听；
   若 `nc` 也超时，问题在网络/数据库侧，不必改应用代码。
2. 复核数据源是否设置了快速失败：把等待连接的超时从 30 秒收敛到秒级，
   避免一个不可用的数据库把 HTTP 工作线程全部拖住（`http-nio-8080-exec-*` 被占满会放大成接口雪崩）。
3. 确认 E7（L24）的兜底逻辑覆盖了所有依赖数据库的读接口，避免用户侧看到裸错误页。

### 4.2 根治（天级）

1. 排查应用到数据库的网络链路：安全组/防火墙策略、VIP 或 DNS 解析、跨可用区访问，
   以及故障时段数据库侧是否有主从切换或连接数打满。
2. 建立数据库连接连通性与 `HikariPool` 等待耗时的监控告警，
   让"等 30 秒才失败"在发生前（如等待连接数持续上升）就能被发现。
3. 复核连接池容量与连接回收：确认是否存在未关闭连接的代码路径。

## 5. 建议执行的排查命令（只读）

| # | 命令 | 用途 | 期望观察 |
| --- | --- | --- | --- |
| 1 | `nc -zv <DB_HOST> <DB_PORT>` | 测数据库端口连通性 | `succeeded`=可达；超时/无响应=网络层不可达；`refused`=端口未监听 |
| 2 | `ss -lntp \| grep <DB_PORT>` | 在数据库主机查监听 | 有输出说明 DB 在监听；无输出说明进程未起 |
| 3 | `jstack <PID> \| head -200` | 看有多少线程卡在取连接 | 大量 `HikariPool.getConnection` → 支持 H2；少量 → 支持 H1 |
| 4 | `grep -n "Connection is not available" </path/to/app.log>` | 统计同类失败次数与时段 | 判断是偶发还是持续；与 DB 侧告警时点对齐 |

> `<DB_HOST>` / `<DB_PORT>` 取自应用数据源配置；`<PID>` 由 `jps -l` 获取；
> `</path/to/app.log>` 替换为实际日志路径。

## 6. 分析边界与信息缺口

- 已按 Step 4.2 运行 `scripts/validate_diagnosis.py`，报告中的类名、源码行号与 `L` 号均已回日志比对通过。
- 本次只分析主链（chain 0，3 个节点）；chain 1（日报任务 `IllegalStateException`）已记为噪声，未纳入结论。
- 日志含 `... 42 more`、`... 47 more`、`... 51 more` 三处省略帧，
  无法确认中间是否插入了自定义拦截器或数据源代理层。
- 未提供：数据库主机地址与端口、应用与数据库之间的网络策略、连接池 `maximumPoolSize` 与
  `connectionTimeout` 实际取值、故障时段数据库侧的监控数据。
- 未提供：完整未省略的堆栈、应用与驱动的准确版本。

## 7. 待确认

1. 数据库主机地址与端口是多少？应用与数据库之间是否经过防火墙、安全组或代理？——决定 H1 能否闭环。
2. 连接池的 `maximumPoolSize` 实际取值是多少？故障时段活跃连接数是否有监控数据？——决定 H2 能否闭环。
3. 09:15:22–09:15:52 期间数据库侧是否有主从切换、CPU 打满或连接数告警？——决定故障是网络侧还是数据库侧。
4. 能否提供完整未省略的堆栈（含 `... N more` 展开后的部分）？——确认中间是否有数据源代理。
