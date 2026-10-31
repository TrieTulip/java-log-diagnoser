# Java 异常排查知识库

> **加载方式**：由 `SKILL.md` 的 Step 2 按 `signals` 命中项**按节加载**，不要整篇读入。
> 每节固定三段：**特征 / 排查方向 / 修复建议**，末尾附**常见误判**。
> 锚点可直接引用，例如 `references/java-exceptions.md#npe`。

## 目录

| 章节 | 锚点 | 对应脚本 `signals.name` |
| --- | --- | --- |
| 1. NullPointerException | `#npe` | `npe` |
| 2. OutOfMemoryError | `#oom` | `oom` |
| 3. 类加载失败 | `#classloading` | `class_missing` |
| 4. 依赖冲突 | `#dependency-conflict` | `version_conflict` |
| 5. 连接类故障 | `#connectivity` | `connection_refused` / `dns_failure` / `timeout` |
| 6. 数据库与连接池 | `#database` | `db_error` |
| 7. 并发与线程 | `#concurrency` | — |
| 8. 启动失败 | `#startup` | `spring_context` |
| 9. 其他高频 | `#others` | — |

---

<a id="npe"></a>
## 1. NullPointerException（NPE）

### 特征

- `java.lang.NullPointerException`，老版本只有一行，只能靠堆栈定位。
- JDK 14+ 的 Helpful NPE 会直接点名**哪一种** null，这是最快的信息源：

| 消息形态 | 含义 | 典型成因 |
| --- | --- | --- |
| `because "order" is null` | 对象引用为 null | 字段未初始化；`@Autowired` 字段所在对象不是 Spring 管理的（被 `new` 出来） |
| `because the element at index 1 of "java.util.List" is null` | **集合元素**为 null | 数据缺行；按下标填充留下空洞；上游返回含 null 元素的列表 |
| `because the return value of "a.b.C.m()" is null` | 链式调用中间返回 null | `map.get(k)` 未命中；`findOne` 返回空 |
| `because "x" is null`（自动拆箱场景） | 包装类型为 null 参与运算 | DB 可空列映射到 `Integer`/`Long`；`Boolean` 直接进 `if` |
| `because the array is null` / 下标越界 | 数组未初始化或长度不符 | 配置注入空数组 |

### 排查方向

1. **先定位到业务帧**（脚本 `root_business_frame`），不要停在 `org.springframework.*` 帧上。
2. 读消息里点名的变量名 / 字段名，回溯它的**赋值路径**：谁给它赋值、什么条件没走到。
3. 若点名的是注入字段：确认该对象是否由容器创建。`new XxxService()` 出来的实例里 `@Autowired` 恒为 null。
4. 若是集合元素：往**数据源**查——SQL 结果、上游 RPC 响应、缓存快照三者之一。
5. 若是拆箱：核对 DTO/Entity 的包装类型与 DB 表列的可空性。
6. 若是返回值：确认是否漏了 `Optional` / 空集合约定。

### 修复建议

- 在**边界**做校验（外部入参、SQL 结果、RPC 响应），而不是在每个调用点撒 `if (x != null)`。
- 优先构造器注入，让依赖缺失在启动期暴露，而不是运行期 NPE。
- 集合清洗用 `filter(Objects::nonNull)`，但要同时打日志记录脏数据主键——否则只是把问题藏起来。
- 加日志时带业务主键（订单号、用户 ID），便于反查是哪条数据。

### 常见误判

- 把"注入字段为 null"归因为"Spring 没注入"，实际是对象脱离了容器管理。
- 用 `try/catch` 吞掉 NPE 让接口返回 200，把数据不一致推到下游。

---

<a id="oom"></a>
## 2. OutOfMemoryError（OOM）

### 特征：必须先分型，不同分型排查方向完全不同

| `kind` | 含义 | 第一诊断方向 |
| --- | --- | --- |
| `Java heap space` | 堆内存不足 | 大对象、内存泄漏、缓存无上限、一次性加载全量数据 |
| `GC overhead limit exceeded` | GC 花 98% 时间只回收不到 2% | 与 heap space 同源，通常出现在更晚期 |
| `Metaspace` | 元空间耗尽 | 动态生成类（CGLIB、反射、热部署）、ClassLoader 泄漏 |
| `Compressed class space` | 类元数据压缩空间不足 | 同 Metaspace，且类数量极多 |
| `Direct buffer memory` | 堆外直接内存不足 | Netty/NIO 的 `ByteBuf` 未释放、`-XX:MaxDirectMemorySize` 过小 |
| `unable to create new native thread` | 线程数触顶 | 线程泄漏、`ulimit -u`、容器 `pids limit` |
| `Requested array size exceeds VM limit` | 单次分配超大数组 | 反序列化、分页参数异常（如 `size=Integer.MAX_VALUE`） |
| `Out of swap space` / `Map failed` | 操作系统内存或 mmap 失败 | 机器内存耗尽、容器 limit 到顶 |

补充信号：容器里出现 `Killed`、退出码 `137`，说明是 **OOMKilled**，此时 JVM 往往来不及打印堆栈，
日志可能只有半行——不要在这种情况下找"完整堆栈"。

### 排查方向

1. 确认分型（脚本 `out_of_memory.kind`），不要跳过。
2. 区分**缓慢增长**（泄漏）与**瞬时尖峰**（批量任务、大查询、导出）。
3. 有 dump 就分析 dump；无 dump 用 `jcmd <PID> GC.heap_info` 与 `jstat -gcutil` 看老年代曲线。
4. heap：`jmap -histo <PID> | head -30` 看 Top 对象；确认是否有无上限的本地缓存。
5. Metaspace：查动态代理数量、热部署、自定义 `ClassLoader` 是否被静态持有。
6. direct：查 Netty `ByteBuf` 的引用计数是否 release。
7. native thread：查线程池创建策略 + `ulimit -u` + 容器 pids 限制。

### 修复建议

- heap：先定位持有链（静态集合、`ThreadLocal`、缓存 key 无界），再谈扩容。
- Metaspace：限制动态类生成，排查 `ClassLoader` 泄漏。
- direct：显式设置 `-XX:MaxDirectMemorySize`，Netty 开启泄漏检测。
- 容器部署务必设 `-XX:MaxRAMPercentage`，否则 JVM 按宿主机内存计算堆大小。

### 常见误判

- 见到 OOM 就加 `-Xmx`，把泄漏推迟到下一次更严重的故障。
- 把 `GC overhead limit exceeded` 当成独立故障，实际是 heap 不足的尾声。

---

<a id="classloading"></a>
## 3. ClassNotFoundException / NoClassDefFoundError

### 特征：两个异常含义不同，不要混用

| 异常 | 含义 | 典型原因 |
| --- | --- | --- |
| `ClassNotFoundException` | 显式加载（`Class.forName`、资源加载）时找不到类 | 依赖没打进制品；被 `provided` / `exclusion` 排除 |
| `NoClassDefFoundError` | 编译期存在，运行时初始化失败或缺失 | **静态初始化抛异常**（必须看 `Caused by`）；依赖 scope 不对 |
| `LinkageError` / `IncompatibleClassChangeError` | 同一个类被两个类加载器加载，或接口改成了抽象类 | 容器与应用的 jar 冲突、插件化隔离 |
| `AbstractMethodError` | 运行期实现类与编译期接口不匹配 | 依赖版本冲突（见第 4 节） |

### 排查方向

1. `NoClassDefFoundError` **一定先看最内层 `Caused by`**——常见是静态块里抛了 `IllegalStateException`。
2. 确认类是否真的在制品里：`unzip -l app.jar | grep -i Xxx.class`（Spring Boot 3 在 `BOOT-INF/lib`）。
3. 确认依赖 scope：`mvn dependency:tree -Dincludes=<groupId>:<artifactId>`。
4. 确认类加载器隔离：Tomcat、OSGi、插件化框架、`Thread.currentThread().getContextClassLoader()` 的差异。
5. 确认是否被 `spring-boot-maven-plugin` 的 `provided` 或 `optional` 影响。

### 修复建议

- 缺依赖：补 `pom` 依赖或修正 scope。
- 静态初始化失败：修静态块里的真实异常，而不是补 jar。
- 类加载器冲突：统一由父加载器加载，或用 `relocation` 隔离。

### 常见误判

- 把 `NoClassDefFoundError` 一律当"缺 jar"，反复加依赖却没有看 `Caused by`。

---

<a id="dependency-conflict"></a>
## 4. 依赖冲突

### 特征

- `NoSuchMethodError` / `NoSuchFieldError`：编译期 A 版本，运行期 B 版本。
- 同一段代码测试环境正常、线上异常：依赖树不同。
- 日志中出现同一类的两个不同包路径，或栈帧前后矛盾。
- 升级某个 SDK 后突然大面积报错。

### 排查方向

1. 找重复版本：`mvn dependency:tree -Dverbose -Dincludes=<groupId>:<artifactId>`。
2. 看被仲裁掉的版本：`mvn dependency:tree -Dverbose | grep -i omitted`。
3. 看**实际打进去的** jar：`unzip -l app.jar | grep -i "<artifact>"`（不要只看 pom）。
4. 若用了 `shade`：检查是否做了 `relocation`，未 relocate 会与宿主冲突。
5. 若是容器/中间件自带 jar（Tomcat、Spark、Flink）：确认是否被 scope 为 `provided` 排除。

### 修复建议

- `dependencyManagement` 锁定版本，或统一升到同一 BOM。
- 用 `exclusions` 排除传递依赖中的旧版本。
- 三方 SDK 冲突用 `shade` + `relocation`。

### 常见误判

- 直接"升到最新版"，引入新的不兼容；应先锁定到与调用方 API 匹配的版本。

---

<a id="connectivity"></a>
## 5. 连接类故障：refused / timeout / unknown host

### 特征：五种现象，含义完全不同

| 现象 | 含义 | 首要怀疑 |
| --- | --- | --- |
| `Connection refused` / `ConnectException` | 对端端口没有监听（收到 TCP RST） | 服务未启动、端口配错、安全组/iptables、容器端口未映射 |
| `connect timed out` | SYN 无响应 | 网络不通、丢包、防火墙 DROP、对端 backlog 满 |
| `Read timed out` / `SocketTimeoutException` | 已建立连接但对端不返回 | 对端处理慢、锁等待、GC 停顿、连接被借出未归还 |
| `UnknownHostException` | DNS 解析失败 | `resolv.conf`、CoreDNS、search domain、容器 DNS 策略 |
| `Connection reset` | 对端主动断开 | 对端超时短于客户端 keepalive、LB 空闲超时、后端重启 |

### 排查方向

1. 先确认是"连不上"还是"连上了不回"——两者排查方向相反。
2. `ss -lntp | grep <PORT>` 确认本机监听；`nc -zv <HOST> <PORT>` 确认可达。
3. `dig <HOST>` 确认解析结果与预期一致。
4. 对比超时层级：连接超时 < 读超时 < 上游调用超时，任何一层配反都会放大故障。
5. 若只有部分实例失败：查 LB 后端列表、健康检查状态。

### 修复建议

- 配错端口/主机是最常见原因，先核对配置而不是怀疑网络。
- 合理设置三级超时，并让重试带退避、区分幂等。
- DNS 问题在容器环境优先查 CoreDNS 与 `ndots` 配置。

### 常见误判

- 见到 `Connection refused` 就断言"数据库挂了"，实际可能只是端口写错。
- 用 `Read timed out` 去查网络，而真实原因是对端 GC 停顿或锁等待。

---

<a id="database"></a>
## 6. 数据库与连接池

### 特征

- `HikariPool-1 - Connection is not available, request timed out after 30000ms`：**池里拿不到连接**。
- `CannotGetJdbcConnectionException`（Spring 包装，需看 `Caused by`）。
- `Communications link failure` / `connection is closed`：连接被中间件或 DB 断开。
- `Deadlock found when trying to get lock` / `Lock wait timeout exceeded`。
- `SQLSyntaxErrorException` / `BadSqlGrammarException`：SQL 或映射写错。

### 排查方向：Hikari 拿不到连接的四种原因（按概率排序）

1. **连接泄漏**：借出未归还。开启 `leakDetectionThreshold` 可打印泄漏堆栈。
2. **慢 SQL 占满池**：池大小 < 并发 × 平均持有时间。
3. **DB 侧拒绝**：连接数到顶、账号权限、网络不通（通常会伴随 refused/timeout 信号）。
4. **池配置不合理**：`maximumPoolSize` 过小，或 `connectionTimeout` 短于正常 SQL 耗时。

辅助手段：`SHOW PROCESSLIST` / `pg_stat_activity` 看活跃连接与长事务；
应用侧看连接池指标（Spring Boot Actuator `/actuator/metrics/hikaricp.connections.active`）。

### 修复建议

- 泄漏：改用 try-with-resources，检查手动 `getConnection()` 的路径。
- 慢 SQL：加索引、限制返回行数、设置 `statement timeout`。
- 池大小：OLTP 场景约 `CPU 核数 × 2~4`，不是越大越好。
- 长事务：拆分，避免在事务里做 RPC 或大批量写。

### 常见误判

- 把 `maximumPoolSize` 调到 100 来"解决"超时，结果压垮数据库。
- 看到 `CannotGetJdbcConnectionException` 就去查网络，忽略泄漏与慢 SQL。

---

<a id="concurrency"></a>
## 7. 并发与线程

### 特征

- `RejectedExecutionException`：线程池队列满且拒绝策略为 Abort。
- `Found one Java-level deadlock`：jstack 会直接给出持有/等待关系。
- `IllegalMonitorStateException`：`wait`/`notify` 未持锁。
- `TimeoutException`（`Future.get`）：任务慢，还是池被占满，需要区分。
- 线程数持续上涨：`unable to create new native thread` 的前兆。

### 排查方向

1. `jstack <PID>` 连续抓 3 次（间隔 5 秒），看线程是否停留在同一位置。
2. `top -Hp <PID>` 找高 CPU 线程，转十六进制后在 jstack 中定位（`printf '%x\n' <TID>`）。
3. 线程池：核对核心数、队列容量、拒绝策略与实际并发量。
4. 死锁：直接读 jstack 的 deadlock 段，按提示调整加锁顺序。

### 修复建议

- 拒绝策略改为 `CallerRuns` 或自定义（记录 + 降级），不要静默丢弃。
- 缩小锁粒度，统一加锁顺序，避免嵌套锁。
- 线程池参数按"任务类型 + 目标 RT"计算，不复制别人的配置。

### 常见误判

- 抓一次 jstack 就下结论；单次快照无法区分"正在处理"与"卡死"。

---

<a id="startup"></a>
## 8. 启动失败：怎么读 BeanCreationException 链

### 特征

外层永远是包装异常：`BeanCreationException`、`UnsatisfiedDependencyException`、
`ApplicationContextException`、`BeanDefinitionStoreException`。

**规则：外层只用来定位是哪个 bean，根因一律读最深一层 `Caused by`。**

| 最内层异常 | 真实原因 |
| --- | --- |
| `NoSuchBeanDefinitionException` | 缺 bean：组件扫描范围、条件注解、profile 未激活 |
| `BeanCurrentlyInCreationException` | 循环依赖（构造器注入无法解决） |
| `Failed to bind properties` | 配置缺失或类型不符 |
| `BindException: Address already in use` | 端口被占用 |
| `FileNotFoundException` / `AccessDeniedException` | 证书、密钥、配置路径或权限 |
| `ClassNotFoundException` | 依赖缺失（见第 3 节） |
| `SQLException`（启动期） | 数据源连不上、建表脚本失败 |

### 排查方向

1. 从最深一层 `Caused by` 开始读，不要从第一行读。
2. 确认环境：profile、配置中心是否拉取成功、环境变量是否注入。
3. 确认依赖顺序：`@DependsOn`、`@PostConstruct` 中依赖尚未初始化的 bean。
4. 本地能起、容器起不来：优先查配置与环境变量，而不是代码。

### 修复建议

- 循环依赖：重构为单向依赖，或用 `@Lazy` 打破（治标）。
- 配置缺失：给默认值并在启动时校验（`@ConfigurationProperties` + `@Validated`）。
- 端口占用：确认是否有残留进程或同机多实例。

### 常见误判

- 顺着最外层异常名去改代码，实际要改的是配置或依赖。

---

<a id="others"></a>
## 9. 其他高频

| 异常 | 首要排查方向 |
| --- | --- |
| `StackOverflowError` | 递归无终止；Jackson 循环引用（`@JsonIgnore`）；AOP 自调用；`equals`/`hashCode` 互调 |
| `JsonMappingException` / `HttpMessageNotReadableException` | 请求体字段类型不符、日期格式、枚举值不在范围 |
| `MethodArgumentNotValidException` | 参数校验失败，属于业务预期，不是故障 |
| `OutOfMemoryError` | 见第 2 节，先分型 |
| `NullPointerException` | 见第 1 节，先看 Helpful NPE 消息 |
| `UnsupportedClassVersionError` | JDK 版本不匹配（编译版本高于运行版本） |

---

## 附：从异常名到章节的速查

```
NullPointerException                -> #npe
OutOfMemoryError                    -> #oom
ClassNotFoundException              -> #classloading
NoClassDefFoundError                -> #classloading（先看 Caused by）
NoSuchMethodError / LinkageError    -> #dependency-conflict
ConnectException / UnknownHost      -> #connectivity
SocketTimeoutException              -> #connectivity（再考虑 #database）
HikariPool / SQLException           -> #database
RejectedExecutionException          -> #concurrency
BeanCreationException               -> #startup（读最深层 Caused by）
```
