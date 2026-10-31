# examples：可复现的诊断样例

这里的每个示例都是**完整闭环**：一份可运行的原始日志、一份脚本真实产出、一份讲解、一份最终报告。
用途有两个——给人看"这个 Skill 输出长什么样"，给模型做 few-shot 对齐。

`scripts/validate_skill.py` 会自动发现 `logs/*.log`，逐个要求四件套齐全，并**重跑脚本比对 `parsed/`**。
少写一份报告、或者手改过 JSON，CI 都会失败。

`reviews/` 下另有两份**审查样例**（Step 5 可选关卡的实际输出）：一份通过、一份打回，
用来对齐 `prompts/validate_report.md` 的判定格式。

## 目录结构

```
examples/
├── README.md                                  # 本文件：索引与复现方式
├── npe-in-commit-chain.md                     # 讲解：日志 → 抽取 → 分析中间产物
├── oom-heap-space.md
├── startup-port-in-use.md
├── dependency-conflict.md
├── insufficient-info.md
├── incomplete-log-refusal.md                  # 1 行 ERROR 文本，连异常都没有
├── no-business-frame.md
├── db-connection-timeout.md                   # 连接类：refused / timeout / unknown host 的分诊
├── logs/
│   ├── npe-in-commit-chain.log                # 33 行，四层 Caused by + 重复错误
│   ├── oom-heap-space.log                     # 20 行，含一条无关的超时链
│   ├── startup-port-in-use.log                # 15 行，启动失败
│   ├── dependency-conflict.log                # 12 行，NoSuchMethodError
│   ├── insufficient-info.log                  # 4 行，无堆栈
│   ├── incomplete-log-refusal.log             # 1 行，只有一句 ERROR 文本
│   ├── no-business-frame.log                  # 11 行，有帧但全在框架内
│   └── db-connection-timeout.log               # 30 行，连接获取超时 + 同期成功请求
├── parsed/                                    # 脚本输出，禁止手工编辑
│   └── <name>.json
├── reports/
│   └── <name>.report.md                       # 最终诊断报告成品
└── reviews/                                   # Step 5 审查样例（可选关卡）
    ├── npe-in-commit-chain.review.md          # 【审查通过】+ 核查统计
    └── dependency-conflict.review.md          # 【审查失败及修改意见】+ 打回表
```

## 示例列表

| 示例 | 异常类型 | 考察点 | 讲解 | 报告 |
| --- | --- | --- | --- | --- |
| `npe-in-commit-chain` | `NullPointerException`（4 层 Caused by） | 主链选择、报错点与故障点分离、日志截断边界 | [打开](npe-in-commit-chain.md) | [打开](reports/npe-in-commit-chain.report.md) |
| `oom-heap-space` | `OutOfMemoryError: Java heap space` | OOM 先分型、噪声链信号不可当证据、不轻易建议调堆 | [打开](oom-heap-space.md) | [打开](reports/oom-heap-space.report.md) |
| `startup-port-in-use` | `BindException`（3 层包装） | 外层包装异常不是根因、业务帧只是触发点 | [打开](startup-port-in-use.md) | [打开](reports/startup-port-in-use.report.md) |
| `dependency-conflict` | `NoSuchMethodError` | 方法缺失 ≠ 类缺失、无版本证据不写版本号 | [打开](dependency-conflict.md) | [打开](reports/dependency-conflict.report.md) |
| `insufficient-info` | `IllegalStateException`（无堆栈） | 降级分支：只输出信息缺口，不编造根因 | [打开](insufficient-info.md) | [打开](reports/insufficient-info.report.md) |
| `incomplete-log-refusal` | 无异常（`exception_count=0`，只有一行文本） | 零信息拒诊：关键词不是证据、三个补充问题必须能立刻动手 | [打开](incomplete-log-refusal.md) | [打开](reports/incomplete-log-refusal.report.md) |
| `no-business-frame` | `NoSuchBeanDefinitionException`，帧全在 Spring 内 | 零假设红线：无业务帧时必须输出【业务包信息缺失】，禁止猜代码行 | [打开](no-business-frame.md) | [打开](reports/no-business-frame.report.md) |
| `db-connection-timeout` | `SocketTimeoutException: connect timed out` | 连接类分诊（refused/timeout/unknown host）、获取连接失败≠慢 SQL、同期成功请求作反证 | [打开](db-connection-timeout.md) | [打开](reports/db-connection-timeout.report.md) |

## 审查样例（Step 5，可选关卡）

| 样例 | 判定 | 演示什么 | 打开 |
| --- | --- | --- | --- |
| `npe-in-commit-chain.review.md` | 【审查通过】 | 6 个类名 / 6 处源码位置 / 8 个 L 号的回溯统计；缩写名还原的放行条件 | [打开](reviews/npe-in-commit-chain.review.md) |
| `dependency-conflict.review.md` | 【审查失败及修改意见】 | 打回表怎么写：每项都指到原文一句，给类型（R1–R6）与替换示例；两轮不过则降级 | [打开](reviews/dependency-conflict.review.md) |

## 复现方式

```bash
# 生成解析结果（与 parsed/ 下的文件应逐字段一致，generated_at 除外）
python3 scripts/parse_java_log.py \
  --file examples/logs/npe-in-commit-chain.log \
  --app-package com.acme --pretty

# 校验快照是否与脚本当前输出一致（只读，不重写文件；不一致会列出字段差异）
python3 scripts/validate_skill.py --verbose

# 硬校验：成品报告里的类名/行号/证据原文是否真的在日志里（退出码 0 才算过）
python3 scripts/validate_diagnosis.py \
  --log examples/logs/npe-in-commit-chain.log \
  --report examples/reports/npe-in-commit-chain.report.md \
  --parsed examples/parsed/npe-in-commit-chain.json

# 若只想看结论字段
python3 scripts/parse_java_log.py -f examples/logs/oom-heap-space.log \
  --app-package com.acme --compact | python3 -c "import json,sys;print(json.load(sys.stdin)['summary'])"
```

`parsed/*.json` **由脚本生成，不要手工编辑**。脚本或日志改动后，重跑上面的命令覆盖，
否则 `validate_skill.py` 会报"快照与脚本当前输出不一致"。

## 新增示例的清单

一个合格的示例包含四样东西，缺一项校验就会失败：

1. `logs/<name>.log`：能直接运行的真实形态日志，**必须含至少一处噪声**（无关错误、正常请求或定时任务），
   用来检验"主链选择"是否可靠。日志统一用 `com.acme` 作为业务包。
   **拒诊类示例（`insufficient-info` / `incomplete-log-refusal`）除外**：它们的素材本身就是残缺的，
   加噪声等于伪造场景。
2. `parsed/<name>.json`：`--app-package com.acme --pretty` 的真实输出，不允许手写。
3. `<name>.md`：场景 + 日志 + 关键字段节选 + Step 3 分析中间产物 + 考察点 + 反面示范。
   Step 3 必须含**证据表**（`E<n> | L<n> | > 逐字原文`）、每条假设的 `- 引用:` 与推理链、
   以及八问自审表 + `SELF_CHECK: PASS / PASS_WITH_GAPS`（降级示例除外）。
4. `reports/<name>.report.md`：按 `prompts/generate_report.md` 的七节结构产出的成品；
   若示例本身演示降级，则用报告模板里的"信息不足"分支，且**不得**出现"根因假设/修复建议"两节。

另外请保证：

- 报告中每个 `L<行号>` 都指向 `logs/<name>.log` 里**真实且非空**的行（校验器会逐条核对）；
- 证据表的引用与日志**逐字一致**（只允许省略行首缩进、末尾用 `…` 截断），改一个字校验即失败；
- 每个 E 至少被一条假设或"已排除"引用；每条假设至少引用一条存在的 E；
- 报告中至少有一个假设带**反证**或**已排除**说明，否则示例会教坏模型；
- 命令表里不出现 `kill -9`、`rm -r`、`jmap -dump` 等变更/落盘操作；
- 不出现真实公司名、内网 IP、账号口令，统一用 `com.acme`、`<HOST>`、`<PID>` 占位；
- 新增示例后，回到本文件补一行索引（校验器会比对索引与实际文件）；
- 新增审查样例时：文件名用 `<name>.review.md`，判定行只能是 `【审查通过】` 或 `【审查失败及修改意见】`，
  并单独一行给 `REVIEW: PASS` / `REVIEW: FAIL`；通过样例必须带"核查统计"，打回样例必须带
  R1–R6 类型标注 + 修改意见 + 重写要求；
- 报告里出现的类名与 `Xxx.java:nn` 必须能在同一份日志或 `parsed/*.json` 中找到——
  这条从 R1 变成了 CI 检查，编一个"听起来很像项目里该有的"组件名会被直接拦下；
- 新增的成品报告要能通过 `scripts/validate_diagnosis.py`（退出码 0）：它还会核对证据引用是否逐字一致、
  `L<n>` 是否落空；"日志无 `X`""若是…会是 `Y`"这类否定/假设语气不会误判。

## 已覆盖 / 不覆盖

已覆盖：空指针（集合元素为 null）、多层包装异常、事务提交期触发、堆栈截断、重复错误、
OOM 分型（heap space）、启动期端口占用、依赖版本冲突（方法签名不匹配）、信息不足降级、
业务包信息缺失降级（有帧但无业务帧）、**残缺日志拒诊**（只有一行 ERROR 文本、`exception_count=0`）、
**连接类故障**（建连超时，报错点在 HTTP 入口、故障点在依赖边界，两者相距多层调用）。

不覆盖（不要在这些场景上宣称示例已覆盖）：

- `Metaspace` / `unable to create new native thread` 分型——排查方向与 heap 完全不同；
- 死锁与线程池耗尽（需要 `jstack` 输出，日志里通常只有现象）；
- 数据库死锁 / 慢 SQL（需要执行计划与锁等待信息）；
- 序列化与协议不兼容（`SerializationException`、Protobuf/Avro schema 演进）。
