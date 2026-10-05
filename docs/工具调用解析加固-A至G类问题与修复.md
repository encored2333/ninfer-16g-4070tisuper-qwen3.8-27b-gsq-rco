# 工具调用解析加固：A 至 G 类问题与修复

本文记录引擎侧 Qwen 工具调用解析器（`src/models/qwen3_5/frontend/tool_call_parser.cpp`）的一次系统性加固。加固对象是一份独立排查报告列出的 A 至 G 类共 30 余种畸形形态，其中多数在修复前会**静默退化**：正文泄漏、调用丢失、参数被改写，或整段退化为纯文本，而诊断 `reason=none`、日志没有任何信号。

涉及文件（两个引擎树同源同补）：

| 文件 | 作用 |
| --- | --- |
| `src/models/qwen3_5/frontend/tool_call_parser.cpp` | 解析器主体 |
| `include/ninfer/types.h` | `ToolCallParseDiagnostics` 诊断字段 |
| `src/serve/request_log.cpp` | 请求日志 JSONL 字段 |
| `src/serve/operational_log.cpp` | 控制台告警 |
| `tests/test_tool_call_parser.cpp` | 官方单元测试（新增 2 例、修订 2 处契约） |

上述五个文件修改后的完整内容在 `docs/patches/` 下，逐行改动见同目录的
`tool-call-parser-hardening.diff`（可直接 `git apply` 到上游同名文件）。

---

## 1. 治理原则

1. **消灭静默**：凡是"坏了但无信号"的路径，改为可诊断（诊断字段 + 日志告警），不改变可观测语义。
2. **安全优先于兼容**：可能造成**误执行**的路径收紧（正文里引用的调用示例不再执行）。
3. **零回归不变式**：合法输出的解析结果逐字节不变。闸门是官方单元测试 `exit=0` 加 51 例黑盒探针仅出现**预期内**差异。
4. **先红后绿**：每条修复先构造能复现缺陷的探针用例，再改到通过。

---

## 2. 验证基建

| 工具 | 覆盖 | 说明 |
| --- | --- | --- |
| `ninfer_tool_call_parser_test` | 官方单元测试 | 需 CMake 配置 `BUILD_TESTING=ON`；闸门要求 `exit=0` |
| `ninfer-probe`（51 例） | 全形态黑盒探针 | 无 GPU、秒级；用于"仅预期差异"回归 |
| `probe_ae` | A 类 + E 类 + 反例 | A1–A8、E1、E2 由红转绿；N1/N2 反例必须保持"不调用" |
| `probe_bc` | B 类 + C 类 | 正文泄漏与多调用丢失 |
| `probe_g3` | 流式逐字节一致性 | 每组文本按 1 至 23 字节切块，比较流式与非流式结果 |

每批修复的闸门固定为三条：官方测试 `exit=0`、51 例探针差异仅为预期项、专项探针红例转绿且反例不回归。

---

## 3. 逐类修复

### A 类 · 整段退化（`<|im_start|>` 污染与方言变体）

| 编号 | 形态 | 修复 |
| --- | --- | --- |
| A1–A4 | `<|im_start|>` 控制 token 残留在 `<tool_call>` 与 `<function=…>` 之间（同行、独立行、无 wrapper 等） | 集中式**区域预规范化**：剥离标签边界处的 `<\|…\|>`，补全缺 `<` 的裸 `function=` / `parameter=`；**仅当规范化结果命名了已声明工具时**才采纳，正文永不会因此变成调用 |
| A5 | `<function bash>` 空格分隔、无 `=` | 容忍"裸词头部"：header 首词即函数名；但**仅当该词是已声明工具**时才成立（否则仍按非法名拒绝，正文保持正文） |
| A6 | `<function_calls>` 内再套 `<tool_call>` | 打开函数前**循环跳过**两种 wrapper，任意嵌套顺序均可 |
| A7 | 只有 `<tool_call>`、没有函数 | 统一规则："区域是否真的打开了一个函数"。只有 wrapper 而无函数标签**不是**调用尝试，保持正文（官方测试固定不能改） |
| A8 | `<![CDATA[ … ]]>` 包住参数值 | 剥离 CDATA 包裹，只留内容 |

### B 类 · 静默泄漏

| 编号 | 形态 | 修复 |
| --- | --- | --- |
| B1/B2/B3 | 已接受调用之前的失败 marker 区域、markdown 围栏被并进正文且 `reason=none` | 正文边界维持官方契约（首个 marker 之前的文本；引号内或损坏的示例留在消息里），但**被丢弃/吞并的 markup 字节数**记入 `markup_before_call_bytes`，并在运行日志告警。**不删除任何字节** |

### C 类 · 静默丢调用

| 编号 | 形态 | 修复 |
| --- | --- | --- |
| C1 | 一个 wrapper 里两个函数，只保留 1 个 | 宽松读取在遇到兄弟函数开启标签时闭合当前调用，recovery 循环逐个别读，坏的那个产出占位、好的继续保留 |
| C3 | 完整调用后紧跟另一个完整调用，第二个被丢 | 依文法 `(call ws)*` 全部保留，以 51 例探针回归闸门固化 |
| C5 | 正文引用 marker 超过 16 次 | 尝试上限 `kMaxMarkerAttempts` 是**官方测试盯死的扫描护栏**，维持不变；该形态作为已记录限制 |
| C4 | `parallel_tool_calls=false` 只回 1 个 | OpenAI 并行语义，**不改**，仅文档化 |

### D 类 · 有损路径

| 编号 | 形态 | 处理 |
| --- | --- | --- |
| D1 | 参数值内部引用自己的闭合标签，边界被吞 | 值**逐字节保留**（闭合符后随普通文本即视为值内容，后随空白与 `<` 或文末才结束）；新增 `ambiguous_parameter_closers` 计数与告警，让该形态可见 |
| D2 | 声明为非 string 的参数收到空值，整个参数消失 | 维持**省略**语义（两个官方测试固定：可选字段"未提供"的正解就是不出现在 JSON 里），但 `empty_arguments_omitted` 现在会触发运行告警，不再静默 |
| D3/D5/D6/D7 | 未声明参数类型推断、`integer` 收到 `007`/`+7`、XML 实体透传、参数顺序 | **文档化不改**：属既定可观测语义 |
| D4 | `required` 不校验 | 维持"解析器不拦截"契约，由客户端校验并回报 |

### E 类 · 身份与权限

| 编号 | 形态 | 修复 |
| --- | --- | --- |
| E1 | 工具名大小写漂移（声明 `bash`，模型写 `BaSh`） | 大小写不敏感且**唯一**匹配时，按**已声明的拼写**输出，客户端不再报未知工具；声明歧义（同名不同大小写并存）时不猜测 |
| E2 | 非法工具名没有 `intended_function` | malformed 占位参数里补上尽力而为的 `intended_function`（最长 64 字节）。**这是合同变更**，见第 4 节 |
| E3 | 正文里引用的裸 `<function=…>` 被当成真实调用 | **收紧**：裸 `<function…>` 只有在**响应开头**或**段落开头（前置空行）**时才算尝试；正文行内引用的示例保持正文，不再执行。**这是合同收紧**，见第 4 节 |

### F 类 · 硬失败

| 编号 | 形态 | 处理 |
| --- | --- | --- |
| F1/F2 | 工具名长度超过配置上限（生产 256 / 默认 128）导致 HTTP 400 | 报错文案与配置来源文档化；解析器本身按 `max_tool_name_length` 判定 |

### G 类 · 死代码与诊断缺口

| 编号 | 内容 | 处理 |
| --- | --- | --- |
| G1 | `DuplicateParameter` 枚举不可达（重复参数静默取最后值并计数） | 保留枚举（日志兼容），文档标注；重复计数已有 |
| G2 | 无断言覆盖"recovered 调用 + 非 None reason" | **新增官方测试** `test_recovery_reports_both_call_and_reason` |
| G3 | 流式路径疑似丢字节（静态推断） | **新增官方测试** `test_streaming_never_drops_bytes_at_any_chunk_size`：10 组文本 × 每字节切块 1 至 23，流式结果必须与非流式逐字节一致。**实测无法复现丢字节**；源码注释已更正（结束候选的那个字节仍会被随后的普通分支处理，并未丢弃） |
| G5 | 测试与实现疑似矛盾 | **编译核对：不存在矛盾**。相关测试已在 `main()` 注册且整套 `exit=0` |

---

## 4. 合同变更（客户端需要知悉）

1. **E2 · `intended_function` 覆盖非法名**
   以前只有"合法但未声明"的名字才会写进 `malformed_tool_call` 的参数；现在**非法名**（含空格、斜杠、非 ASCII、超长）也会写进去，最长 64 字节。调用仍然是 `malformed_tool_call`，不会被执行。目的是让模型知道它尝试调用的名字，便于重试。

2. **E3 · 正文中的裸 `<function…>` 不再执行**
   判定规则：裸 `<function…>` 位于响应开头，或位于一个段落开头（其前是空行）时，才算调用尝试；出现在正文行内的（如"用法是 `<function=configure>…</function>`"）一律保持正文。此前这类示例会变成真实调用，存在误执行风险。带 `<tool_call>` / `<function_calls>` wrapper 的调用不受影响。

---

## 5. 新增诊断字段

`ToolCallParseDiagnostics` 新增四个字段，均**只增加可观测性、不改变解析结果**：

| 字段 | 含义 | 触发告警文本 |
| --- | --- | --- |
| `markup_before_call_bytes` | 已接受调用之前被跳过的 markup 字节数（失败区域、引号内示例、markdown 围栏） | `tool markup before call \| bytes=N, kept in content` |
| `markup_repaired` | 区域在解析前被修复过（剥离控制 token、补全裸标签） | 随上述告警一并可见 |
| `prose_markers_skipped` | 因位于正文中而被跳过的裸 `<function…>` 个数 | `bare function markup in prose \| count=N, kept in content` |
| `ambiguous_parameter_closers` | 参数值内部引用了自己的闭合标签、被并进值的闭合符个数 | `ambiguous parameter closer \| count=N, kept in value` |

另有 `empty_arguments_omitted > 0` 时新增告警：`empty declared parameter omitted | count=N, absent from arguments`。

四个字段同时写入 `--request-log-jsonl` 的每条请求记录，便于长期统计这些形态的发生频率。

---

## 6. 复现与自检

```bat
rem 官方单元测试（需先配置 BUILD_TESTING=ON 并构建）
ninfer_tool_call_parser_test.exe && echo PASS

rem 51 例黑盒探针：与非回归基线对比，差异应仅为预期项
ninfer-probe\probe.exe > probe.out.txt
fc probe-baseline.txt probe.out.txt
```

---

## 7. 未采纳项与理由（透明记录）

| 项 | 计划原文 | 实际处理与理由 |
| --- | --- | --- |
| A7 | "统一为明确的 malformed 路径" | 改为统一为**单一判定规则**："区域是否打开了函数"。官方测试固定"正文提及 `<tool_call>` 仍是正文"，因此只有 wrapper 而无函数标签不能算调用尝试 |
| D2 | "保留空值" | 保持**省略**。两个官方测试固定"可选字段空值 = 不出现在 arguments"，且省略是 JSON 中对"未提供"的正确表达；改为 null 会把语义从"缺省"改成"显式为空"，对必填字段反而更糟。改为**告警**以满足"消灭静默" |
| C4 | 未列出 | OpenAI 的 `parallel_tool_calls` 语义，属既有可观测行为，文档化 |
| C5 | "界值只统计能开函数的候选" | 尝试上限是官方测试盯死的扫描护栏，改动会破坏既有契约；作为已记录限制保留 |
| G3 | "复现则修" | 未复现（10 组文本 × 23 种切块全部逐字节一致），不修代码，只更正误导性注释并补测试 |
| G5 | "存在矛盾，需编译核对" | 编译并运行核对：**不存在矛盾**，测试与实现一致 |

---

## 8. 变更清单（按批次）

| 批次 | 内容 |
| --- | --- |
| 1 | B1–B3 泄漏可见化（计数 + 告警，不删字节）；C1 多调用保留；围栏与尝试上限维持契约 |
| 2 | A1–A8 全覆盖（含区域预规范化与 CDATA）；E1 大小写漂移；E2 非法名回显（合同变更）；E3 正文示例不再执行（合同收紧） |
| 3 | D1 歧义闭合符计数与告警；D2 空值省略告警 |
| 4 | G2/G3 新增官方测试；G5 编译核对；G1 文档化 |
