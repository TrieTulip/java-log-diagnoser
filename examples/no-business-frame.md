# 示例：业务包信息缺失——只有框架帧，指不出代码行

考察点：**零假设红线**（红牌 2）、`NO_BUSINESS_FRAME` 降级分支、区分"有帧但不在业务包"与"根本没有帧"。

| 项目 | 路径 |
| --- | --- |
| 输入日志 | [`logs/no-business-frame.log`](logs/no-business-frame.log)（11 行） |
| 脚本输出 | [`parsed/no-business-frame.json`](parsed/no-business-frame.json)（脚本直接生成） |
| 最终报告 | [`reports/no-business-frame.report.md`](reports/no-business-frame.report.md)（降级模板，非七节） |

复现：

```bash
python3 scripts/parse_java_log.py --file examples/logs/no-business-frame.log --app-package com.acme --pretty
```

## 1. 场景

订单服务 v2.7.3 启动失败，日志里有完整的两层 `Caused by`、有 5 个堆栈帧，但**所有帧都在 `org.springframework.*`**。
业务代码被日志采集链路裁剪过，只剩框架帧。

这是最容易被"编一段像样分析"蒙过去的情况：异常类型明确、消息里有类名，看起来什么都够，
实际上**一个能指到源码行的证据都没有**。

```
Caused by: org.springframework.beans.factory.NoSuchBeanDefinitionException:
  No qualifying bean of type 'com.acme.order.client.StockClient' available: expected at least 1 bean ...
	at org.springframework.beans.factory.support.DefaultListableBeanFactory.raiseNoMatchingBeanFound(...)
```

## 2. 脚本抽取结果

```json
{
  "summary": {
    "chain_count": 1, "chain_length": 2,
    "root_cause_type": "org.springframework.beans.factory.NoSuchBeanDefinitionException",
    "root_cause_log_line": 9,
    "has_business_frame": false,
    "frame_count": 5,
    "primary_signals": ["spring_context"]
  },
  "business_frames": [],
  "first_business_frame": null,
  "root_business_frame": null,
  "warnings": [
    "已指定业务根包 com.acme，但日志中没有属于该包的堆栈帧：可能根包写错、业务帧被日志配置裁剪，或异常确实发生在框架内部。"
  ]
}
```

注意 `frame_count=5` 与 `business_frames=[]` 同时成立——**有帧，但没有一帧属于业务包**。
这与 `insufficient-info` 示例（`frame_count=0`）是两回事，脚本的 warning 措辞也不同：
本例不能再让用户"加 `--app-package`"，因为已经加了。

## 3. 为什么不能给代码行

| 想写的结论 | 能否被日志支持 |
| --- | --- |
| "`StockClient` 的实现类没加 `@Component`" | 否。日志没给任何业务帧，也没给源码 |
| "`OrderController.java:34` 的构造器注入失败" | 否。**这个行号日志里没有**，属于编造 |
| "缺 `com.acme.order.client.StockClient` 类型的 bean" | 是。异常消息原文就是这个意思 |
| "注入点是 `orderController` 的第 0 个构造参数" | 是。L5 原文可核对 |
| "需要业务帧或扫描配置才能继续" | 是。`business_frames=[]` 可直接证实 |

按红牌 2，此时只能输出固定的降级结构，**第一行必须是字面量**【业务包信息缺失，无法定位具体代码行】。

## 4. Step 3.2：分析中间产物（降级）

```
【业务包信息缺失，无法定位具体代码行】
NO_BUSINESS_FRAME
reason: 已解析到 1 条链（2 个节点，L5 / L9），但 5 个堆栈帧全部位于 org.springframework.*，
        指定根包 com.acme 后业务帧仍为 0，无法定位到业务代码行 [事实·脚本]
known_facts:
- [事实] L9 的异常是 NoSuchBeanDefinitionException，缺失的 bean 类型为 com.acme.order.client.StockClient（类型名来自异常消息，不来自堆栈帧）
- [事实] L5 显示注入点是名为 orderController 的 bean 的构造参数 0
- [事实] L3 显示健康检查端点已注册，配置装配阶段已通过，失败发生在 bean 依赖解析阶段
need:
- 确认应用根包（当前按 com.acme 解析）；若实际根包不同，纠正后重跑脚本
- OrderController 的构造器声明，以及 StockClient 的实现类位置（是否有 @Component / @Bean、是否在扫描路径内）
- 该模块的日志配置：是否裁剪了 com.acme 的堆栈帧（如自定义 converter、%ex{short}）
safe_checks:
- `grep -rn "StockClient" src/main/java` — 期望观察：只找到接口、没有实现类，或实现类不在启动类所在包之下
- `grep -rn "@ComponentScan\|@SpringBootApplication" src/main/java/com/acme` — 期望观察：扫描范围是否覆盖实现类所在包
- `grep -n "NoSuchBeanDefinitionException" </path/to/app.log>` — 期望观察：确认是否只有这一次，还是每次启动都复现
```

**没有"假设"章节，没有"修复建议"**——不是漏了，是红牌 2 明令禁止：
在没有任何业务帧的情况下写"某个方法没加注解"，就是把猜测包装成结论。

## 5. Step 4.1：最终报告

见 [`reports/no-business-frame.report.md`](reports/no-business-frame.report.md)。它使用降级模板：
标题即写明"业务包信息缺失"，第 1 节第一行是固定字面量，之后只有已知事实、缺口与只读检查，
**不含根因假设与修复建议**。

## 6. 这个例子演示了什么

1. **"有帧"不等于"能定位"**：`frame_count=5` 看起来信息很足，但业务帧为 0，结论只能停在组件层（Spring 容器）。
2. **零假设红线可执行**：不是"尽量别猜"，而是给出固定字面量与固定结构，让模型没有自由发挥的空间。
3. **类型名可用、行号不可用**：`com.acme.order.client.StockClient` 来自异常消息，可以引用；
   `OrderController.java:34` 日志里没有，不能写。两者的区别就是"原文有没有"。
4. **warning 要能区分场景**：已给根包却无命中时，再提示"请加 `--app-package`"会让用户白跑一遍。

## 7. 反面示范

| 错误输出 | 问题 |
| --- | --- |
| "根因是 StockClient 实现类没有加 `@Component`，建议补上注解" | 无业务帧、无源码，属于凭空猜测；注解是否存在日志里看不到 |
| "在 `OrderController.java:34` 的构造器注入处失败" | 行号是编的，日志里只有 `orderController` 这个 bean 名 |
| "这是 Spring 的 bug，建议升级版本" | 把框架当替罪羊，且没有任何版本证据 |
| "信息不足，请提供更多日志" | 空话；应具体到"根包名 / StockClient 实现类 / 日志配置" |
