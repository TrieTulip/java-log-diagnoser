# java-log-diagnoser

把一段 Java 报错日志，变成一份**能直接照着做**的诊断报告。

它不是又一个"帮我看看这段报错"的提示词。它把诊断拆成四步：**脚本抽取事实 → 按需加载知识 → 形成假设 → 生成报告**，
并用硬约束压住大模型最容易犯的三个错误：编造行号、把外层异常当根因、推荐危险命令。

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
| 行号靠模型"脑补" | 行号只来自脚本输出的 `log_line`，报告里的 `L<数字>` 必须能在原文找到（CI 会校验） |
| 把 `BeanCreationException` 当根因 | `prompts/extract_root_cause.md` 明确把包装异常降级为"链路节点" |
| 建议 `kill -9` / 重启 | `references/safe-commands.md` 是白名单，破坏性操作只允许写成文字建议 |
| 知识塞满上下文，报告反而变水 | `references/` 按异常类型分节，Step 2 只加载命中的 1–3 节 |

## 目录结构

```
java-log-diagnoser/
├── SKILL.md                          # 骨架：触发条件、四步工作流、强约束
├── prompts/
│   ├── extract_root_cause.md         # Step 3：根因假设（输出结构化中间产物）
│   └── generate_report.md            # Step 4：七节报告结构与措辞规范
├── scripts/
│   ├── parse_java_log.py             # 事实抽取：Caused by 链 / OOM 分型 / 业务帧 / 信号
│   └── validate_skill.py             # 自检：结构完整性 + 行号不越界 + 示例可跑通
├── references/
│   ├── java-exceptions.md            # 9 类高频异常的 特征/排查/修复/误判
│   └── safe-commands.md              # 只读命令白名单 + 禁止清单
├── examples/
│   ├── README.md
│   ├── npe-in-commit-chain.md        # 完整样例：日志 → 抽取 → 分析中间产物
│   ├── logs/npe-in-commit-chain.log
│   ├── parsed/npe-in-commit-chain.json
│   └── reports/npe-in-commit-chain.report.md
├── docs/USAGE.zh-CN.md               # 从安装到使用的完整说明
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
产出 1–3 个假设并验证 → 生成七节报告。

完整输出效果见 [`examples/reports/npe-in-commit-chain.report.md`](examples/reports/npe-in-commit-chain.report.md)。

## 输出长什么样

| 章节 | 内容 |
| --- | --- |
| 1. 结论摘要 | 根因（含置信度）、影响面、建议动作，三行说完 |
| 2. 关键证据 | 表格，每条带 `L<行号>` 与 `[事实]` 标注 |
| 3. 根因假设 | H1–H3，含依据、反证、验证步骤、"若验证不成立转向 H?" |
| 4. 修复建议 | 止血（分钟级）/ 根治（天级，表格列改动点与风险） |
| 5. 排查命令 | 只读，带占位符与"期望观察" |
| 6. 分析边界 | 日志是否截断、脚本是否运行、未覆盖范围 |
| 7. 待确认 | 复选框，最多 5 条 |

## 自检

```bash
python3 scripts/validate_skill.py
```

校验内容：frontmatter 合法性、必需文件齐全、`references/` 锚点可解析、示例日志能被脚本解析、
报告中每个 `L<行号>` 不越界、无残留占位符。CI 中同样会跑（见 `.github/workflows/validate.yml`）。

## 设计原则

1. **骨架与知识分离**：`SKILL.md` 只有流程与约束，异常细节在 `references/`，按需加载。
2. **脚本优先**：能正则确定的事实（链、行号、OOM 分型）不交给模型推断。
3. **指令模板化**：分析阶段与写作阶段分离，避免"边分析边写报告"导致结论漂移。
4. **事实与推测分离**：`[事实]` 必须可指到日志行，`[推测]` 必须跟验证方法。
5. **只读边界**：给命令不给操作，破坏性动作只作为建议并标注风险。

## 兼容性

- 任何支持 Agent Skills（`SKILL.md` + 渐进式加载）的工具均可使用。
- 脚本需要 Python 3.8+；仅用 Skill 不跑脚本时无 Python 也能工作（会降级为手工解析，报告会标注）。
- 日志编码建议 UTF-8；脚本对非 UTF-8 使用 `errors="replace"` 容错。

## 许可证

[MIT](LICENSE)
