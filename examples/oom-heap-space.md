# 示例：报表导出 OOM（Java heap space）

考察点：**OOM 必须先分型**、**全文信号不等于根因证据**、**没有 dump/GC 日志时不下"内存给小了"的结论**。

| 项目 | 路径 |
| --- | --- |
| 输入日志 | [`logs/oom-heap-space.log`](logs/oom-heap-space.log)（20 行） |
| 脚本输出 | [`parsed/oom-heap-space.json`](parsed/oom-heap-space.json)（脚本直接生成） |
| 最终报告 | [`reports/oom-heap-space.report.md`](reports/oom-heap-space.report.md) |

复现：

```bash
python3 scripts/parse_java_log.py --file examples/logs/oom-heap-space.log --app-package com.acme --pretty
```

## 1. 场景

报表服务（Spring Boot，包根 `com.acme`）在凌晨 02:10 的定时导出任务中 OOM。日志只有 20 行，含两段互不相关的错误：

- L4–L9：远程数据源拉取 `SocketTimeoutException`（02:08，另一个请求）
- L10–L20：导出任务 48 万行，OOM（02:10）

## 2. 脚本抽取结果（节选）

```json
{
  "schema_version": "1.1",
  "summary": {
    "chain_count": 2,
    "primary_chain_index": 1,
    "chain_length": 2,
    "root_cause_type": "java.lang.OutOfMemoryError",
    "root_cause_message": "Java heap space",
    "root_cause_log_line": 15,
    "frame_count": 12,
    "oom_kind": "Java heap space",
    "primary_signals": ["oom"],
    "noise_signals": ["timeout"]
  },
  "out_of_memory": { "present": true, "kind": "Java heap space", "log_line": 15 },
  "first_business_frame": { "method": "export", "file": "ExportController.java", "line": 71, "log_line": 14 },
  "root_business_frame": { "method": "writeRow", "file": "XlsxExporter.java", "line": 214, "log_line": 18 }
}
```

两条链与信号归属：

| 链 | 行区间 | 节点数 | 结构 |
| --- | --- | --- | --- |
| chain 0 | L5–L9 | 1 | `SocketTimeoutException`（远程拉取超时，与本问题无关） |
| chain 1（主链） | L11–L20 | 2 | `NestedServletException`(L11) → `OutOfMemoryError: Java heap space`(L15) |

`primary_signals=['oom']`、`noise_signals=['timeout']`——**这是本示例最重要的一个字段**。
`timeout` 同样命中了日志（L5），但它落在 chain 0，不属于主链。若不加区分地把 `signals` 全当作根因线索，
就会写出"导出失败是因为远程数据源超时"这种看似有据、实际错位的结论。

## 3. 分型为什么必须先做

`oom_kind = "Java heap space"` 决定了后面所有动作：

- `Java heap space` → 查"一次性加载了多少数据"、`jmap -histo` 看谁在占堆；
- `Metaspace` → 查动态生成类（CGLIB/反射/热部署），与 `-Xmx` 无关；
- `unable to create new native thread` → 查线程数与 `ulimit -u`，加堆反而更糟。

本示例里 `ByteArrayOutputStream.grow`（L17）出现在扩容路径，说明数据是**整体攒在内存里**再写出的，
与"堆给小了"是两个不同结论：前者改代码（流式写），后者改参数。日志没有 `-Xmx`、没有 GC 日志、
没有 dump，所以"内存给小了"只能作为低置信假设（H3），并附验证命令，不能写进结论。

## 4. Step 3.1：命中的知识

- `oom` → `references/java-exceptions.md#oom`（分型表 + 四类分型的排查方向）。
- `signals.in_primary_chain` 为 `false` 的 `timeout` 不加载 `#connectivity`，避免把无关章节带进上下文。

## 5. Step 3.2：分析中间产物

按 `prompts/extract_root_cause.md` 执行：先取证（只复制原文），再假设，再反证，最后八问自审。

```
### 1. 链定位
chain_index: 1 / chain_length: 2
root_cause: java.lang.OutOfMemoryError — Java heap space [L15] [事实·脚本]
discarded_chains: chain 0 — 02:08 的远程拉取超时，属于另一条链，与本任务无调用关系

### 2. 代码位置
业务包: com.acme
报错点: com.acme.report.web.ExportController.export(ExportController.java:71) [L14] [事实·脚本]
故障点: com.acme.report.exporter.XlsxExporter.writeRow(XlsxExporter.java:214) [L18] [事实·脚本]
说明: DispatcherServlet 分发到 export，下层 writeRow 在扩容缓冲区时抛出 OOM；
      报错点是请求入口，故障点是内存增长点。

### 3. 语义归类
class: oom
knowledge_section: references/java-exceptions.md#oom
signals_used: oom (primary), timeout (noise) | noise: timeout（chain 0，in_primary_chain=false）

### 4. 证据表（只放原文，不放结论）
E1 | L10 | > 2026-11-01 02:10:44.318 ERROR 1 --- [scheduling-2] c.a.r.job.ReportExportJob           : 报表导出失败 reportId=R20261101-009 rows=480000
E2 | L15 | > Caused by: java.lang.OutOfMemoryError: Java heap space
E3 | L17 | > 	at java.base/java.io.ByteArrayOutputStream.grow(ByteArrayOutputStream.java:120)
E4 | L18 | > 	at com.acme.report.exporter.XlsxExporter.writeRow(XlsxExporter.java:214)
E5 | L14 | > 	at com.acme.report.web.ExportController.export(ExportController.java:71)
E6 | L5  | > java.net.SocketTimeoutException: Read timed out

### 5. 假设
H1 | confidence=high | 全量行在堆内攒成字节数组，48 万行超出可用堆
- 引用: E1, E2, E3, E4, E5
- 推理链: E1 的 `rows=480000` 说明本次导出量级；E2 把分型锁定为 Java heap space；
  E3 的 `ByteArrayOutputStream.grow` 表明内存在写缓冲扩容时被打满；E4 落在 writeRow；
  E5 是请求入口，说明内存是在这条导出链路里涨起来的 → 整批数据攒在堆里，没有流式写出 [推测]
- counter_evidence: 无。分型不是 Metaspace，也不是 unable to create new native thread，另两类可排除
- verify:
  1. `jstat -gcutil <PID> 1000 10` — 期望观察：O 区接近 100 且 FGC 后不回落
  2. `jmap -histo <PID> | head -30` — 期望观察：`[B`（byte[]）占用居首
- basis: 知识库 #oom 中 "Java heap space" 的排查方向

H2 | confidence=medium | 单行字段异常巨大，一次扩容即失败
- 引用: E3, E4
- 推理链: E3 的扩容点与 E4 的 writeRow 同一条路径，若单行超大，这里会先崩 [推测]。
  未闭环部分：日志没给单行大小，也没有堆直方图
- counter_evidence: 若单行超大，失败点更可能在读取/反序列化阶段，而非写出阶段
- verify:
  1. `jmap -histo <PID> | head -30` — 期望观察：存在极少数超大 `byte[]` / `String` 实例
- basis: 扩容路径的常见触发形态

H3 | confidence=low | 堆上限与容器 limit 不匹配
- 引用: E2
- 推理链: E2 只能证明"堆被打满"，不能说明上限是否合理 [推测]。
  未闭环部分：无 JVM 参数、无容器 limit，判断不了是"装太多"还是"给太少"
- counter_evidence: 无直接反证；同一进程 02:05 的中小负载查询仍成功，说明日常负载下堆够用
- verify:
  1. `jcmd <PID> VM.flags` — 期望观察：MaxHeapSize 明显低于容器 memory limit
- basis: 容器化部署的通用经验

### 6. 已排除
- 远程数据源超时：timeout 证据全在 chain 0（E6/L5），`in_primary_chain=false`，且主链无任何网络异常 — 依据: E6
- Metaspace / 直接内存 / 线程创建失败：E2 的分型不符 — 依据: E2
- 数据库连接问题：日志无 SQLException / HikariPool 命中，主链帧全部在导出路径 — 依据: E4

### 7. 信息缺口
- 无 GC 日志与 JVM 参数，无法判断是"一次装太多"还是"存在泄漏"
- 无 HeapDump，H2 无法直接证实
- 进程可能已被重启，`<PID>` 需重新获取

### 8. 自我审查
| # | 自查问题 | 结论 | 处置 |
| --- | --- | --- | --- |
| 1 | 每个 L 编号都在原文中存在且内容对应？ | 是 | — |
| 2 | E 表每段引用都与原文逐字一致？ | 是 | 由日志逐行复制 |
| 3 | 每个假设都引用了真实存在的 E 编号？ | 是 | H1→E1-E4，H2→E3/E4，H3→E2 |
| 4 | 假设里的类名/方法名/配置项都在日志或脚本输出中出现过？ | 是 | — |
| 5 | 是否把包装异常当成了根因？ | 否 | NestedServletException 只作链路节点 |
| 6 | 无业务帧时是否仍指出了具体代码行？ | 否 | 业务帧已识别 |
| 7 | 每条假设都有反证与可执行的验证步骤？ | 是 | — |
| 8 | 是否出现"可能/大概/建议重启"这类无证据表述？ | 否 | — |
SELF_CHECK: PASS_WITH_GAPS
```

`PASS_WITH_GAPS`：结论无幻觉，但缺 GC 日志与堆直方图，H2/H3 只能验证不能确认。

## 6. Step 4.1：最终报告

见 [`reports/oom-heap-space.report.md`](reports/oom-heap-space.report.md)。一句话结论：

> 导出 48 万行时把整份 xlsx 攒在堆内字节缓冲区，`XlsxExporter.writeRow`（L18）扩容时堆耗尽；
> 不是 Metaspace、不是远程超时、也没有证据支持"堆给小了"。

## 7. 这个例子演示了什么

1. **主链 = 节点最多，不是"最后出现的错误"**：这里恰好两者一致，但真正起作用的是 `chain_length=2`。
2. **信号要区分归属**：`noise_signals=['timeout']` 的存在，恰好说明为什么不能拿 `signals` 直接当根因。
3. **分型先于建议**：没有 `oom_kind` 就写"加 `-Xmx`"是典型的模板化输出，本示例明确把它降为低置信假设。
4. **报错点 ≠ 故障点**：`ExportController.export:71`（L14）是入口，`XlsxExporter:214`（L18）才是内存增长点。

## 8. 反面示范

| 错误输出 | 问题 |
| --- | --- |
| "OOM 说明内存不足，建议把 -Xmx 调到 8G" | 未分型、未验证就改参数，可能只是把 OOM 推迟到 96 万行 |
| "导出失败是因为远程数据源 Read timed out" | 把 chain 0 的信号当成 chain 1 的原因，时间与调用关系都对不上 |
| "存在内存泄漏，建议用 MAT 分析 dump" | 日志未提供 dump；是否有泄漏尚未验证，不能先断言泄漏 |
| "报告导出接口第 96 行有内存问题" | 日志中 `XlsxExporter.java:96` 是 `export` 方法的帧（L19），增长点在 `writeRow`（L18），写错行会改错方法 |
