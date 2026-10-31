# 审查样例：npe-in-commit-chain（审查通过）

> **说明**：本文是 `prompts/validate_report.md` 的实际输出，用于对齐审查格式。
> 被审对象是 [`../reports/npe-in-commit-chain.report.md`](../reports/npe-in-commit-chain.report.md)，
> 输入为同一份日志与 `parsed/npe-in-commit-chain.json`。除本段说明外，以下内容即为可直接复用的审查结论。

---

审查对象：诊断报告：NullPointerException @ 订单详情查询 · 日志 33 行 · frame_count=7 · business_frames=7
【审查通过】

REVIEW: PASS
R1 幽灵事实：0 处（6 个类名、6 处源码位置、8 个 L 号、4 条命令全部回溯成功）
R2 绝对化措辞：0 处（全文无断言式/归因式/推断式黑名单词，置信度与证据强度匹配）
R3 信息缺口：满足（第 6 节 3 条，具体到"GC 日志""应用根包名""日志尾 N 行"，可直接执行）
R4 证据断裂：0 处（H1–H3 均写 `依据` 且引用 E1–E7，E 编号与 Step 3 一致，无孤立证据）
R5 结构：完整（七节齐全，E1–E7 编号连续，结论摘要三行）
R6 安全：无越界（4 条命令均为只读，PID/路径/主机全部占位并给了取值方式）
核查统计：类名/方法名 6 处、源码行号 6 处、L 号 8 处、命令 4 条，全部可回溯

---

**核查明细（供人工复核，不属于审查输出格式）**

| 对象 | 数量 | 核对于 | 结果 |
| --- | --- | --- | --- |
| 全限定类名 | 6 | L4–L8、L11–L24 的 `at` 帧与异常消息 | 全部命中 |
| 源码位置 `Xxx.java:nn` | 6 | 日志中同名帧逐字一致（`OrderAssembler.java:41/52`、`OrderController.java:64`、`OrderQueryService.java:110/118`、`OrderAuditListener.java:38`） | 全部命中 |
| 日志行号 `L<n>` | 8 | 33 行范围内、均非空行 | 全部命中 |
| 命令 | 4 | `references/safe-commands.md` 的 A/B 级只读项 | 全部在白名单 |
| 缩写还原 | 1 | `c.acme.order.OrderApplication` → 报告已注明"日志首行为缩写形式" | 放行（R1 例外条款） |

这次审查实际拦住过一处 R1：报告初稿在命令说明里写"主类为 `com.acme.order.OrderApplication`"，
而日志首行只有缩写形式 `c.acme.order.OrderApplication`。审查员按"缩写还原必须注明"的条款判为轻微 R1，
建议改成"主类名以 `OrderApplication` 结尾"——**展开包名是推断，不能当成日志原文**。
