# 示例：信息不足——只有异常消息，没有堆栈

考察点：**降级分支**（`INSUFFICIENT_INFO`）、**不编造根因**、**把"缺什么信息"说得可执行**。

| 项目 | 路径 |
| --- | --- |
| 输入日志 | [`logs/insufficient-info.log`](logs/insufficient-info.log)（4 行） |
| 脚本输出 | [`parsed/insufficient-info.json`](parsed/insufficient-info.json)（脚本直接生成） |
| 最终报告 | [`reports/insufficient-info.report.md`](reports/insufficient-info.report.md)（降级模板，非七节） |

复现：

```bash
python3 scripts/parse_java_log.py --file examples/logs/insufficient-info.log --app-package com.acme --pretty
```

## 1. 场景

下单接口返回 500。日志只留了一行异常消息，堆栈被日志框架或采集链路吞掉了——这是线上最常见、
也最容易被"编一段看似专业的分析"糊弄过去的情况。

```
2026-11-01 09:12:03.551 ERROR ... 下单失败 orderId=SO20261101033
java.lang.IllegalStateException: 库存扣减返回失败码 STOCK_LOCK_FAIL
```

## 2. 脚本抽取结果

```json
{
  "summary": {
    "chain_count": 1, "chain_length": 1,
    "root_cause_type": "java.lang.IllegalStateException",
    "root_cause_message": "库存扣减返回失败码 STOCK_LOCK_FAIL",
    "root_cause_log_line": 3,
    "has_business_frame": false,
    "frame_count": 0
  },
  "business_frames": [],
  "first_business_frame": null,
  "root_business_frame": null,
  "signals": [],
  "warnings": ["异常只有消息、没有任何堆栈帧（at ...），无法定位代码行；请让用户提供完整堆栈后重跑。"]
}
```

**这条 warning 是本次分析的核心结论**：`frame_count=0` 意味着没有任何 `at` 行，脚本无从定位代码位置。
注意它与另一种情况不同——如果日志有帧但都不属于业务包，warning 会提示"用 `--app-package` 指定根包名重跑"；
本例给了 `--app-package` 也没用，因为根本没有帧。**这两种提示不能混用**，否则会让用户白跑一遍命令。

## 3. 为什么必须走降级分支

按 `prompts/extract_root_cause.md` 的规则，`root_cause_type` 不为 null 但链长为 1、无任何帧时，
**不能进入假设生成**，而应输出 `INSUFFICIENT_INFO`。理由是可验证性：

| 想写的结论 | 能否被日志支持 |
| --- | --- |
| "库存服务不可用" | 否。日志没有任何连接/超时异常 |
| "库存不足被包装成异常" | 否。`STOCK_LOCK_FAIL` 的语义在看代码或对接文档前是未知的 |
| "抛异常处缺少判空" | 否。连是哪个类抛的都不知道 |
| "需要完整堆栈才能继续" | 是。`frame_count=0` 可直接证实 |

前三条都属于"听起来合理"，但它们无法被任何验证步骤证实或推翻——正是 Skill 强约束第 5 条要禁止的。

## 4. Step 3.2：分析中间产物（降级）

```
INSUFFICIENT_INFO
reason: 异常只有消息没有堆栈（frame_count=0），无法定位抛出点与调用链
need:
- 完整堆栈：orderId=SO20261101033 或 traceId=9c1e77 对应的 ERROR 日志全段（含所有 at 与 Caused by）
- STOCK_LOCK_FAIL 的来源：库存服务返回码，还是本系统枚举？给出定义处或对接文档
- 库存扣减的调用方式与超时配置：同步 RPC / 消息 / 本地事务表
```

注意 `reason` 里引用的是脚本字段（`frame_count=0`），而不是"我觉得信息不够"这种主观判断。

## 5. Step 4.1：最终报告

见 [`reports/insufficient-info.report.md`](reports/insufficient-info.report.md)。它**没有**七节结构，
而是降级模板：已知 / 为什么不够 / 需要你补充 / 可以先做的只读检查 / 补充信息后怎么分析。

**没有"根因假设"和"修复建议"两节**——这是刻意的。没有证据的建议会直接把值班同学带偏方向。

## 6. 这个例子演示了什么

1. **降级不是失败**：输出"信息不足 + 需要什么"比输出三个 `low` 假设更有价值。
2. **warning 要分情况**："没有帧"和"有帧但不在业务包"是两种完全不同的处置，脚本必须区分措辞。
3. **字面量不猜测语义**：`STOCK_LOCK_FAIL` 只作为字符串引用，不说它代表"库存锁定失败"还是"锁冲突"。
4. **可执行的信息缺口**：每条补充项都具体到"哪个 traceId / 哪个字符串 / 哪个配置"，而不是"请提供更多日志"。

## 7. 反面示范

| 错误输出 | 问题 |
| --- | --- |
| "根因是库存服务返回 STOCK_LOCK_FAIL，说明库存锁定失败，建议重试" | 把字面量当语义，且"重试"是无依据的动作 |
| "IllegalStateException 表示状态非法，请检查代码逻辑" | 零信息量，读者看完仍不知改哪 |
| "建议补充日志后重试" | 把"补充信息"和"变更操作"混在一起 |
| "可能是网络问题导致库存扣减失败" | 日志无任何网络异常，纯猜测 |
