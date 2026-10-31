# 诊断报告：OutOfMemoryError（Java heap space）@ 报表导出任务

> 日志来源：`examples/logs/oom-heap-space.log` · 分析行数：20（共 20 行） · 分析工具：java-log-diagnoser
> 主链：chain 1（L11–L20） · 分型：`Java heap space` · 业务包：`com.acme`

## 1. 结论摘要

- **根因（置信度：高）**：报表导出把整份 xlsx 在堆内拼成字节数组，48 万行数据（L10）超过可用堆，
  `XlsxExporter.writeRow`（L18）在 `ByteArrayOutputStream` 扩容时抛 `OutOfMemoryError: Java heap space`（L15）。
- **影响面**：仅导出任务 `scheduling-2`；同期查询接口仍正常，但 JVM 已发生 OOM，后续可能反复 Full GC 拖慢全局。
- **建议动作**：先做 §4.1 的行数上限/任务暂停止血，再按 §4.2 改为流式写出。

## 2. 关键证据

| # | 日志行 | 证据 | 说明 |
| --- | --- | --- | --- |
| E1 | L10 | `报表导出失败 reportId=R20261101-009 rows=480000` | **[事实]** 失败前已确认数据量 48 万行 |
| E2 | L15 | `Caused by: java.lang.OutOfMemoryError: Java heap space` | **[事实]** 分型为堆内存，不是 Metaspace / native thread |
| E3 | L17 | `at java.base/java.io.ByteArrayOutputStream.grow(ByteArrayOutputStream.java:120)` | **[事实]** 失败发生在中间缓冲区扩容，说明数据被整体攒在内存里 |
| E4 | L18 | `at com.acme.report.exporter.XlsxExporter.writeRow(XlsxExporter.java:214)` | **[事实]** 业务侧写入点，最深层 Caused by 中的用户代码 |
| E5 | L5 | `java.net.SocketTimeoutException: Read timed out` | **[事实]** 属于 chain 0（L5–L9），15 分钟前的远程拉取超时；`in_primary_chain=false`，**不作为本次根因依据** |

## 3. 根因假设

### H1 导出过程中把全量行攒在内存字节缓冲区，直至堆耗尽（置信度：高）

- **依据**：`[事实]` E1 + E2 + E3 + E4 同处主链；`ByteArrayOutputStream.grow` 只在需要扩容时出现，
  说明此前已成功写入大量数据。
- **反证**：未发现反证。若为 `Metaspace` 或 `unable to create new native thread`，L15 的分型会不同。
- **验证步骤**：
  1. `jstat -gcutil <PID> 1000 10` — 期望观察：老年代 `O` 接近 100% 且 `FGC` 持续增长后仍不下降；
  2. `jmap -histo <PID> | head -30` — 期望观察：`[B`（byte[]）实例数与总字节数排第一，且远高于其他类型。
- **若验证不成立** → 转向 H2

### H2 单行数据异常巨大，一次扩容即失败（置信度：中）

- **依据**：`[事实]` L16 `Arrays.copyOf` 处于扩容路径；`[推测]` 单个超大字段（如整段 HTML 富文本）也会走到同一行。
- **反证**：若单行超大，失败点更可能在数据读取/反序列化阶段，而不是写出阶段（L18 已进入写行逻辑）。
- **验证步骤**：
  1. `jmap -histo <PID> | head -30` — 期望观察：存在个位数实例但占用极高的 `byte[]` / `String`。
- **若验证不成立** → 转向 H3

### H3 堆上限与容器 limit 不匹配，可用堆偏小（置信度：低）

- **依据**：`[推测]` 容器化部署常见 `-Xmx` 未跟随 limit，导致堆偏小。
- **反证**：`[事实]` L3 显示 1820ms 的聚合查询仍能完成，说明堆在中小负载下够用，不能只凭分型断言"内存给小了"。
- **验证步骤**：
  1. `jcmd <PID> VM.flags` — 期望观察：`MaxHeapSize` 显著低于容器 limit（例如 limit 4G、MaxHeapSize 512M）。
- **若验证不成立** → 本次不采纳该假设

## 4. 修复建议

### 4.1 止血（分钟级，风险低）

1. 暂停或限流导出任务（调度开关）—— 预期效果：阻断 OOM 重复发生；回滚方式：恢复开关。
   **属变更操作，需值班同学在变更窗口执行。**
2. 把单次导出行数上限临时下调到已压测可承受的值 —— 预期效果：大报表报错而不是拖垮进程；
   回滚方式：改回原值。

### 4.2 根治（天级）

| 改动点 | 具体做法 | 风险 |
| --- | --- | --- |
| `XlsxExporter.java:96` | 改用 `SXSSFWorkbook`（滑动窗口）流式写，每 N 行 flush 到磁盘临时文件 | 低；需验证临时目录磁盘余量 |
| `XlsxExporter.java:214` | 写行改为直接写 sheet，去掉中间 `ByteArrayOutputStream` 全量缓冲 | 低 |
| `ReportExportJob.java:58` | 分页查询（如每页 5000 行）+ 导出前按行数估算内存，超阈值直接拒绝并提示分批导出 | 中；需产品确认分批交互 |
| JVM/容器参数 | 让 `-XX:MaxRAMPercentage` 与容器 limit 对齐，并开启 `-XX:+HeapDumpOnOutOfMemoryError` | 低；下次 OOM 才有 dump，不能替代本次分析 |

```java
// 示意，行号与变量名以实际代码为准
try (SXSSFWorkbook wb = new SXSSFWorkbook(200)) {   // 内存中最多保留 200 行
    Sheet sheet = wb.createSheet("report");
    int rowIdx = 0;
    for (Page page : pages) {                        // 分页拉取，不一次取 48 万行
        for (RowData d : page.getRows()) {
            writeRow(sheet.createRow(rowIdx++), d);  // 直接写 sheet，不再攒 byte[]
        }
        wb.flushRows(100);                          // 及时落到临时文件
    }
    wb.write(response.getOutputStream());
}
```

## 5. 建议执行的排查命令（只读）

| 目的 | 命令 | 说明 / 期望观察 |
| --- | --- | --- |
| 确认 GC 是否已失控 | `jstat -gcutil <PID> 1000 10` | `<PID>` 由 `jps -l` 获取；`O` 接近 100 且 `FGC` 递增 |
| 确认内存被谁占满 | `jmap -histo <PID> \| head -30` | 关注 `[B` 与业务 DTO 的实例数、字节数；不要加 `:live` |
| 确认堆上限 | `jcmd <PID> GC.heap_info` | 对比 `-Xmx` 与实际使用，判断是"泄漏"还是"一次装太多" |
| 统计同类失败次数 | `grep -c "报表导出失败" </path/to/app.log>` | 与导出任务触发次数对比，判断是否每次都失败 |
| 拉出该任务完整上下文 | `grep -n "R20261101-009" </path/to/app.log> \| tail -50` | 看失败前是否有重试、是否有其他任务并发 |

## 6. 分析边界与信息缺口

- 日志完整性：20 行全部参与分析，无 `... N more` 截断。
- 未覆盖：无 GC 日志、无 JVM 启动参数、无容器 limit；若进程已重启，`<PID>` 指向的将不是故障现场。
- 主链选择：主链为 chain 1（L11–L20，2 个节点）。chain 0 是更早的远程拉取超时，虽然也命中了 `timeout` 信号，
  但 `in_primary_chain=false`，不能作为本次根因依据。
- 脚本状态：已运行，行号来自 `parsed/oom-heap-space.json`。

## 7. 待确认

- [ ] 导出任务的并发度与单次最大行数配置
- [ ] 容器内存 limit 与 JVM `-Xmx` 的实际取值
- [ ] 是否已开启 `-XX:+HeapDumpOnOutOfMemoryError`（有 dump 才能证实 H2）
- [ ] OOM 之后进程是被 kill 还是自愈（决定影响面写法）
