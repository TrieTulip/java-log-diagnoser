# examples：可复现的诊断样例

这里的每个示例都是**完整闭环**：一份可运行的原始日志、一份脚本真实产出、一份讲解、一份最终报告。
用途有两个——给人看"这个 Skill 输出长什么样"，给模型做 few-shot 对齐。

## 目录结构

```
examples/
├── README.md                              # 本文件：索引与复现方式
├── npe-in-commit-chain.md                 # 讲解：日志 → 抽取 → 分析中间产物
├── logs/
│   └── npe-in-commit-chain.log            # 原始日志（33 行，可直接喂脚本）
├── parsed/
│   └── npe-in-commit-chain.json           # parse_java_log.py 的真实输出
└── reports/
    └── npe-in-commit-chain.report.md      # 最终诊断报告成品
```

## 示例列表

| 示例 | 异常类型 | 考察点 | 讲解 | 报告 |
| --- | --- | --- | --- | --- |
| `npe-in-commit-chain` | `NullPointerException`（4 层 Caused by） | 主链选择、报错点与故障点分离、反证使用、日志截断边界 | [打开](npe-in-commit-chain.md) | [打开](reports/npe-in-commit-chain.report.md) |

## 复现方式

```bash
# 生成解析结果（与 parsed/ 下的文件应逐字段一致，generated_at 除外）
python3 scripts/parse_java_log.py \
  --file examples/logs/npe-in-commit-chain.log \
  --app-package com.acme --pretty

# 若只想看结论字段
python3 scripts/parse_java_log.py -f examples/logs/npe-in-commit-chain.log \
  --app-package com.acme --compact | python3 -c "import json,sys;print(json.load(sys.stdin)['summary'])"
```

`parsed/*.json` **由脚本生成，不要手工编辑**。若因日志或脚本改动需要更新，重跑上面的命令覆盖即可。

## 新增示例的清单

一个合格的示例应包含四样东西，缺一项就不算示例：

1. `logs/<name>.log`：能直接运行的真实形态日志，包含至少一处**噪声**（无关错误、正常请求或定时任务），
   用来检验"主链选择"是否可靠。
2. `parsed/<name>.json`：脚本真实输出，不允许手写。
3. `<name>.md`：场景说明 + 日志 + 关键字段节选 + Step 3 分析中间产物 + 本示例考察点。
4. `reports/<name>.report.md`：按 `prompts/generate_report.md` 的七节结构产出的成品报告。

另外请保证：

- 报告中每个 `L<行号>` 都能在 `logs/<name>.log` 里找到对应行；
- 至少有一个假设带**反证**或**已排除**说明，否则示例会教坏模型；
- 不出现真实公司名、内网 IP、账号口令，统一用 `com.acme`、`<HOST>`、`<PID>` 占位。

## 已覆盖 / 待补充

- 已覆盖：NPE（集合元素为 null）、多层包装异常、事务提交期触发、堆栈截断、第二条重复错误。
- 待补充：`OutOfMemoryError` 分型（heap / Metaspace / native thread）、依赖冲突（`NoSuchMethodError`）、
  连接类故障（`Connection refused` 与连接池耗尽的区分）、启动失败（`BeanCreationException` 链）。
