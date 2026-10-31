# 诊断报告：业务包信息缺失，无法定位具体代码行

> 日志来源：`examples/logs/no-business-frame.log` · 分析行数：11（共 11 行） · 分析工具：java-log-diagnoser
> 脚本结论：`chain_length=2`、`frame_count=5`、`has_business_frame=false`
> 降级原因：堆栈帧全部位于 `org.springframework.*`，指定根包 `com.acme` 后业务帧仍为 0

## 1. 已知

【业务包信息缺失，无法定位具体代码行】

- 异常：`org.springframework.beans.factory.NoSuchBeanDefinitionException`，消息为
  `No qualifying bean of type 'com.acme.order.client.StockClient' available …`（L9，**[事实]** 逐字引用）。
- 外层：`org.springframework.beans.factory.UnsatisfiedDependencyException`，指明注入点是
  名为 `orderController` 的 bean 的**构造参数 0**（L5，**[事实]**）。
- 阶段：健康检查端点已注册（L3，**[事实]**），说明配置装配已通过，失败发生在 bean 依赖解析阶段。
- 帧分布：5 个帧全部在 `org.springframework.beans.factory.support.*`（L6–L8、L10–L11，**[事实·脚本]**），
  没有一帧属于 `com.acme`。

## 2. 为什么不够

`NoSuchBeanDefinitionException` 能告诉我们"容器里没有 `StockClient` 类型的 bean"，
但**不能**告诉我们：`StockClient` 的实现类是否存在、是否在扫描路径内、是否被条件注解排除、
`OrderController` 的构造器到底声明了什么。

这些答案只在源码或业务堆栈里，而本次日志两者都没有——所有帧都在 Spring 内部。
按零假设红线，此时**不输出根因假设，也不输出修复建议**：无业务帧时写"某个类没加注解"，
就是把猜测包装成结论，会把排查引向错误方向。

## 3. 需要你补充（按优先级）

1. **应用根包名**：当前按 `com.acme` 解析仍无命中。若实际根包不同（如 `cn.acme`），
   请纠正后用 `--app-package` 重跑；若根包正确，则说明业务帧被日志配置裁掉了。
2. **`StockClient` 的实现类位置**：它是接口还是类？实现类是否有 `@Component` / `@Service`，
   或在某个 `@Configuration` 里用 `@Bean` 声明？所在包是否在启动类扫描范围之内？
3. **`OrderController` 的构造器声明**：构造参数 0 期望的类型与限定符（`@Qualifier`），
   以及是否存在多个候选实现。
4. **日志配置**：是否使用了裁剪堆栈的 pattern（自定义 converter、`%ex{short}`、只打 `e.getMessage()`）。

## 4. 你可以先做的只读检查

| 目的 | 命令 | 期望观察 |
| --- | --- | --- |
| 看 `StockClient` 有没有实现 | `grep -rn "StockClient" src/main/java` | 只有接口定义、没有实现类 → 符合"容器里没有该类型"；有实现类则转查注解与扫描范围 |
| 看扫描范围 | `grep -rn "@ComponentScan\|@SpringBootApplication" src/main/java/com/acme` | 启动类注解的 `scanBasePackages` 是否覆盖实现类所在包 |
| 确认是否每次都复现 | `grep -c "NoSuchBeanDefinitionException" </path/to/app.log>` | 每次启动都出现 → 配置/代码问题；偶发 → 再看是否有条件装配 |
| 确认 jar 里是否有该类 | `unzip -l <app.jar> \| grep -i "StockClient"` | 类存在但容器没有 → 扫描/注解问题；类不存在 → 打包问题 |

> 以上均为只读操作。改配置、发版、重启需在变更窗口由值班同学执行，本报告不提供变更命令。

## 5. 补充信息后我会怎么分析

1. 拿到业务帧或根包纠正后，先用脚本重跑，确认主链与最深业务帧；
2. 若最深 `Caused by` 仍是 `NoSuchBeanDefinitionException`，且实现类存在 → 查扫描范围、条件注解、多实现冲突；
3. 若实现类不存在 → 查模块依赖与打包配置（是否被 `provided`、是否漏了模块）；
4. 若 `OrderController` 的构造参数期望类型与实现类不一致 → 按类型不匹配处理，而不是笼统归为"缺 bean"。
