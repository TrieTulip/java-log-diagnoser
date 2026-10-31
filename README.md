# java-log-diagnoser

把一段 Java 报错日志，变成一份**能直接照着做**的诊断报告。

它不是又一个"帮我看看这段报错"的提示词。它把诊断拆成五步：**预处理 → 脚本抽取事实 →
结合模板分析（加载知识 + 形成假设）→ 生成报告并跑机器硬校验**，需要时再加一道可选的
**换个身份把报告审一遍**。三条绝对红线压住大模型最容易犯的三个错误：编造类名与行号、
把推测当事实、信息不足时硬编根因。

```
输入：一段 Java 堆栈（粘贴 / 文件 / 容器日志）
输出：结论摘要 + 带行号的证据表 + 1~3 个根因假设（含验证步骤）+ 止血/根治建议 + 只读命令清单
```

## 为什么需要它

直接把日志丢给模型，常见产出是"NullPointerException 表示空指针，建议检查对象是否为空"——
没有信息量。真正难的是：

| 难点 | 本项目的处理 |
| --- | --- |
| 四层 `Caused by`，根因在最里面 | `scripts/parse_java_log.py` 用正则还原完整链，输出 `root_cause_type` 与最深业务帧 |
| 行号靠模型"脑补" | 行号只来自脚本输出的 `log_line`；报告里的 `L<数字>` 必须指向**真实且非空**的行（CI 逐条核对） |
| 把 `BeanCreationException` 当根因 | `prompts/extract_root_cause.md` 明确把包装异常降级为"链路节点" |
| 拿日志里无关错误的特征当根因 | 每条信号带 `in_primary_chain`，只有落在主链的才能支撑结论 |
| 结论与证据对不上号 | Step 3 强制"证据表 → 假设"闭环：每条结论挂 E 编号，E 编号背后是逐字原文 |
| 报告里的类名/行号是编的，但读起来毫无破绽 | `scripts/validate_diagnosis.py` 逐条回日志比对，对不上**退出码 1**——不是"提醒"，是拦截 |
| 日志信息不足，却硬凑三个"低置信度假设" | R3 红线：第一行必须是【信息不足，拒绝盲目诊断】+ 3 个具体补充问题，`validate_skill.py` 会检查降级模板 |
| 写报告的人不肯挑自己的错 | Step 5（可选）切换到审查员身份：只判定、只定位、不重写，按 R1–R6 打回 |
| "肯定是""根本原因就是"这类断言 | R2 黑名单 + CI 扫描；`[推测]` 段落里出现强断言直接打回 |
| 建议 `kill -9` / 重启 | `references/safe-commands.md` 是白名单；CI 会扫描命令表与代码块，出现即失败 |
| 知识塞满上下文，报告反而变水 | `references/` 按异常类型分节，Step 3.1 只加载命中的 1–3 节 |

## 目录结构

```
java-log-diagnoser/
├── SKILL.md                          # 骨架：三条红线、五步工作流（第 5 步可选）、强约束
├── prompts/
│   ├── extract_root_cause.md         # Step 3.2：证据链闭环 + 根因假设 + 八问自审（中间产物）
│   ├── generate_report.md            # Step 4.1：七节报告结构与措辞规范
│   └── validate_report.md            # Step 5（可选）：审查员视角，R1–R6 打回条件
├── scripts/
│   ├── parse_java_log.py             # 事实抽取：Caused by 链 / OOM 分型 / 业务帧 / 信号归属
│   ├── validate_diagnosis.py         # 硬校验：报告里的类名/行号/证据原文是否真的在日志里
│   ├── validate_skill.py             # 自检：40 项，含红线位置、流程门禁、证据引用核对
│   └── mutation_test.py              # 变异测试：注入 23 类缺陷，证明自检真的会红
├── references/
│   ├── java-exceptions.md            # 9 类高频异常的 特征/排查/修复/误判
│   └── safe-commands.md              # 只读命令白名单 + 禁止清单
├── examples/                         # 8 个完整示例，每个都是 日志+parsed+讲解+报告
│   ├── README.md
│   ├── npe-in-commit-chain.md        # NPE，4 层 Caused by，含重复错误与截断
│   ├── oom-heap-space.md             # OOM heap space，含无关的超时噪声链
│   ├── startup-port-in-use.md        # 启动失败，端口占用
│   ├── dependency-conflict.md        # NoSuchMethodError，依赖版本冲突
│   ├── insufficient-info.md          # 无堆栈，演示降级分支
│   ├── no-business-frame.md          # 有帧但无业务帧，演示零假设红线
│   ├── logs/*.log
│   ├── parsed/*.json                 # 脚本真实输出，禁止手工编辑
│   ├── reports/*.report.md           # 成品报告
│   └── reviews/*.review.md           # 审查样例：一份通过、一份打回
├── docs/USAGE.zh-CN.md               # 从安装到使用的完整说明
├── .github/workflows/validate.yml    # CI：Python 3.9 与 3.12 双版本
├── LICENSE
└── README.md
```

## 安装

### 方式一：一键安装到编码工具（推荐）

```bash
npx skills add <your-github-name>/java-log-diagnoser
```

按提示选择目标工具（Claude Code / Cursor / Copilot 等）与作用域（项目级或用户级）。
命令会读取仓库根目录的 `SKILL.md` 作为入口。若你的 CLI 版本参数不同，以 `npx skills add --help` 为准。

### 方式二：手动放置

把整个目录放到对应工具的 skills 目录下，目录名保持 `java-log-diagnoser`：

| 工具 | 项目级 | 用户级 |
| --- | --- | --- |
| Claude Code | `.claude/skills/java-log-diagnoser/` | `~/.claude/skills/java-log-diagnoser/` |
| Cursor | `.cursor/skills/java-log-diagnoser/` | `~/.cursor/skills/java-log-diagnoser/` |
| GitHub Copilot（VS Code） | `.github/skills/java-log-diagnoser/` | 以扩展当前文档为准 |

各工具对 Agent Skills 的支持仍在演进，路径以官方文档为准；判断是否生效的标准只有一个：
**工具能在技能列表里看到 `java-log-diagnoser`，且描述里包含触发关键词。**

### 方式三：只用脚本，不装 Skill

脚本零依赖、纯标准库，可单独在跳板机上跑：

```bash
python3 scripts/parse_java_log.py --file app.log --app-package com.yourcompany --pretty
```

## 使用

装好后直接用自然语言触发，不需要记命令：

```
帮我分析这段日志：<粘贴堆栈>
```

```
app.log 里这个报错什么原因？文件在 /var/log/order/app.log
```

```
订单服务一直在报 HikariPool 超时，pod 叫 order-svc-7d9f-xxx，帮我定位
```

Skill 会依次执行：预处理（判断日志类型、脱敏、找截断）→ 跑脚本 → 按信号加载知识 →
产出 1–3 个假设并验证 → 生成七节报告 → **跑硬校验，通过才交付**。

需要第二道把关时说一句"再复核一下"，它会用 `prompts/validate_report.md` 另起一轮审查：

```
这份报告帮我复核一下，行号、类名、措辞都过一遍
```

审查结论是**独立的一段**，形如 `【审查通过】` 或 `【审查失败及修改意见】`，附 `REVIEW: PASS / FAIL`，
不会与报告正文混在一起——改了什么、谁改的、改得对不对，必须能追溯。

完整输出效果见 [`examples/`](examples/README.md)：七个场景各有一份成品报告，其中
[`insufficient-info`](examples/reports/insufficient-info.report.md) 演示"有异常但没堆栈时只输出缺口、不给建议"，
[`incomplete-log-refusal`](examples/reports/incomplete-log-refusal.report.md) 演示更极端的"日志只有一句话"——
连异常都没有，报告里就不许把任何异常类名当成事实，
[`reviews/`](examples/reviews/npe-in-commit-chain.review.md) 演示审查关卡通过与打回两种输出。

## 硬校验：把"不许编造"变成一个退出码

`prompts/` 里的约束是文字，文字拦不住模型。所以交付前还有一道机器关卡：
报告里的**类名、`Foo.java:nn`、`L<n>`、证据原文**，逐条回原始日志做字符串级核对，对不上就退出码 1。

```bash
python3 scripts/validate_diagnosis.py \
  --log examples/logs/npe-in-commit-chain.log \
  --report examples/reports/npe-in-commit-chain.report.md \
  --parsed examples/parsed/npe-in-commit-chain.json
# 退出码：0 通过 / 1 有错误 / 2 无法执行（文件缺失、日志为空）
```

| 编号 | 查什么 | 典型幻觉 |
| --- | --- | --- |
| V1 | `Foo.java:52` 在日志里有同名同号的帧 | 把 `:110` 记成 `:999`、把 `:41-60` 的终点当帧号 |
| V2 | 断言提到的异常真实存在 | "本次由 `CacheMissException` 引起"，日志里根本没这个异常 |
| V3 | `L<n>` 在范围内且非空 | 凭印象写 `L42`，日志只有 33 行 |
| V4 | 证据表里的原文与本行逐字一致 | 把堆栈"顺手改通顺"，或拼接两行当一条证据 |
| V5 | `com.x.Y` 能在日志里找到 | 编一个 `com.acme.order.ghost.GhostResolver` |

失败时它不只报错，还给出改法（下面是真实输出，注入了 `:999` 与一个不存在的类名）：

```
❌ V1 幽灵源码位置：OrderQueryService.java:999 在日志与 parsed.json 中都没有对应帧
   报告第 49 行：1. 查看 `OrderQueryService.java:999` 附近如何构建 `items`。
   修法：日志里 OrderQueryService.java 只出现于 :110、:118；改用真实帧，或删掉行号只写类名

共 1 处错误
⚠️ 校验失败，请 AI 重新生成报告（或按上面的「修法」逐条修正）。
```

**难点不在正则，在语境。** 朴素写法 `if "Foo.java:52" not in log: error` 在真实报告上会误杀：

| 陷阱 | 例子 | 本脚本的处理 |
| --- | --- | --- |
| 否定语境 | "日志无 `SQLException`、`HikariPool`" | 判为已排除，只记提示（`--verbose` 可见） |
| 反事实 | "若是依赖没打进包，异常会是 `NoClassDefFoundError`" | 同上，不当作断言 |
| JVM 参数 | "`-XX:+HeapDumpOnOutOfMemoryError`" | 识别为参数而非异常类名 |
| Spring 缩写 | 日志 `c.a.o.c.OrderController` → 报告 `com.acme.order.controller.OrderController` | 段数相同 + 每段前缀匹配即放行，并可按需注明缩写 |
| 省略引用 | `` `at …OrderAssembler.toDetail(OrderAssembler.java:52)` `` | 按 `…` 拆片段，每段都要能在原文中找到 |

把 20 行的朴素版原样跑在本仓库 8 份示例上：`npe-in-commit-chain` 报 2 条**误报**（"日志无 `OutOfMemoryError`"
被判成幻觉），另外 3 份因为正文出现"推测"二字，异常检查被 `and "推测" not in report` 整条跳过。
一个会误杀、又能被一句话关闭的检查，比没有更危险——它给人"已经校验过"的错觉。

供 AI 自纠时用 `--json`（机器可读，含每条错误的 `report_line` / `hint`）、
CI 里用 `--quiet`、想把提示也当错误用 `--strict`。多份报告可循环调用：

```bash
for n in examples/logs/*.log; do
  python3 scripts/validate_diagnosis.py --log "$n" \
    --report "examples/reports/$(basename "$n" .log).report.md" --quiet || exit 1
done
```

## 输出长什么样

| 章节 | 内容 |
| --- | --- |
| 1. 结论摘要 | 根因（含置信度）、影响面、建议动作，三行说完 |
| 2. 关键证据 | 表格，每条带 `L<行号>`、逐字原文与 `[事实]` 标注，编号沿用 Step 3 的 E |
| 3. 根因假设 | H1–H3，依据只许引用 E 编号，含反证、验证步骤、"若验证不成立转向 H?" |
| 4. 修复建议 | 止血（分钟级）/ 根治（天级，表格列改动点与风险） |
| 5. 排查命令 | 只读，带占位符与"期望观察" |
| 6. 分析边界 | 日志是否截断、脚本是否运行、未覆盖范围 |
| 7. 待确认 | 复选框，最多 5 条 |

另有一份独立的审查结论（可选）：`【审查通过】` / `【审查失败及修改意见】` + R1–R6 分项 + 打回表。

## 自检

```bash
python3 scripts/validate_skill.py            # 40 项
python3 scripts/validate_skill.py --verbose  # 失败时输出差异细节
python3 scripts/mutation_test.py             # 23 类变异，验证"检查真的会失败"
```

自检不只看"文件在不在"，而是检查**内容对不对得上**：

- **红线在开头**：`SKILL.md` 的 R1–R3 必须排在"何时使用"之前，删掉或挪到文末都会 FAIL；
- **流程没漏步**：工作流必须保持"预处理 → 脚本解析 → 模板分析 → 输出与拦截"的顺序，
  Step 4 内必须同时出现 `validate_diagnosis.py`、退出码要求与"改后重跑"；
- **拒诊口径一致**：`【信息不足，拒绝盲目诊断】` 必须同时出现在 `SKILL.md`、两份 prompts 与至少一份示例报告中；
- **示例四件套**：自动发现 `examples/logs/*.log`，每个都必须有讲解、`parsed/` 快照、成品报告；
- **快照可复现**：重跑脚本与 `parsed/*.json` 逐字段比对（忽略时间戳），手改过的 JSON 会被抓出来；
- **行号真实**：`L<n>` 必须指向日志里**真实且非空**的那一行，不只是"不越界"；
- **结论可核对**：`root_cause_log_line` 指向的行必须真的包含该异常类型；
- **字段存在**：文档里写的 `summary.<字段名>` 必须在真实输出中存在，防止模型照抄不存在的字段；
- **报告结构**：七节齐全（降级示例则检查降级模板，且不得出现"根因假设/修复建议"）；
- **危险命令**：命令表与代码块里出现 `kill -9`、`jmap -dump`、`rm -r` 等即失败；
- **索引一致**：`examples/README.md` 列出的示例与实际文件双向一致；
- **证据逐字可核**：示例里每条 `E<n> | L<n> | > 原文` 必须与日志该行完全一致，改一个字就失败；
- **假设闭环**：每条 H 必须写 `- 引用: E<n>` 且编号存在，每个 E 必须被引用，否则判为孤立证据；
- **自审到位**：示例必须有八问自审表与 `SELF_CHECK: PASS / PASS_WITH_GAPS`；
- **编号一致**：报告证据表的 E 编号必须是 Step 3 定义过的，防止各处各编一套；
- **类名可回溯**（R1）：报告里出现的每个全限定类名、每处 `Xxx.java:nn`，必须能在同一份日志或 `parsed/*.json` 中找到；
- **硬校验跑得通**（F）：以子进程真实执行 `validate_diagnosis.py`，每份成品报告都必须退出码 0——
  文档里写的命令和用户实际能跑的命令不能是两回事；
- **无绝对化断言**（R2）：报告与 Step 3 输出不得出现"肯定是/根本原因就是/显然是"，除非同行有 `[事实]` 与出处；
- **审查样例自洽**：判定行与 `REVIEW:` 行必须一致，通过样例要有核查统计，打回样例要带 R1–R6 与修改意见。

这套检查带**变异测试**（`scripts/mutation_test.py`，已接入 CI）：复制仓库到临时目录，注入 23 类缺陷
（手改快照、越界行号、删章节、混入 `kill -9`、写不存在的字段名、缺报告、篡改引用一个字、
引用不存在的 E、删自审表、编一个不存在的类名、写"肯定是"、判定行与 REVIEW 不一致、删审查样例，
5 类报告侧幻觉：编造 `:999`、断言日志没有的异常、改掉证据里的方法名、写越界 `L99`、编造全限定类名，
以及 5 类"规则漂移"：删掉红线章节、把红线挪到文末、删掉 Step 4.2 硬校验、改掉 prompts 里的拒诊标记、
把报错点退回帧顶导致 HTTP 入口被认成 DAO），
逐例断言"退出码为 1 且失败信息正是预期那条"——23/23 被捕获。CI 在 Python 3.9 与 3.12 上双版本运行。

其中"编一个不存在的类名"这条是加审查关卡时被自己抓到的：`npe-in-commit-chain` 报告里曾写
"主类为 `com.acme.order.OrderApplication`"，而日志首行只有缩写形式 `c.acme.order.OrderApplication`。
现在这类问题会在 CI 里直接失败。

## 设计原则

1. **骨架与知识分离**：`SKILL.md` 只有流程与约束，异常细节在 `references/`，按需加载。
2. **脚本优先**：能正则确定的事实（链、行号、OOM 分型）不交给模型推断。
3. **指令模板化**：分析阶段与写作阶段分离，避免"边分析边写报告"导致结论漂移。
4. **事实与推测分离**：`[事实]` 必须可指到日志行，`[推测]` 必须跟验证方法。
5. **只读边界**：给命令不给操作，破坏性动作只作为建议并标注风险。
6. **审查与创作分离**：审查员只判定、只定位，不重写正文；两轮不过就降级，不无限打磨。
7. **能机械校验的，不靠自觉**：把"不许编造"落成退出码——类名、行号、证据原文逐字比对，
   再用变异测试证明这些检查真的会红，而不是永远打印 OK。

## 兼容性

- 任何支持 Agent Skills（`SKILL.md` + 渐进式加载）的工具均可使用。
- 脚本需要 Python 3.8+；仅用 Skill 不跑脚本时无 Python 也能工作（会降级为手工解析，报告会标注）。
- 日志编码建议 UTF-8；脚本对非 UTF-8 使用 `errors="replace"` 容错。

## 许可证

[MIT](LICENSE)
