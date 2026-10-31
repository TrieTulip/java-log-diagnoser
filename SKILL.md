---
name: java-log-diagnoser
description: 诊断 Java 应用报错日志并输出结构化诊断报告。当用户粘贴 Java 异常堆栈、GC/OOM 日志，或出现 NullPointerException、OutOfMemoryError、StackOverflowError、ClassNotFoundException、NoClassDefFoundError、NoSuchMethodError、BeanCreationException、UnsatisfiedDependencyException、SQLException、HikariPool、Connection refused、Address already in use、依赖冲突、启动失败、接口 500、线上报错等关键词，或说"帮我看看这段报错""定位一下这个异常""为什么启动失败"时使用。输出包含事实证据、根因假设、验证命令与修复建议的 Markdown 报告。
---

# Java 日志诊断

把一段 Java 日志变成一份可执行、可追溯的诊断报告。目标不是"解释异常是什么"，
而是回答四个问题：**哪一行代码出错、为什么错、怎么验证、怎么修**。

## 1. 何时使用

- 用户粘贴了 Java 堆栈、异常信息、`Caused by` 链、GC 日志、容器/进程退出日志
- 关键词命中：`NullPointerException`、`OutOfMemoryError`、`StackOverflowError`、
  `ClassNotFoundException`、`NoClassDefFoundError`、`NoSuchMethodError`、
  `BeanCreationException`、`Connection refused`、`Address already in use`、
  `HikariPool`、`Deadlock`、`依赖冲突`、`启动失败`、`线上报错`、`接口 500`
- 用户要求"排查 / 定位 / 分析 / 看下这段日志"

## 2. 何时不使用

- 非 Java 技术栈日志（Go / Python / Node）——直接分析，不要套用本流程
- 纯 API 用法、语法、框架特性咨询
- 需要登录生产机器执行变更（重启、回滚、改配置、kill 进程）——超出只读边界，转人工
- 用户只要求翻译或摘要日志，不需要根因

## 3. 四件套职责与加载时机（渐进式加载）

| 路径 | 角色 | 何时加载 |
| --- | --- | --- |
| `SKILL.md` | 骨架：流程、边界、强约束 | 始终 |
| `scripts/parse_java_log.py` | 事实抽取：Caused by 链、OOM 类型、首个业务帧 | Step 1，必跑 |
| `prompts/extract_root_cause.md` | 根因分析指令模板 | Step 3 |
| `prompts/generate_report.md` | 报告结构与措辞规范 | Step 4 |
| `references/java-exceptions.md` | 异常知识库（NPE/OOM/类加载/依赖冲突/连接类…） | Step 2，按异常类型读 1–3 节 |
| `references/safe-commands.md` | 只读排查命令白名单 | Step 3/4，需要给验证命令时 |
| `examples/*.md` | 输入输出样例，用于对齐格式 | 需要对齐输出格式时 |

**渐进式加载原则**：一次只读一个文件的一节。不要为了"全面"把 `references/` 全量塞进上下文——
它会让报告变长而不是变准。

## 4. 工作流（严格按顺序执行）

### Step 0 预处理（在心里完成，不作为输出）

- **判断日志类型**：启动失败 / 运行时报错 / OOM 被杀 / 请求超时 / 定时任务失败。
  同一份堆栈，启动期和运行期的排查方向完全不同。
- **找边界**：日志是否被截断？只有 `Caused by` 没有 `at`、出现 `... 23 more`、
  出现 `[truncated]` / `... (省略)`，都说明信息不全。
- **脱敏**：密码、token、AK/SK、手机号、身份证、内网 IP、连接串凭据，
  在最终输出中替换为 `<REDACTED>`，保留字段结构便于定位。
- **判断信息是否足够**：缺堆栈、缺版本、缺关键配置时，走 Step 4 的"信息不足"分支，
  不要用通用建议凑字数。

### Step 1 结构化抽取（脚本优先，禁止跳过）

```bash
# 推荐：显式指定应用根包名，业务帧判定最准
python3 scripts/parse_java_log.py --file app.log --app-package com.yourcompany --pretty > parsed.json

# 或管道输入（日志不在本地时，先让用户保存到文件）
cat app.log | python3 scripts/parse_java_log.py --pretty
```

规则：

- **脚本输出是唯一事实来源**。异常类型、消息、行号、`Caused by` 层级、业务帧
  一律从 `parsed.json` 取，不靠肉眼复制。
- 日志超过 200000 行时先用 `tail -n 200000` 截尾，并在报告"分析边界"注明只分析了尾部。
- 脚本无法运行或无输出 → **降级**：手工沿 `Caused by` 逐层阅读，并在报告
  "分析边界"注明"脚本未运行 / 无结构化结果"，同时降低结论置信度。
- 业务帧识别不准时，请用户提供应用根包名（`--app-package`），不要靠猜。

### Step 2 按需加载知识

- 依据 `summary.root_cause_type` 与 `signals` 决定读 `references/java-exceptions.md` 的哪几节。
- 需要"让用户自己验证"时读 `references/safe-commands.md`。
- 需要对齐报告格式时看 `examples/`。

### Step 3 根因分析

以 `prompts/extract_root_cause.md` 为系统指令，输入 = 脱敏日志 + `parsed.json` + 相关知识条目。
产出 1–3 个根因假设，按可能性降序。

### Step 4 生成报告

以 `prompts/generate_report.md` 为系统指令。报告必须包含：
结论摘要 / 关键证据（带行号）/ 根因假设（含置信度与验证步骤）/
修复建议（分"止血"与"根治"）/ 分析边界与信息缺口。

## 5. 强约束（违反任意一条，本次输出即视为失败）

1. **不编造**。行号、类名、方法名、异常消息、依赖版本一律来自日志或脚本 JSON。
   日志里没有就写"日志未提供"，绝不补全。
2. **事实与推测分离**。每条结论标注 `[事实]`（日志可直接看到）或 `[推测]`（经验推断），
   推测必须附验证方法。
3. **命令只读**。只推荐 `references/safe-commands.md` 白名单内的命令。
   `kill -9`、`rm`、`DROP/TRUNCATE`、`jmap -dump` 落盘、改配置、重启发布属于变更操作，
   只能写成"建议由值班同学在变更窗口执行"并标注风险，不提供一键粘贴命令。
4. **占位符化**。命令中的 PID、路径、主机名使用 `<PID>`、`</path/to/app.log>` 占位，
   并说明取值方式（如 `通过 jps -l 获取`）。
5. **不臆断根因**。日志只有 `Connection refused` 时，不得断言"数据库挂了"，
   必须写成假设 + 验证命令。
6. **假设 1–3 个**，按可能性降序，每个假设必须有可执行的验证步骤。
7. **信息不足要明说**。缺堆栈、缺 `Caused by`、缺版本时，先列"还需要哪些信息"，
   不用泛泛而谈的建议填充。
8. **脱敏**。输出中不得出现明文密码、token、AK/SK、完整连接串凭据、身份证、手机号。
9. **中文输出**，技术名词保留英文原名（`NullPointerException`、`HikariCP`、`Metaspace`）。

## 6. 提交前自检

- [ ] 报告里出现的每个行号都能在原始日志中找到？
- [ ] 每个假设都配了验证步骤，而不是只给结论？
- [ ] 有没有出现白名单外的命令？有没有可一键执行的破坏性操作？
- [ ] `[事实]` / `[推测]` 是否逐条标注？
- [ ] 敏感信息是否已脱敏？占位符是否说明取值方式？
- [ ] 是否写清了"分析边界"（日志截断、脚本未运行、只分析了尾部 N 行）？

## 7. 失败与降级

| 情况 | 处理 |
| --- | --- |
| 日志只有一行异常，无堆栈 | 输出"结论：信息不足"，列出需要用户补充的 3 项（完整堆栈、框架/依赖版本、触发场景） |
| 脚本运行失败 | 手工解析，报告注明降级，置信度最高只给"中" |
| 根因在第三方库内部 | 给"绕行方案 + 升级/替换建议"，不下"库有 bug"的断论 |
| 用户要求直接改生产 | 拒绝执行，给出变更评审清单 |
