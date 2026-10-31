# 使用说明：从下载到出报告

面向使用者的完整操作手册。全程 5 分钟，包含安装、第一次使用、读懂输出、常见问题。  
维护者请直接看第 10 节。

---

## 0. 前置条件

| 项目      | 要求                                                                   | 说明                          |
| ------- | -------------------------------------------------------------------- | --------------------------- |
| 编码工具    | Claude Code / Cursor / GitHub Copilot（VS Code）或其他支持 Agent Skills 的工具 | 需要支持 `SKILL.md` 这一约定        |
| Node.js | ≥ 18（仅方式一需要）                                                         | `npx` 随 Node 一起安装           |
| Python  | ≥ 3.8（推荐，非必须）                                                        | 脚本零第三方依赖；没有 Python 会降级为手工解析 |
| 网络      | 安装时需要；使用时可离线                                                         | 脚本不发任何网络请求                  |

检查环境：

```bash
node -v      # v18+ 即可
python3 -V   # 3.8+；Windows 上可能是 python -V
```

---

## 1. 安装

### 1.1 方式一：一键安装（推荐）

```bash
npx skills add <your-github-name>/java-log-diagnoser
```

执行后会进入交互式选择：

1. **选择目标工具**：Claude Code / Cursor / Copilot 等，可多选。
2. **选择作用域**：
   - **项目级**（写进当前仓库，随仓库共享）—— 适合团队统一；
   - **用户级**（写进家目录，所有项目可用）—— 适合个人常用。
3. 确认后，工具会把整个仓库（`SKILL.md` + `prompts/` + `scripts/` + `references/` + `examples/`）复制到  
   对应 skills 目录。

> CLI 的参数在不同版本间可能变化，若上面的命令报参数错误，先跑 `npx skills add --help` 看当前用法。  
> 也可以用完整地址：`npx skills add https://github.com/<your-github-name>/java-log-diagnoser`。

### 1.2 方式二：手动放置

```bash
git clone https://github.com/<your-github-name>/java-log-diagnoser.git
```

把**整个目录**复制到下表位置，目录名必须保持 `java-log-diagnoser`（`SKILL.md` 里的 `name` 与它一致）：

| 工具                      | 项目级                                       | 用户级                                    |
| ----------------------- | ----------------------------------------- | -------------------------------------- |
| Claude Code             | `<项目>/.claude/skills/java-log-diagnoser/` | `~/.claude/skills/java-log-diagnoser/` |
| Cursor                  | `<项目>/.cursor/skills/java-log-diagnoser/` | `~/.cursor/skills/java-log-diagnoser/` |
| GitHub Copilot（VS Code） | `<项目>/.github/skills/java-log-diagnoser/` | 以扩展当前文档为准                              |

```bash
# 例：装到当前仓库，供团队共享
mkdir -p .claude/skills
git clone https://github.com/<your-github-name>/java-log-diagnoser.git .claude/skills/java-log-diagnoser
```

各工具对 Agent Skills 的支持仍在演进，**路径以官方文档为准**；判断是否生效的标准只有一个：  
工具的技能列表里能看到 `java-log-diagnoser`，且描述包含触发关键词。

### 1.3 方式三：只用脚本（不装 Skill）

适合跳板机、离线环境、或只想拿结构化结果自己写报告：

```bash
python3 scripts/parse_java_log.py --file /var/log/order/app.log \
  --app-package com.yourcompany --pretty > parsed.json
```

脚本只读、零依赖、无网络。输出结构见第 4 节。

### 1.4 安装验证（三选一，建议全做）

```bash
# ① 目录结构完整
ls .claude/skills/java-log-diagnoser
#   应看到 SKILL.md  prompts  scripts  references  examples  README.md  LICENSE

# ② 自检通过（40 项）
python3 .claude/skills/java-log-diagnoser/scripts/validate_skill.py

# ③ 脚本能跑示例
python3 .claude/skills/java-log-diagnoser/scripts/parse_java_log.py \
  --file .claude/skills/java-log-diagnoser/examples/logs/npe-in-commit-chain.log \
  --app-package com.acme --compact | head -c 300
```

第 ② 步输出 `结果：40 通过 / 0 失败` 即安装完整。若有 FAIL，先看提示里的文件名与行号——
大概率是文件没复制全，或检出时被换行符改动（用 `.gitattributes` 已固定为 LF）。

---

## 2. 第一次使用

装上之后不需要记任何命令，直接用自然语言。三种最常用的开场：

**① 直接贴日志**

```
帮我分析这段日志：
org.springframework.transaction.TransactionSystemException: Could not commit JPA transaction
    at ...
Caused by: java.lang.NullPointerException: Cannot invoke "..." because "order" is null
    at com.acme.order.OrderService.calcTotal(OrderService.java:57)
```

**② 给文件路径**

```
/var/log/order/app.log 里 21:04 这个报错什么原因？只分析最后 2000 行。
```

**③ 给容器 / Pod**

```
order-svc-7d9f-xxx 这个 pod 一直在重启，帮我看看日志，定位下原因。
```

Skill 被触发后会依次做：预处理（判断日志类型、脱敏、找截断）→ 跑脚本 → 按信号加载知识 →  
产出 1–3 个假设并给验证步骤 → 生成七节报告 → **跑硬校验，类名/行号/引用都能对上日志才交付**。

---

## 3. 怎么给输入效果最好

| 做法                          | 效果    | 原因                            |
| --------------------------- | ----- | ----------------------------- |
| 贴**完整 `Caused by` 链**       | ★★★★★ | 根因几乎总在最深一层，缺了就只能猜             |
| 同时给出**应用根包名**（如 `com.acme`） | ★★★★★ | 脚本靠它判断哪些帧是你的代码，直接决定定位精度       |
| 说明**发生时间 + 是否持续**           | ★★★★  | 决定是"数据问题"还是"资源问题"             |
| 只说"报错了，怎么办"                 | ★     | 没有堆栈，Skill 会直接告诉你信息不足，并列清单让你补 |
| 只给一句 `ERROR - something went wrong` | ☆   | 连异常都没有，只能拒诊（见 `examples/incomplete-log-refusal.md`），补上堆栈才谈得上定位 |
| 贴几百行 INFO 日志                | ★★    | 会被截断分析，建议先 `grep -n` 定位到错误段   |

**关键提示**：告诉它你的应用包名，收益最大。可以在提问里直接写：

```
我们的根包是 com.acme，日志在 /tmp/app.log，帮我分析。
```

对应的就是脚本参数 `--app-package com.acme`。

---

## 4. 读懂输出

报告固定七节：

| 章节      | 你要看什么                                |
| ------- | ------------------------------------ |
| 1. 结论摘要 | 三行看完：根因、影响面、下一步动作。**值班时只看这一节也能动手**   |
| 2. 关键证据 | 每条带 `L<行号>`，可回到日志核对                  |
| 3. 根因假设 | H1–H3 按可能性排序，每条都有"验证步骤"和"若验证不成立转向哪条" |
| 4. 修复建议 | 4.1 止血（分钟级）、4.2 根治（天级，表格列风险）         |
| 5. 排查命令 | 只读命令，带 `<PID>` 占位符与"期望观察"            |
| 6. 分析边界 | 日志是否截断、脚本是否运行、哪些没覆盖                  |
| 7. 待确认  | 需要你补充的信息                             |

两个标注必须分清：

- `[事实]`：日志里能直接看到，行号可核对。
- `[推测]`：基于经验的推断，**后面一定跟一句验证方法**。没跟就是报告的 bug，可以直接怼它。

置信度三档：`高` = 直接证据 + 无反证；`中` = 需一步推导或上下文缺失；`低` = 仅模式匹配。  
**看到"低"就当线索，不要当结论。**

如果不想只看说明，直接对照成品（每个都含原始日志、脚本输出、成品报告，可跑通）：

| 你的场景 | 看这个 | 特别之处 |
| --- | --- | --- |
| 空指针，堆栈有好几层 `Caused by` | [`examples/npe-in-commit-chain.md`](../examples/npe-in-commit-chain.md) | 报错点与故障点分离、日志被 `... 27 more` 截断 |
| OOM / 被容器 kill | [`examples/oom-heap-space.md`](../examples/oom-heap-space.md) | 先分型；日志里还有一条**无关**的超时错误，演示怎么排除 |
| 启动失败、端口/配置问题 | [`examples/startup-port-in-use.md`](../examples/startup-port-in-use.md) | 外层 `ApplicationContextException` 不是根因 |
| `NoSuchMethodError` / 依赖冲突 | [`examples/dependency-conflict.md`](../examples/dependency-conflict.md) | 日志没给版本时，报告怎么写"需确认"而不编版本号 |
| 日志只有一行异常，没有堆栈 | [`examples/insufficient-info.md`](../examples/insufficient-info.md) | 降级分支：只给信息缺口与只读检查，**不给**根因假设 |
| 有堆栈但全是框架帧 | [`examples/no-business-frame.md`](../examples/no-business-frame.md) | 零假设红线：输出【业务包信息缺失】，禁止猜业务代码行 |

注意：报告里的 `L21` 指**日志第 21 行**，`OrderService.java:57` 指**源码第 57 行**，两者不是一回事。
混用会让排查方向直接跑偏。

---

## 5. 进阶用法

| 需求     | 说法                                          |
| ------ | ------------------------------------------- |
| 日志太大   | "只分析最后 5000 行"（对应 `--max-lines 5000`）       |
| 报告太长   | "给我 20 行的精简版，只要结论和下一步"                      |
| 只要命令   | "不用写报告，直接给我排查命令"                            |
| 存成文件   | "把报告存到 `diagnosis-20261031.md`"             |
| 对比两次故障 | 分别贴两段，要求"对比两次的差异"                           |
| 多个 Pod | "3 个副本里只有 `-7d9f` 这个报错，另外两个正常"（这类信息对定位极有价值） |

### 5.1 让报告再过一道审查（可选关卡）

报告是要发给别人、进工单、进复盘的时候，多一道把关值得。说一句就行：

```
这份报告帮我复核一下，重点查行号、类名和措辞
报告别急，先自己审一遍再发我
```

它会把 `prompts/validate_report.md` 当作审查员的指令，用**同一份日志**逐条核对报告，输出：

```
审查对象：诊断报告：NoSuchMethodError @ 启动期 Bean 初始化失败 · 日志 12 行
【审查失败及修改意见】

REVIEW: FAIL
R1 幽灵事实：1 处（GuavaVersionResolver 在日志与 JSON 中均无出处）
R2 绝对化措辞：2 处（肯定是、根本原因就是，均在 [推测] 段落内）
R3 信息缺口：不满足（缺第 6 节；日志未给 guava 版本）
...
| # | 章节/位置 | 类型 | 报告原文（摘录） | 为什么打回 | 修改意见 |
| 1 | 3. H1 依据 | R1 | `GuavaVersionResolver.check()` ... | 日志里没有这个类 | 删除或改成"需人工确认" |
```

三类必打回（其余还有 R4 证据断裂 / R5 结构缺失 / R6 安全越界）：

| 条件 | 说明 | 真实例子 |
| --- | --- | --- |
| R1 幽灵事实 | 类名、方法名、`Xxx.java:nn`、`L<n>`、版本号在日志与 `parsed.json` 里都找不到 | 编一个"听起来像项目里该有的"组件名，比编行号更难发现 |
| R2 绝对化措辞 | `肯定是`、`绝对是`、`根本原因就是`、`显然` 等；`[推测]` 段落里出现一律打回 | 结论方向可能没错，但语气超过了证据 |
| R3 缺"需补充的信息" | 无业务帧、日志截断、缺版本/GC/配置值时必须列出具体补充项 | 写"更多日志"不合格，要写"哪个文件 / 哪条命令 / 哪个字段" |

几点使用注意：

- **审查结论与报告分开放**。合并成一个文档后，就分不清哪句是诊断、哪句是自我评价。
- **审查员不改写报告**。它只给位置和修改方向，改由原流程改——否则改了什么没人复核。
- **最多两轮**。两轮不过就停止打磨，改用降级模板只给"已知事实 + 缺口"。反复润色一份证据不足的报告，只会让它更像真的。
- 预算紧、只是一次性问答，就别开这道关卡，省一轮往返。

样例见 [`examples/reviews/`](../examples/reviews/npe-in-commit-chain.review.md)：一份【审查通过】带核查统计，一份【审查失败及修改意见】带完整打回表。

### 5.2 让机器把幻觉拦下来（Step 4.2，必过）

审查关卡是"模型审模型"，仍可能漏；而且让审查员把注意力花在查字符串上，它就没有余力判断
"证据够不够支撑结论"。所以交付前还有一道**机器关卡**：把报告里的类名、`Foo.java:nn`、`L<n>`、
证据原文抽出来，逐条回原始日志比对，对不上就退出码 1。

**它默认就会跑**，不需要你说什么。想自己手工验一遍（或拿到别人给的报告时）：

```bash
python3 scripts/validate_diagnosis.py \
  --log app.log \
  --report diagnosis-20261031.md \
  --parsed parsed.json        # 可选；给了才能校验缩写类名与行号
# 退出码：0 通过 / 1 有错误 / 2 无法执行（文件缺失、日志为空）
```

通过时长这样：

```
✅ 校验通过：15 处源码位置、3 个异常类名、13 处 L 号、7 条证据引用、8 个类名，均可在日志中找到。
```

不通过时，每条错误都带报告行号和改法：

```
❌ V1 幽灵源码位置：OrderQueryService.java:999 在日志与 parsed.json 中都没有对应帧
   报告第 49 行：1. 查看 `OrderQueryService.java:999` 附近如何构建 `items`。
   修法：日志里 OrderQueryService.java 只出现于 :110、:118；改用真实帧，或删掉行号只写类名

共 1 处错误
⚠️ 校验失败，请 AI 重新生成报告（或按上面的「修法」逐条修正）。
```

五个检查项与处理方式：

| 编号 | 它发现什么 | 你该怎么做 |
| --- | --- | --- |
| V1 | `Foo.java:999` 在日志里没有这一帧 | 换成日志中真实存在的帧；只想指方向就删掉行号，只写类名 |
| V2 | 报告断言了一个日志里没有的异常 | 回日志确认；确实没有就删掉这句，或用降级模板 |
| V3 | `L99` 越界，或指向空行 | 改指到证据真正所在的行 |
| V4 | 证据表里的"原文"和日志那一行对不上 | 回日志复制，不要手动"改通顺"；截断处用 `…` |
| V5 | `com.acme.ghost.X` 这类类名日志里没有 | 删掉，或注明"日志中为缩写形式"后按缩写还原 |

参数：

| 参数 | 用途 |
| --- | --- |
| `--parsed parsed.json` | 第二来源。日志里类名常被缩写成 `c.a.o.c.X`，给了解析结果才能正确还原 |
| `--json` | 输出机器可读结果（含 `report_line`、`hint`），适合让 AI 自己按结果改 |
| `--quiet` | 通过时静默，适合放进 CI / 批量 |
| `--strict` | 把提示也当错误（想卡到"零提示"时用） |
| `--verbose` | 显示被跳过的否定/假设语境，以及每条提示的明细 |
| `--log -` | 从标准输入读日志：`kubectl logs <pod> \| python3 scripts/validate_diagnosis.py --log - --report r.md` |

**三种写法不会被误判**（它们本来就该出现在报告里）：

1. 排除项：`日志无 SQLException、HikariPool`——脚本按"否定语境"跳过，只记为提示；
2. 反事实：`若是依赖没打进包，异常会是 NoClassDefFoundError`——同上，不算断言；
3. JVM 参数：`-XX:+HeapDumpOnOutOfMemoryError`——识别为参数，不当成异常类名。

反过来，**同一个名字在一处被否定、另一处被当事实用，仍然会报错**——那才是真正要拦的。

---

## 6. 常见问题

**Q1：工具里看不到这个 Skill？**  
先确认目录名是 `java-log-diagnoser`（不是 `java-log-diagnoser-main`，`git clone` 解压常带后缀）；  
再确认 `SKILL.md` 在目录**根**，不是嵌在子目录里；最后重启工具或重新加载窗口。

**Q2：提示找不到 `python3`？**  
Windows 上一般是 `python`；也可以让 Skill 跳过脚本——它会降级为手工解析，  
并在报告"分析边界"里注明"脚本未运行，行号未经校验"（硬校验同样跑不了），此时置信度最高只到"中"。

**Q3：日志几十万行，贴不进去？**

|                                |                             |
| ------------------------------ | --------------------------- |
| 先用 \`grep -n "<异常关键字>" app.log | tail -50\` 定位，再贴错误段前后 50 行。 |
| 或者直接给文件路径 + "只分析最后 5000 行"。    |                             |

**Q4：中文乱码？**  
脚本按 UTF-8 读取，非法字节用替换符容错。若日志是 GBK，先转码：  
`iconv -f GBK -t UTF-8 app.log > app.utf8.log`。

**Q5：报告里的行号和我看到的不一致？**  
大概率是日志被裁剪过（比如你只贴了中间一段）。报告的行号对应**你提供的文本**的物理行号。  
让它重新核对："按我贴的这段重新数行号。"

**Q6：它为什么不肯给我 `kill -9` / 重启命令？**  
设计如此。破坏性操作只写成文字建议并标注风险，由你决定是否执行。  
这是为了避免"AI 建议重启"掩盖真实根因。

**Q7：能分析 k8s 里的日志吗？**  
可以。给它 pod 名，它会用 `kubectl logs --tail` 拿日志，并用 `kubectl describe` 看 `OOMKilled`、退出码 137 等信号。

**Q8：会不会把日志发到网上？**  
脚本不发任何网络请求，只在本地跑。但**对话本身**由你使用的模型服务处理——  
生产日志请先脱敏（账号、连接串、身份证、手机号），这是使用任何 AI 工具的前提。

**Q9：硬校验报错，但我确认报告是对的？**  
先按"修法"那行看具体是哪一句。常见的三类可解释情况：

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| 报某个异常在日志里找不到 | 它出现在"排除项"或"反事实"之外的句子里 | 改成否定句（"日志未出现 X"），或补上它真正出现的行 |
| 报某个类名找不到 | 日志里是缩写 `c.a.o.c.X`，你没给 `--parsed`，或段数不一致 | 补 `--parsed parsed.json`，并注明"日志中为缩写形式" |
| 报代码块里的行号找不到 | 那段是示意代码 | 在块内写 `// 示意，行号与变量名以实际代码为准` |

**不要为了过检去放宽脚本规则**。如果一条结论只能靠"日志里没有的名字"支撑，
问题在结论本身，不在校验器。另外它只查"名字在不在"，不判断"证据够不够"——后者是 5.1 的事。

---

## 7. 安全边界

- 脚本：只读本地文件/标准输入，不写文件、不发请求。
- 报告中的命令：限定在 `references/safe-commands.md` 白名单（`jps`/`jstack`/`jstat`/`df`/`ss`/`grep`/`SELECT` 等）。
- 明确禁止：`kill`、重启、`jmap -dump` 落盘、`DROP/TRUNCATE/UPDATE`、`rm`、清缓存、生产压测。
- 输出脱敏：密码、token、AK/SK、连接串凭据、手机号、身份证替换为 `<REDACTED>`。

---

## 8. 升级与卸载

**升级**（用户级安装示例）：

```bash
rm -rf ~/.claude/skills/java-log-diagnoser
npx skills add <your-github-name>/java-log-diagnoser
```

或手动 `git pull`（若是 clone 安装）：

```bash
cd .claude/skills/java-log-diagnoser && git pull
```

升级后建议重跑 `python3 scripts/validate_skill.py` 确认结构完整。

**卸载**：删除该目录即可，不写注册表、不装全局依赖、不改任何配置。

---

## 9. 自己扩展

| 想加什么   | 改哪里                                             | 注意                                      |
| ------ | ----------------------------------------------- | --------------------------------------- |
| 新的异常类型 | `references/java-exceptions.md` 新增一节，并在开头目录表加锚点 | 用 `<a id="xxx"></a>` 定义锚点，才能被 `#xxx` 引用 |
| 新的识别信号 | `scripts/parse_java_log.py` 的 `SIGNAL_RULES`    | 同步在知识库加对应章节，否则信号指向空                     |
| 新的只读命令 | `references/safe-commands.md`                   | 必须标风险等级 A/B/C                           |
| 新的示例   | `examples/` 下按四件套补齐（日志 + 真实解析 JSON + 讲解 + 报告）   | 新增后回填 `examples/README.md` 索引；行号必须指向真实非空行 |
| 调整报告结构 | `prompts/generate_report.md`                    | 同步改 `examples/reports/` 里的成品，否则校验器会报结构缺失 |
| 调整红线或拒诊标记 | `SKILL.md` §0 + 两份 prompts + 降级示例报告     | 四处必须同口径；`validate_skill.py` 的 `DEGRADED_BANNER` 与两个脚本的 `DEGRADED_MARKS` 要一起改，否则自检直接红 |
| 调整审查条件 | `prompts/validate_report.md` 的 R1–R6 | 同步改 `examples/reviews/` 的样例与 `validate_skill.py` 的 `GATE_TOKENS` |
| 新增审查样例 | `examples/reviews/<name>.review.md` | 判定行与 `REVIEW:` 行必须一致；通过样例要带核查统计 |

改完必须跑：

```bash
python3 scripts/validate_skill.py            # 40 项，全绿才算改完
python3 scripts/mutation_test.py             # 23 例变异，确认检查还抓得住错
python3 scripts/validate_skill.py --verbose  # 失败时看差异细节
```

改了报告结构或示例后，还要单独确认硬校验仍能过（它也是 CI 里独立的一步）：

```bash
for log in examples/logs/*.log; do
  n="$(basename "$log" .log)"
  python3 scripts/validate_diagnosis.py --log "$log" \
    --report "examples/reports/$n.report.md" --parsed "examples/parsed/$n.json" --quiet || exit 1
done
```

它会拦住这些破坏（不止"文件在不在"）：

- **锚点**：`references/<文件名>.md#<锚点>` 指向的小节不存在，或锚点后面没跟标题；
- **快照**：手改过 `examples/parsed/*.json`，或改了脚本却没重新生成快照（逐字段比对，忽略时间戳）；
- **行号**：`L<n>` 越界、指向空行，或 `root_cause_log_line` 那行其实不含该异常；
- **结构**：报告缺章节、降级报告里混进"根因假设"、假设没写反证；
- **安全**：命令表或代码块里出现 `kill -9`、`jmap -dump`、`rm -r`；
- **字段**：文档里引用了一个不存在的 `summary.<字段名>`；
- **幻觉**：报告里的类名、`Foo.java:nn`、`L<n>`、证据原文对不上日志——由 `validate_diagnosis.py` 拦截，退出码 1。

---

