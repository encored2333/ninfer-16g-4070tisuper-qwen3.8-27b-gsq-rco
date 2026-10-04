# KVMem 环完全修复与 Agent 场景调优实录

> 在 16GB RTX 4070 Ti SUPER 上把上游 KVMem 环补丁（shensanshu/ninfer-master-shensanshu-kvmem，
> 基线 0.11.0-rtx3090，与我们的源码树同基线）从"原型可用"推进到"agent 生产可用"的完整记录。
> 包含三处引擎源码修复、一组参数处方、dsh 等 agent 客户端的配置表、以及全部验证数据。

## 0. 成果速览

| 项 | 值 |
|---|---|
| 逻辑上下文 | 262,144（256K，模型原生上限）|
| KV 池 | **75,776 token（1,184 页，k8v4）**，runtime 3.38 GiB / free 843 MiB |
| 常驻窗口 | 32,768 + 每轮检索 8,192 |
| MTP 投机 + host-backed 复用 | **同时工作**（上游补丁做不到——见 §2 三道门修复）|
| 多轮追问 | 第二轮起 0.3~2s（cache 99.8%+，`adopt host-backed` 实测 frontier=129,540 / 池 17,920）|
| agent 工具调用 | 10 轮疲劳测试零畸形（修复前：连续 3 次 `malformed_tool_call` + 逐字碎裂）|

## 1. 上游补丁移植（起点）

- 补丁 = 34 个源文件整文件覆盖（`patches/changed-files/`，与基线同 VERSION 0.11.0-rtx3090，
  34/34 同名存在、符号自洽、include 100% 可解析——直接覆盖零冲突）
- 我们树与补丁基线同 fork 血统（Ryan-gsq fork ← iamwavecut/ninfer-all）
- 构建：同主部署文档第 5 节流程，`JOBS=8` 防 OOM，nvprune sm_89
- **必须 `--prefill-chunk 256`**（不是白皮书模板的 1024）：chunk 1024 在过池预填上随机楔死
  （零错误行、prefill 零推进），两次实锤；256 后 5/5 稳定，速度几乎无损失

## 2. 三道门修复（引擎源码，本仓库 `docs/patches/` 有完整文件）

上游补丁的 host-backed 复用只做完了"发布"半边（代码注释自述 *"Recorded only for now"*），
"采纳"侧被三道只认内存状态的硬门堵死——装不下就 `throw` 500。三处全部改为
**优雅降级**（`return std::nullopt` → 放弃本次复用、重新规划重填；容量是正常工况，永不 500）：

| # | 文件:位置 | 原行为 | 修复 |
|---|---|---|---|
| 门1 | `request_plan.cpp` MTP 采纳门 | 检查点 MTP KV 覆盖不足 → throw `published MTP checkpoint is not materializable` | 增加第三析取：backend 链在宿主层**全链可恢复**（每页 device 或 host-current）即放行；真不可恢复才降级 |
| 门2 | `pressure.cpp` 宿主后备采纳门 | 只扫 text 页 → backend 页缺失漏检 | 补 backend 扫描（同谓词 `host_resident && host_replica_current`），并入同一 decline 诊断 |
| 门3 | `request_plan.cpp` entitlement 门 | retained 前缀页 > 活跃配额 → throw `retained prefix exceeds its active KV entitlement` | 降级为重新规划（重填） |

物化层（`materialization.cpp` 的 backend H2D 恢复规划/提交/发布）**零改动**——机制本来就在，
只是被门挡住。三道门修完后 MTP 满血与超池复用真正兼得。

**楔死事故处理纪律**（两次实锤）：楔死引擎被 `taskkill` 强杀 = 4070 Ti SUPER 整卡掉线
（PnP Unknown/问题码 12+0xC0000138），软件层不可恢复，**必须关机断电 30 秒冷启动**。
预防 = chunk 256；发生后严禁强杀。

## 3. Agent 场景参数处方（按上游《卡死与循环的防治》+ 实测迭代）

### 3.1 引擎侧（`scripts/start_qwen3_8_27b_gsq_kvmem.bat` 最终值）

| 参数 | 值 | 依据 |
|---|---|---|
| `--kv-capacity` | **75776** | 池要同时养 retained 前缀 + 输出租约；81920 会 OOM（差 55MB），此值留 843MiB 显存缓冲 |
| `NINFER_KV_WINDOW` | **32768** | 窗口覆盖 agent 的"自我示范历史"（工具调用格式锚点），治格式漂移的根 |
| `--auto-long-anchors` | 开 | 消息边界锚定（引擎现成机制）|
| `--temperature / --top-p` | **0.7 / 0.8** | 非思考通道工具场景处方（白皮书 L2 表）；温度 1.0 时出现过逐字碎裂输出 |
| `--presence-penalty` | **0** | 高 presence 与工具调用结构化标记打架 |
| `--preserve-thinking` | **关** | 回灌上轮推理 = 空交付/退化**已定级主因**（上游单变量实验：去回灌 10 轮 0 退化）|
| `--default-thinking-budget` | **8192** | 思考收束阀；12288 档实测偶发畸形、16384 数学上装不下（思考+正文 > max_tokens）|
| `--max-shared-prefixes 0` | 必开 | 防同题面重发的 503 毒化 |
| `--spec mtp --draft-tokens 4 --adaptive-mtp --lookup-ngram 31` | 保留 | 投机满血（实测 mtp accepted 25/39≈64%，decode 76~120 tok/s）|

### 3.2 客户端侧（dsh 等任何 OpenAI 兼容 agent 客户端）

| 字段 | 值 | 说明 |
|---|---|---|
| Base URL | `http://127.0.0.1:8081/v1` | 本地服务，鉴权关闭 |
| Model | `qwen3.8-27b` | `--model-id` 别名 |
| API Key | 任意非空（如 `sk-local`） | 引擎不校验，客户端字段校验过 |
| **max_tokens** | **24576** | 天花板 = 池 75,776 − retained 前缀；超了触发降级重填（不失败但慢一轮）。曾因 40000 > 池 35,840 触发过 entitlement 报错（门3 修复后变降级）|
| temperature | 不设（用引擎默认 0.7）| 要覆盖就 0.7，别用 1.0 |
| reasoning 回传 | **不回传** `reasoning_content` | 配合关回灌的主因修复 |
| 大文件写入 | 分轮写（每轮 ≤12K）| 单轮"思考 8K + 文件 13K"顶满 16K 会截坏收尾标记（实测形态：`</tool_call>` 残缺当文本吐出）|
| 单轮输出解剖 | 思考 8,192 + 正文余量 | budget 是收束阀不是配额，max_tokens 才是硬顶 |

### 3.3 行为边界（什么时候会发生什么）

| 场景 | 行为 |
|---|---|
| 会话前缀 < ~51K | 复用秒回（0.3~2s）|
| 前缀涨过 entitlement（约 51~76K，随输出预留浮动）| **一次降级重填**：40K≈95s / 72K≈235s / 129K≈642s（过池越深越慢），下一轮恢复秒回 |
| 同前缀逐字节重发 | response replay，0.3~1s |
| 楔死（极低概率，chunk 256 已防）| 严禁 taskkill；关机冷启动 |
| max_tokens + 前缀 > 池 | 门3 降级重填（旧版是 HTTP 500）|

## 4. 验证记录（脚本在 `scripts/kvmem-tests/`）

| 测试 | 脚本 | 结果 |
|---|---|---|
| 完全修复三循环（72K/129K/72K × 重发+续问）| `verify_complete_fix.py` | 3/3 PASS；`adopt host-backed`×6、零 materializable、零 invariant |
| dsh 场景六轮复现 | `reproduce_invariant.py`（含在调优过程）| 6/6 存活，129K 题面 7.2 倍过池复用 100% |
| 标准工具循环 | `test_agent_loop.py` | 4/4 合法 |
| **疲劳加强版**（10 轮 + 45K 中段文档 + 回灌）| `test_fatigue10.py` | **零畸形**（唯一 FAIL 为"完工总结"假阳性）|
| 工具调用温度矩阵 | `test_toolcall.py` | temp 1.0/0.7 合法；0.3 思考烧满无输出 |
| `--structured-output` 实验 | — | **死刑**：与 thinking 冲突全烧 + grammar 路径 100% malformed 占位，勿开 |

## 5. 与其他档位的关系（本仓库三件套）

| bat | 定位 |
|---|---|
| `start_qwen3_8_27b_gsq_kvmem.bat` | **全能主力**：256K + agent 稳定 + 追问秒回 |
| `start_qwen3_8_27b_gsq_ninfer.bat` | 深思考特化：119.5K 无损 + prefill 快 3 倍 + 可放 32K 思考预算 |
| `start_qwen3_8_27b_gsq_vision_ninfer.bat` | 图片/视频输入，48K |

引擎二进制：`engine-kvmem\` 为三道门修复版（Release v1.1+ 的包）；`engine\` 为原版（无 KVMem）。
