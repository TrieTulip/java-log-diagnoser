# 示例：日志残缺，AI 拒绝瞎猜

考察点：**零信息输入的拒诊**（【信息不足，拒绝盲目诊断】）、**不把关键词当证据**、
**把"缺什么"写成 3 个可执行的问题**。

| 项目 | 路径 |
| --- | --- |
| 输入日志 | [`logs/incomplete-log-refusal.log`](logs/incomplete-log-refusal.log)（1 行） |
| 脚本输出 | [`parsed/incomplete-log-refusal.json`](parsed/incomplete-log-refusal.json)（脚本直接生成） |
| 最终报告 | [`reports/incomplete-log-refusal.report.md`](reports/incomplete-log-refusal.report.md)（降级模板，非七节） |

复现：

```bash
python3 scripts/parse_java_log.py --file examples/logs/incomplete-log-refusal.log --app-package com.acme --pretty
```

## 1. 场景

值班同学转来一句话："应用日志里有条 ERROR，帮我看看。"

他给的就是全部材料：

```
2023-10-27 10:00:00 ERROR - something went wrong, please check the database.
```

没有堆栈、没有异常类名、没有线程名、没有 traceId，连应用名和请求参数都没有。
这是最容易被"编一段听起来很专业的话"糊弄过去的输入——因为读者无法证伪。

## 2. 脚本抽取结果

```json
{
  "summary": {
    "exception_count": 0,
    "chain_count": 0,
    "root_cause_type": null,
    "frame_count": 0,
    "has_business_frame": false
  },
  "chains": [],
  "exceptions": [],
  "business_frames": [],
  "error_lines": [
    {
      "log_line": 1,
      "level": "ERROR",
      "text": "2023-10-27 10:00:00 ERROR - something went wrong, please check the database."
    }
  ],
  "signals": [],
  "warnings": ["未在日志中解析到异常堆栈：可能只有一行错误文本，或日志格式非标准。"]
}
```

**关键字段是 `exception_count=0`。** 这不是"有异常但没堆栈"，而是脚本**连异常都没找到**：
`chains` 为空、`exceptions` 为空，唯一可用的事实只有 `error_lines` 里那一行文本。

与另一个降级示例的区别，决定了两者输出不一样：

| 示例 | 脚本字段 | 报告里能引用什么 |
| --- | --- | --- |
| `insufficient-info` | `exception_count=1`、`chain_length=1`、`frame_count=0` | 可以引用异常类型与消息，但引用不到任何代码位置 |
| `incomplete-log-refusal` | `exception_count=0`、`chain_count=0` | **连异常类型都没有**，报告里不允许把任何异常类名当作事实引用 |

## 3. 为什么连"分析对象"都没有

| 想写的结论 | 能否被日志支持 |
| --- | --- |
| "数据库连接池耗尽" | 否。没有任何连接类异常，也没有池状态 |
| "SQL 执行超时" | 否。没有耗时、没有慢查询、没有超时消息 |
| "数据库账号无权限" | 否。没有任何鉴权失败的痕迹 |
| "这条日志不足以定位代码行" | 是。`exception_count=0`、`frame_count=0` 可直接证实 |
| "需要上下文、堆栈与连接配置才能继续" | 是。缺的是什么，脚本字段已经写明 |

前三条都能从 `database` 一词"顺"出来，但没有任何验证步骤能证实或推翻它们。
按 §0 红线 R3，这种情况必须拒诊，而不是给三个"置信度极低"的猜测。

## 4. Step 3.2：分析中间产物（降级）

```
【信息不足，拒绝盲目诊断】
INSUFFICIENT_INFO
reason: exception_count=0、chain_count=0，日志中没有异常类型与堆栈，无法建立证据链
need:
- 该 ERROR 前后各 50 行上下文（线程名 / traceId / 应用名 / 同时段的其它 WARN、ERROR）
- 完整异常堆栈：从异常类名那行到最后一条 at 帧，含全部 Caused by
- 数据库连接配置（去掉密码）：连接串、池上限与获取超时、是否自动重连
```

`reason` 引用的是脚本字段，不是"我感觉信息不够"。三条 `need` 分别对应用户手上现成的东西：
日志系统里能拉的上下文、控制台里能复制的堆栈、配置文件里能脱敏的连接串。

## 5. Step 4.1：最终报告

见 [`reports/incomplete-log-refusal.report.md`](reports/incomplete-log-refusal.report.md)。
它用降级模板：已知 / 为什么不够 / 需要你补充 / 可以先做的只读检查 / 补齐后怎么分析。

报告第一行就是 **【信息不足，拒绝盲目诊断】**，而不是把这句话藏在第 5 节——
读者在手机上只看前三行，标记必须出现在他一定会看到的位置。
**没有"根因假设"和"修复建议"两节**，这是刻意的：没有证据的建议会把值班同学直接带去查数据库。

## 6. 这个例子演示了什么

1. **关键词不是证据**：`database` 出现在日志里，只能说明"作者希望你看数据库"，不能说明数据库有问题。
2. **拒诊看字段，不看感觉**：`exception_count=0` 是硬事实，"我觉得信息不够"不是。
3. **三个问题都要能立刻动手**：拉上下文、导堆栈、查配置，都是五分钟内能完成的事；
   "请提供更多信息"不是问题，是推卸。
4. **拒诊也给下一步**：报告末尾写了"拿到堆栈后会按什么顺序分析"，用户知道补完之后会发生什么。
5. **不重复不存在的证据**：这份报告里没有出现任何异常类名，也没有出现任何文件名加行号的引用。

## 7. 反面示范

| 错误输出 | 问题 |
| --- | --- |
| "最可能原因：无法确定（置信度：极低）" | 字段名本身就在暗示"总得有个原因"；读者只会记住"数据库"，记不住"极低" |
| "从 `database` 一词看，问题出在数据库" | 把单词当结论，跳过了"先拿到异常"这一步 |
| "建议重启应用并检查数据库连接" | 变更操作 + 无依据；一旦照做，真正的问题被掩盖，还多了一次重启风险 |
| "请提供更多日志以便进一步分析" | 空话；应具体到"前后 50 行 / 完整堆栈 / 连接配置" |
| "这类 ERROR 通常是连接池配置不当导致的" | 用经验统计替代本案证据，属于把先验当事实 |
