# 示例：启动失败——8080 端口被占用

考察点：**外层包装异常不是根因**、**业务帧是触发点不是故障点**、**`PortInUseException` 与 `BindException` 各自提供了什么信息**。

| 项目 | 路径 |
| --- | --- |
| 输入日志 | [`logs/startup-port-in-use.log`](logs/startup-port-in-use.log)（15 行） |
| 脚本输出 | [`parsed/startup-port-in-use.json`](parsed/startup-port-in-use.json)（脚本直接生成） |
| 最终报告 | [`reports/startup-port-in-use.report.md`](reports/startup-port-in-use.report.md) |

复现：

```bash
python3 scripts/parse_java_log.py --file examples/logs/startup-port-in-use.log --app-package com.acme --pretty
```

## 1. 场景

订单服务 v2.7.1 启动即退出。日志里有三条 WARN/INFO 干扰项（废弃配置项、健康检查注册），
很容易被误读成"配置有问题"或"actuator 有问题"。

## 2. 脚本抽取结果（节选）

```json
{
  "summary": {
    "chain_count": 1, "primary_chain_index": 0, "chain_length": 3,
    "root_cause_type": "java.net.BindException",
    "root_cause_message": "Address already in use",
    "root_cause_log_line": 12,
    "primary_signals": ["spring_context", "port_in_use"],
    "noise_signals": []
  },
  "first_business_frame": { "method": "afterPropertiesSet", "file": "WebServerConfig.java", "line": 22, "log_line": 8 },
  "root_business_frame": { "method": "afterPropertiesSet", "file": "WebServerConfig.java", "line": 22, "log_line": 8 }
}
```

三层链：

| 层 | 异常 | 行 | 提供了什么信息 |
| --- | --- | --- | --- |
| 0 | `ApplicationContextException: Failed to start bean 'webServerStartStop'` | L5 | 失败**阶段**：Web 容器启停，不是配置解析/数据源 |
| 1 | `PortInUseException: Port 8080 is already in use` | L9 | 失败**对象**：端口 8080（只有这一层给出端口号） |
| 2 | `BindException: Address already in use` | L12 | 失败**原因**：内核 bind 返回 EADDRINUSE（真正失败点） |

三层缺一不可：只有 `BindException` 时不知道是哪个端口；只有 `ApplicationContextException` 时连方向都没有。

## 3. 两个容易写错的地方

**（1）把 L5 当根因。** `ApplicationContextException` 是 Spring 的包装异常，脚本给出的
`root_cause_type` 是最深一层的 `BindException`，不是它。

**（2）把业务帧当故障点。** 脚本的 `first_business_frame` 与 `root_business_frame` 都指向
`WebServerConfig.afterPropertiesSet(WebServerConfig.java:22)`（L8）。这是因为三层里只有这一层含 `com.acme` 包，
它恰好是"主动触发容器启动"的那一行。**改这一行不会解决端口冲突**——真正的失败在 Tomcat 与操作系统之间。
这类"业务帧只是入口"的情形，报告里必须显式说明，否则读者会去改代码。

判断方法：看业务帧**下面还有没有非业务帧**。本例 L10–L11（Tomcat）、L13–L15（JDK NIO）都排在业务帧之后，
说明异常在离开业务代码之后才发生。

## 4. Step 3.1：命中的知识

- `port_in_use` → `references/java-exceptions.md#startup`（启动失败章节）+ `#connectivity`（端口/监听判定）
- `spring_context` → 同章节的"怎么读 BeanCreationException 链"，本例用于确认"外层只是包装"
- 命令取自 `references/safe-commands.md` 第 4 节（网络）

## 5. Step 3.2：分析中间产物

按 `prompts/extract_root_cause.md` 执行。本例的关键是：外层 `ApplicationContextException` 只是壳，
真正的失败点在最深一层 `Caused by`。

```
### 1. 链定位
chain_index: 0 / chain_length: 3
root_cause: java.net.BindException — Address already in use [L12] [事实·脚本]
discarded_chains: 无（日志只有一条链）

### 2. 代码位置
业务包: com.acme
报错点: com.acme.order.config.WebServerConfig.afterPropertiesSet(WebServerConfig.java:22) [L8] [事实·脚本]
故障点: 日志未提供（失败发生在 Tomcat 启动与 JDK NIO bind，无业务代码帧）
说明: 业务帧只是触发容器启动，异常在离开业务代码后才抛出，不能据此修改 WebServerConfig

### 3. 语义归类
class: framework-startup
knowledge_section: references/java-exceptions.md#startup
signals_used: spring_context (primary), port_in_use (primary) | noise: 无

### 4. 证据表（只放原文，不放结论）
E1 | L5  | > org.springframework.context.ApplicationContextException: Failed to start bean 'webServerStartStop'
E2 | L8  | > 	at com.acme.order.config.WebServerConfig.afterPropertiesSet(WebServerConfig.java:22)
E3 | L9  | > Caused by: org.springframework.boot.web.server.PortInUseException: Port 8080 is already in use
E4 | L12 | > Caused by: java.net.BindException: Address already in use
E5 | L3  | > 2026-11-01 08:15:04.113  INFO 1 --- [main] c.a.o.c.HealthCheckConfig            : 健康检查端点 /actuator/health 已注册

### 5. 假设
H1 | confidence=high | 同一主机已有进程监听 8080，新实例 bind 失败
- 引用: E1, E3, E4
- 推理链: E1 指出失败阶段是 `webServerStartStop`（容器启停）；E3 明确写 "Port 8080 is already in use"；
  E4 的 bind 失败是 E3 的直接原因 → 端口被别的进程占着 [推测]
- counter_evidence: 无。若为权限问题（低端口需 root），消息通常是 Permission denied 而非 already in use
- verify:
  1. `ss -lntp | grep 8080` — 期望观察：存在 LISTEN 状态与占用进程
  2. `lsof -i :8080` — 期望观察：交叉确认占用者
  3. `jps -l` — 期望观察：若出现同主类进程，说明上次实例未退出
- basis: 知识库 #startup 中"端口被占用"分支

H2 | confidence=medium | 容器端口映射或 hostNetwork 冲突
- 引用: E3, E4
- 推理链: E3 说明 8080 在 bind 时已被占；若宿主侧 `ss` 查不到占用者，可能是容器网络命名空间重叠 [推测]。
  未闭环部分：日志无容器相关信息
- counter_evidence: 无直接反证；日志未提及容器、Pod、hostPort
- verify:
  1. 检查 Pod spec 的 hostPort 与 hostNetwork 字段 — 期望观察：两者并用且端口重叠
- basis: 经验，需部署配置佐证

H3 | confidence=low | 上次进程残留，端口未释放
- 引用: E4
- 推理链: E4 只能证明 bind 失败，无法区分"别的进程在听"与"残留状态未释放" [推测]。
  未闭环部分：无历史启动日志、无进程列表
- counter_evidence: E2 显示 PID 1 全新启动；TIME_WAIT 一般影响 connect 而非 bind，概率低
- verify:
  1. `ss -tanp | grep 8080` — 期望观察：只有 TIME_WAIT 而无 LISTEN
- basis: 模式匹配，优先级最低

### 6. 已排除
- 配置缺失/解析失败：E5 显示健康检查端点已注册，说明配置装配已完成 — 依据: E5
- 数据源不可用：主链无 SQLException / HikariPool 命中，失败阶段在 Web 容器而非 DAO — 依据: E1
- 依赖缺失：无 ClassNotFoundException / NoClassDefFoundError 命中，类加载阶段已通过 — 依据: E2

### 7. 信息缺口
- 无容器编排配置，H2 无法证实
- 无历史启动日志，无法判断是否首次部署
- 不知 8080 是否为平台分配的固定端口（影响能否直接改端口）

### 8. 自我审查
| # | 自查问题 | 结论 | 处置 |
| --- | --- | --- | --- |
| 1 | 每个 L 编号都在原文中存在且内容对应？ | 是 | — |
| 2 | E 表每段引用都与原文逐字一致？ | 是 | 由日志逐行复制 |
| 3 | 每个假设都引用了真实存在的 E 编号？ | 是 | H1→E1/E3/E4，H2→E3/E4，H3→E4 |
| 4 | 假设里的类名/方法名/配置项都在日志或脚本输出中出现过？ | 是 | 未引入日志外的组件名 |
| 5 | 是否把包装异常当成了根因？ | 否 | ApplicationContextException、PortInUseException 只作链路节点 |
| 6 | 无业务帧时是否仍指出了具体代码行？ | 否 | 故障点写明"日志未提供"，未编造行号 |
| 7 | 每条假设都有反证与可执行的验证步骤？ | 是 | — |
| 8 | 是否出现"可能/大概/建议重启"这类无证据表述？ | 否 | — |
SELF_CHECK: PASS_WITH_GAPS
```

注意"故障点：日志未提供"这一行：本例业务帧存在（`WebServerConfig:22`），但它只是触发容器启动，
真正失败在 Tomcat/NIO 内部。按红牌 2，不允许把业务行号当故障点，也不允许为框架内部编一个行号。

## 6. Step 4.1：最终报告

见 [`reports/startup-port-in-use.report.md`](reports/startup-port-in-use.report.md)。一句话结论：

> 8080 已被占用导致 Tomcat bind 失败（L9 给端口、L12 给原因）；业务帧 `WebServerConfig:22` 只是触发点，
> 修改它无效，应先确认占用者。

## 7. 这个例子演示了什么

1. **"最深 Caused by" 才是根因**：`ApplicationContextException` 看起来最"严重"，但它只是包装。
2. **业务帧不必然是故障点**：当业务帧下方还有框架/JDK 帧时，说明异常发生在业务代码之外。
3. **一条链里三层各自的价值**：阶段 / 对象 / 原因，报告应把三层都写进证据表，而不是只抄最后一层。
4. **干扰项处理**：废弃配置 WARN（L2）、健康检查 INFO（L3）都与失败无关，报告里一句"已排除"带过，不展开。

## 8. 反面示范

| 错误输出 | 问题 |
| --- | --- |
| "根因是 ApplicationContextException，Spring 上下文启动失败" | 把包装异常当根因，读者仍然不知道要查什么 |
| "修改 WebServerConfig.java:22 增加端口判断" | 业务帧是触发点，改代码无效；应该查谁占用了端口 |
| "端口冲突，重启服务即可" | 重启解决不了"别的进程占着 8080"，且属变更操作 |
| "配置项 order.legacy.mode 已废弃导致启动失败" | 把 WARN 当 ERROR；L2 与失败无因果关系 |
