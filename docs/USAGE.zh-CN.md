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

# ② 自检通过（18 项）
python3 .claude/skills/java-log-diagnoser/scripts/validate_skill.py

# ③ 脚本能跑示例
python3 .claude/skills/java-log-diagnoser/scripts/parse_java_log.py \
  --file .claude/skills/java-log-diagnoser/examples/logs/npe-in-commit-chain.log \
  --app-package com.acme --compact | head -c 300
```

第 ② 步输出 `结果：18 通过 / 0 失败` 即安装完整。

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
产出 1–3 个假设并给验证步骤 → 生成七节报告。

---

## 3. 怎么给输入效果最好

| 做法                          | 效果    | 原因                            |
| --------------------------- | ----- | ----------------------------- |
| 贴**完整 `Caused by` 链**       | ★★★★★ | 根因几乎总在最深一层，缺了就只能猜             |
| 同时给出**应用根包名**（如 `com.acme`） | ★★★★★ | 脚本靠它判断哪些帧是你的代码，直接决定定位精度       |
| 说明**发生时间 + 是否持续**           | ★★★★  | 决定是"数据问题"还是"资源问题"             |
| 只说"报错了，怎么办"                 | ★     | 没有堆栈，Skill 会直接告诉你信息不足，并列清单让你补 |
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

---

## 6. 常见问题

**Q1：工具里看不到这个 Skill？**  
先确认目录名是 `java-log-diagnoser`（不是 `java-log-diagnoser-main`，`git clone` 解压常带后缀）；  
再确认 `SKILL.md` 在目录**根**，不是嵌在子目录里；最后重启工具或重新加载窗口。

**Q2：提示找不到 `python3`？**  
Windows 上一般是 `python`；也可以让 Skill 跳过脚本——它会降级为手工解析，  
并在报告"分析边界"里注明"脚本未运行，行号未经校验"，此时置信度最高只到"中"。

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
| 新的示例   | `examples/` 下按四件套补齐（日志 + 真实解析 JSON + 讲解 + 报告）   | 行号必须能在日志里找到，CI 会校验                      |
| 调整报告结构 | `prompts/generate_report.md`                    | 同步改 `examples/reports/` 里的成品，否则不一致      |

改完必须跑：

```bash
python3 scripts/validate_skill.py
```

它会拦住三类最常见的破坏：锚点失效、行号越界、示例跑不通。

---

