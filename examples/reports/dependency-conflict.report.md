# 诊断报告：NoSuchMethodError @ 启动期 Bean 初始化失败

> 日志来源：`examples/logs/dependency-conflict.log` · 分析行数：12（共 12 行） · 分析工具：java-log-diagnoser
> 主链：chain 0（L4–L12，3 层 Caused by） · 业务包：`com.acme`

## 1. 结论摘要

- **根因（置信度：高）**：运行期加载到的 `com.google.common.base.Preconditions` 中不存在
  编译期使用的方法签名（L10），属于**同一个类在不同版本间的方法差异**，不是类缺失。
- **影响面**：应用启动即失败，`orderFacade` 无法创建，全部依赖该 Bean 的功能不可用。
- **建议动作**：先按 §5 确认实际打包进制品的版本，再按 §4 处理；**在拿到版本前不要执行任何"升级"操作**。

## 2. 关键证据

| # | 日志行 | 证据 | 说明 |
| --- | --- | --- | --- |
| E1 | L10 | `NoSuchMethodError: 'void com.google.common.base.Preconditions.checkArgument(boolean, java.lang.String, java.lang.Object)'` | **[事实]** 缺失的是**方法**，且消息给出了完整签名：3 个参数、返回 void |
| E2 | L11 | `at com.acme.order.facade.OrderFacade.<init>(OrderFacade.java:34)` | **[事实]** 调用点：构造器中调用该方法；这是最深层 Caused by 里的业务代码 |
| E3 | L9 | `at com.acme.order.config.FacadeConfig.orderFacade(FacadeConfig.java:41)` | **[事实]** 装配点：由 `@Bean` 方法创建，说明是启动期而非请求期 |
| E4 | L4 | `BeanCreationException: Error creating bean with name 'orderFacade'` | **[事实]** 外层包装，只说明"哪个 Bean 失败"，不是根因 |
| E5 | L1 | `Starting OrderApplication v2.7.2 using Java 17.0.9` | **[事实]** 本次制品版本 v2.7.2；**日志未给出 guava 的任何版本号** |

## 3. 根因假设

### H1 运行期 guava 版本低于编译期，该重载尚不存在（置信度：高）

- **依据**：`[事实]` E1 的方法签名可对照 guava 各版本的 API；`[推测]` 该三参 `checkArgument` 属较新版本引入，
  旧版本只有 `checkArgument(boolean)` / `(boolean, Object)` 等重载。
- **反证**：未发现反证。若是 guava 完全没打进包，异常会是 `NoClassDefFoundError` / `ClassNotFoundException`，
  而不是 `NoSuchMethodError`（类已加载成功，只是方法对不上）。
- **验证步骤**：
  1. `unzip -l <app.jar> | grep -i guava` — 期望观察：`BOOT-INF/lib/guava-*.jar` 的版本号低于编译期版本；
  2. `mvn dependency:tree -Dincludes=com.google.guava:guava` — 期望观察：出现两个版本，或有 `omitted for conflict` 提示；
  3. `mvn dependency:tree -Dverbose | grep -i omitted` — 期望观察：能看到被 Maven 仲裁掉的另一个版本。
- **若验证不成立**（制品中版本正常）→ 转向 H2

### H2 依赖被 shade / relocation 或类加载器隔离，加载到了另一份同名类（置信度：中）

- **依据**：`[事实]` E1 显示类本身存在；`[推测]` 中间件 SDK 常自带 shaded guava，可能抢占同名包。
- **反证**：`[推测]` 若为 shade 冲突，报错类名通常带 relocation 前缀（如 `com.acme.shaded.google.common`），
  而 L10 是原始包名，倾向不支持该假设。
- **验证步骤**：
  1. `unzip -l <app.jar> | grep -i "guava\|shaded"` — 期望观察：存在多个包含该包名的 jar。
- **若验证不成立** → 转向 H3

### H3 编译产物与运行制品不一致（发布时打错包）（置信度：低）

- **依据**：`[事实]` L1 显示 v2.7.2；`[推测]` 灰度/回滚场景可能出现代码与依赖 jar 版本错配。
- **反证**：`[事实]` 日志无回滚、多版本并存痕迹，缺支撑。
- **验证步骤**：
  1. `unzip -l <app.jar> | grep -i "order-service"` — 期望观察：业务 jar 版本与制品版本一致。
- **若验证不成立** → 本次不采纳

## 4. 修复建议

### 4.1 止血（分钟级，风险低）

1. 回滚到上一个可用版本（v2.7.1）—— 预期效果：恢复启动；回滚方式：重新发布上一版制品。
   **属变更操作，需值班同学在变更窗口执行。**
2. 若确认是新引入的依赖传递导致，可先排除该传递依赖 —— **需在拿到 §5 的依赖树结果后执行，不要盲改**。

### 4.2 根治（天级）

| 改动点 | 具体做法 | 风险 |
| --- | --- | --- |
| `pom.xml` 的 `dependencyManagement` | 显式锁定 `com.google.guava:guava` 版本，与编译期一致 | 低 |
| 构建校验 | 引入 `maven-enforcer-plugin` 的 `dependencyConvergence`，构建期就暴露版本分歧 | 低；可能暴露一批历史遗留冲突，需分批修 |
| 依赖引入规范 | 三方 SDK 若自带 guava，显式 `<exclusions>` 排除，统一走主版本 | 中；需回归相关功能 |
| 启动自检 | 关键工具类的版本在启动日志打印，便于下次 30 秒定位 | 低 |

```xml
<!-- 示意，版本号以实际编译期依赖为准；本报告中日志未提供任何 guava 版本 -->
<dependencyManagement>
  <dependencies>
    <dependency>
      <groupId>com.google.guava</groupId>
      <artifactId>guava</artifactId>
      <version>${guava.version}</version>
    </dependency>
  </dependencies>
</dependencyManagement>
```

## 5. 建议执行的排查命令（只读）

| 目的 | 命令 | 说明 / 期望观察 |
| --- | --- | --- |
| 看制品里实际打进去的版本 | `unzip -l <app.jar> \| grep -i guava` | `<app.jar>` 为部署包路径；这是最直接的证据，优先级高于看 pom |
| 看依赖树里的版本分歧 | `mvn dependency:tree -Dincludes=com.google.guava:guava` | 在项目根目录执行；观察是否有多版本或 omitted |
| 看被仲裁掉的版本 | `mvn dependency:tree -Dverbose \| grep -i omitted` | 定位"谁把新版本压成了旧版本" |
| 确认方法在哪个版本存在 | `unzip -l <app.jar> \| grep -i "Preconditions.class"` | 只能确认类在，方法需结合版本 API 文档比对 |
| 确认运行时类来源 | `jcmd <PID> VM.system_properties \| grep -i classpath` | `<PID>` 由 `jps -l` 获取；确认是否有外部 classpath 注入 |

## 6. 分析边界与信息缺口

- 日志完整性：12 行全部参与分析，无截断。
- **关键缺口**：日志**没有**给出 guava 的版本号，也没有给出编译期依赖。因此本报告只断言"方法签名不匹配"，
  不断言"应该升到哪个版本"——任何具体版本号都必须由 §5 的命令确认后填写。
- 未覆盖：无 `pom.xml`、无制品清单、无构建日志。
- 脚本状态：已运行，`primary_signals=['version_conflict','spring_context']`。
- 外层 `BeanCreationException` / `BeanInstantiationException`（L4、L7）只是包装，均不作为根因。

## 7. 待确认

- [ ] 制品中实际存在的 guava 版本（`unzip -l` 结果）
- [ ] 编译期 pom 声明的 guava 版本
- [ ] 本次发布是否新增/升级过依赖
- [ ] 是否有三方 SDK 自带 guava（需 `dependency:tree` 确认）
