# 诊断报告：BindException（Address already in use）@ 启动失败

> 日志来源：`examples/logs/startup-port-in-use.log` · 分析行数：15（共 15 行） · 分析工具：java-log-diagnoser
> 主链：chain 0（L5–L15，3 层 Caused by） · 业务包：`com.acme`

## 1. 结论摘要

- **根因（置信度：高）**：8080 端口在启动时已被别的进程监听，Tomcat 绑定失败（L9 指明端口，L12 是内核返回的
  `Address already in use`），应用启动中止。
- **影响面**：本次启动的实例完全不可用（进程退出）；若为滚动发布，则表现为"新实例起不来、老实例仍在跑"。
- **建议动作**：按 §5 先确认占用者是谁，再决定换端口还是清理残留进程（后者属变更操作）。

## 2. 关键证据

| # | 日志行 | 证据 | 说明 |
| --- | --- | --- | --- |
| E1 | L4 | `ERROR ... Application run failed` | **[事实]** 失败发生在启动阶段，不是运行时请求 |
| E2 | L5 | `ApplicationContextException: Failed to start bean 'webServerStartStop'` | **[事实]** 失败阶段是 Web 容器启停，不是配置解析、不是数据源初始化 |
| E3 | L9 | `PortInUseException: Port 8080 is already in use` | **[事实]** 唯一明确指出端口的行；没有它只知道"绑定失败" |
| E4 | L12 | `Caused by: java.net.BindException: Address already in use` | **[事实]** 最深一层，来自 JDK NIO 的 bind 调用，是真正的失败点 |
| E5 | L3 | `健康检查端点 /actuator/health 已注册` | **[事实]** 说明配置装配、Bean 创建已完成，进一步排除配置类问题 |

## 3. 根因假设

### H1 同一主机上已有进程监听 8080（置信度：高）

- **依据**：`[事实]` E3 明确给出端口 8080 与 "already in use"；E4 是内核层 `bind` 失败，二者互证。
- **反证**：未发现反证。若是权限问题（非 root 绑定 1024 以下端口），异常会是 `Permission denied` 而非 `already in use`。
- **验证步骤**：
  1. `ss -lntp | grep 8080` — 期望观察：存在 LISTEN 记录及对应进程 PID/名称；
  2. `lsof -i :8080` — 期望观察：同上，交叉确认占用者；
  3. `jps -l` — 期望观察：若看到同一个 `OrderApplication` 主类，说明是上一次未退出的残留实例。
- **若验证不成立**（8080 无人监听却仍报占用）→ 转向 H2

### H2 容器端口映射或 hostNetwork 冲突（置信度：中）

- **依据**：`[推测]` 容器内 `ss` 看不到宿主侧占用，但 bind 仍会失败；常见于 `hostPort` 与 `hostNetwork: true` 混用。
- **反证**：`[事实]` 日志未出现容器相关字样，也没有 K8s 事件，缺直接证据。
- **验证步骤**：
  1. 查看 Pod spec 的 `ports.hostPort` 与 `hostNetwork` 字段 — 期望观察：两者同时使用且端口与其他 Pod 重叠。
- **若验证不成立** → 转向 H3

### H3 上一次进程处于 TIME_WAIT / 未完全释放（置信度：低）

- **依据**：`[推测]` 快速重启时可能出现端口未释放。
- **反证**：`[事实]` L1 显示这是全新启动、PID 1；TIME_WAIT 通常影响 connect 而非 bind（未开 `SO_REUSEADDR` 时才可能）。
- **验证步骤**：
  1. `ss -tanp | grep 8080` — 期望观察：若只有 `TIME_WAIT` 而无 `LISTEN`，则该假设成立。
- **若验证不成立** → 本次不采纳

## 4. 修复建议

### 4.1 止血（分钟级，风险低）

1. 通过配置把 `server.port` 临时改为空闲端口（如 8081），先让实例起来 —— 预期效果：恢复可用；
   回滚方式：改回 8080。**属变更操作，需值班同学执行。**
2. 若确认占用者是本应用的残留进程，停掉它 —— **属变更操作，风险中**，需先确认不是正在服务的实例
   （用 `jps -l` 与 `ss -lntp` 对照，并用 `curl` 探活业务端口）。

### 4.2 根治（天级）

| 改动点 | 具体做法 | 风险 |
| --- | --- | --- |
| 部署脚本 | 启动前做端口预检（`ss -lntp \| grep <PORT>` 为空才启动），失败即退出并告警 | 低 |
| 容器编排 | 固定端口 + Service 转发，避免使用 `hostPort`；`hostNetwork` 仅在确有必要时开启 | 中；需评估网络策略 |
| 停机流程 | 配置优雅停机（`server.shutdown=graceful` + `terminationGracePeriodSeconds`），减少残留 | 低 |
| 启动自检 | 端口被占用时输出占用进程信息，而不是只抛 `BindException` | 低 |

## 5. 建议执行的排查命令（只读）

| 目的 | 命令 | 说明 / 期望观察 |
| --- | --- | --- |
| 确认端口被谁监听 | `ss -lntp \| grep 8080` | 输出 PID/进程名；无输出说明宿主侧确实没人监听，转查容器映射 |
| 交叉确认占用者 | `lsof -i :8080` | 与上一条对照；注意区分 IPv4/IPv6 监听 |
| 找残留 Java 进程 | `jps -l` | 若出现两个 `OrderApplication`，即上一次进程未退出 |
| 看连接状态 | `ss -tanp \| grep 8080` | 只有 `TIME_WAIT` 无 `LISTEN` 时，指向 H3 |
| 确认启动参数 | `jcmd <PID> VM.system_properties \| grep -i server.port` | `<PID>` 由 `jps -l` 获取；确认实际生效端口是否被环境变量覆盖 |

## 6. 分析边界与信息缺口

- 日志完整性：15 行全部参与分析，无截断。
- **业务帧的含义需要特别说明**：脚本给出的 `first_business_frame` 与 `root_business_frame` 都是
  `WebServerConfig.afterPropertiesSet(WebServerConfig.java:22)`（L8）。这只是"业务代码离失败点最近的一帧"，
  它所在的阶段是"触发容器启动"，**不是需要修改的代码位置**。改这一行不会解决端口冲突。
- 未覆盖：无容器编排配置、无历史启动日志（无法判断是否首次部署）、无宿主机端口清单。
- 脚本状态：已运行，`primary_signals=['spring_context','port_in_use']`。

## 7. 待确认

- [ ] 这是首次部署还是滚动更新（决定"清理残留"是否安全）
- [ ] 是否运行在容器内，端口映射方式（hostPort / Service / hostNetwork）
- [ ] 8080 是否被其他业务方占用（需要平台侧确认端口分配）
- [ ] 是否有历史启动成功记录（判断是否与本次变更相关）
