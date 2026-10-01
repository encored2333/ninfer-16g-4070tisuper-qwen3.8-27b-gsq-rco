# NInfer 验证脚本（RTX 4070 Ti SUPER 16GB）

本目录两个脚本用于验证本地 NInfer 推理引擎服务是否正常、并测量与官方 RTX 5070 Ti 实测参考（64K 输入 prefill ≈ 1695 tok/s、decode ≈ 105 tok/s、TTFT ≈ 37 秒，见 `D:\ninfer\src\docs\rtx-5070ti-windows.md`）的相对速度。4070 Ti SUPER 预期约为 5070 Ti 的 **75%**。

## 环境约定

- 推理 API：`http://127.0.0.1:18081/v1`（OpenAI / Anthropic 兼容；管理器默认端口，见 `docs/rtx-5070ti-windows.md` 与 `apps/windows-manager` 默认配置）
- 管理网页：`http://127.0.0.1:8090`（从托盘打开可启动/管理模型）
- 预期注册模型名：`Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp`（服务端由 `--model-id` 注册；`/v1/models` 可查）
- Python 3.11（`py -3.11`），脚本仅用标准库（urllib），无第三方依赖

## 1. bench.py — 服务验证与基准

### 用法

```bat
:: 快速验证：健康检查 + 1 条短对话（默认 base 与模型名已是本环境预期值）
py -3.11 D:\ninfer\validate\bench.py --mode quick

:: 完整基准：短对话(warm-up) + decode 专项 + ~4000 token 输入 + ~64K token 输入 + 对比表
py -3.11 D:\ninfer\validate\bench.py --mode full

:: 常用参数
py -3.11 bench.py --base http://127.0.0.1:18081 --model Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp --mode full --timeout 900
```

| 参数 | 默认 | 说明 |
|---|---|---|
| `--base` | `http://127.0.0.1:18081` | 推理 API 根地址 |
| `--model` | `Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp` | 预期模型名；脚本先查 `/v1/models` 自动校正（model 字段与注册名不一致会 404） |
| `--mode` | `quick` | `quick` 或 `full` |
| `--timeout` | `900` | 单请求 socket 超时秒数 |
| `--api-key` | 空 | 服务端开启 `--api-key` 时填写 |
| `--short-max-tokens` / `--decode-max-tokens` | 512 / 256 | 各用例输出上限 |
| `--mid-tokens` / `--long-tokens` | 4000 / 65536 | full 模式中/长档输入目标 token 数 |

### 长输入构造方式

无本地分词器，长 prompt 用**固定英文句子按 ~4 字符/token 估算重复到目标量级**：种子句 160 字符 ≈ 40 token，~4000 档重复 100 次、~64K 档重复 1600 次（约 250 KB 文本）；句尾追加中文指令（"忽略上文，从 1 数到 200"，保证解码吃满 `max_tokens=256`）。**实际 token 数以服务端返回的 `usage.prompt_tokens` 为准**，脚本会打印。

### 测速口径（与官方一致）

- **prefill tok/s**：服务端 `timings.prompt_per_second`（未缓存输入 tokens / 引擎 prompt 时间）
- **decode tok/s**：服务端 `timings.predicted_per_second`（(输出-1) / 引擎 predicted 时间），同时打印客户端口径兜底
- **TTFT**：客户端从发出请求到**第一个非空思考/正文流事件**（官方口径）
- 依据：`D:\ninfer\src\docs\rtx-5070ti-windows.md`（"解码速度 =（输出 tokens − 1）/ 引擎 predicted 时间；客户端 TTFT 从发出请求计到第一个非空思考、正文或工具流事件"）。因 TTFT 必须流式才能测，脚本走 **SSE 流式** + `stream_options: {"include_usage": true}`，最终 usage chunk 携带 `usage` 与 `timings`（`src/serve/openai_chat_response.cpp` 的 `usage_chunk`）。

### 预期输出样例（数值为示意）

quick 模式：

```
NInfer 基准验证  mode=quick  base=http://127.0.0.1:18081  预期模型=Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp
------------------------------------------------------------------------------
[OK] GET http://127.0.0.1:18081/health -> 200 {"status":"ok"} 服务就绪
[OK] 服务端注册模型 id: Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp
------------------------------------------------------------------------------
  [短对话] 请求完成
  实际输入 tokens   : 12
  输出 tokens       : 23
  客户端 TTFT       : 0.412 s
  prefill (引擎)    : n/a tok/s            # 短输入 prompt_n 可能被缓存计为 0
  decode  (引擎)    : 55.30 tok/s
  decode  (客户端)  : 52.10 tok/s
  总耗时            : 0.85 s
  finish_reason     : stop

完成。
```

full 模式结尾：

```
==================================================================================
结果汇总 (prefill/decode 为引擎 timings 口径, 与官方测法一致)
==================================================================================
用例                   输入 tok       输出 tok     TTFT s       prefill tok/s       decode tok/s
短对话                 12             23           0.41         n/a                 55.30
decode 专项(短输入)    15             256          0.38         n/a                 79.20
~4000 输入             3,987          256          3.44         1,158.3             78.80
~65536 输入            62,341         256          51.02        1,222.0             77.50

==============================================================================
与 RTX 5070 Ti 官方参考对比 (64K 输入档, docs/rtx-5070ti-windows.md)
==============================================================================
指标               5070Ti 参考       本机实测      实测/参考    75% 预期
------------------------------------------------------------------
Prefill tok/s      1,695.4           1,222.0       72%          ~1272
Decode tok/s       99.4 - 105.6      77.5          76%          ~74.5 - 79.2
客户端 TTFT s      ~36.9             51.0          -            -
------------------------------------------------------------------
```

服务未启动时的明确报错：

```
[失败] GET http://127.0.0.1:18081/health
[服务未启动] 无法连接 http://127.0.0.1:18081 ([WinError 10061] ...)。
  排查提示:
  1. 若用 NInfer 管理器启动: 打开管理页 http://127.0.0.1:8090 选择配置启动模型;
     推理 API 默认地址是 http://127.0.0.1:18081/v1 (docs/rtx-5070ti-windows.md)。
  ...
```

## 2. watch_vram.ps1 — 显存监控

每 2 秒轮询 `nvidia-smi`，按名字匹配 **RTX 4070 Ti SUPER** 那块卡，输出时间戳 + 已用/总/余量 MiB + 利用率；Ctrl+C 退出。

```bat
powershell -NoProfile -ExecutionPolicy Bypass -File D:\ninfer\validate\watch_vram.ps1
:: 换卡或改间隔
powershell -NoProfile -ExecutionPolicy Bypass -File D:\ninfer\validate\watch_vram.ps1 -IntervalSeconds 2 -GpuName "4070 Ti SUPER"
```

预期输出样例：

```
watch_vram: polling GPU matching '4070 Ti SUPER' every 2s via 'C:\Windows\System32\nvidia-smi.exe'.
Press Ctrl+C to stop.
timestamp           gpu / vram
2026-09-30 23:50:01  NVIDIA GeForce RTX 4070 Ti SUPER  used 15234 MiB / 16383 MiB  free 1149 MiB  util 98%
2026-09-30 23:50:03  NVIDIA GeForce RTX 4070 Ti SUPER  used 15236 MiB / 16383 MiB  free 1147 MiB  util 97%
```

（`watch_vram stopped.` 为 Ctrl+C 后的收尾行；找不到匹配卡时会打印 nvidia-smi 检测到的全部卡名。）

## 验证通过标准

1. **服务就绪**：`GET /health` 返回 200 且 `{"status":"ok"}`；`/v1/models` 列出注册模型名。503 表示服务进程在但模型未就绪（加载中），连接拒绝表示服务未启动。
2. **短请求成功**：quick 短对话拿到流式事件、`finish_reason`（`stop` 或 `length`）且 `completion_tokens > 0`，流以 `[DONE]` 收尾。
3. **显存余量 > 100 MiB**：在 64K 用例运行期间用 watch_vram.ps1 观察，`free` 持续 > 100 MiB（官方 5070 Ti 64K strict 档余量约 1.9–2.8 GB；4070 Ti SUPER 16GB 余量应明显为正）。余量归零或为负说明驱动已借用 Shared 系统内存。
4. **解码速度量级合理**：64K 档 decode 引擎口径大致落在 **70–85 tok/s**（75% 预期 74.5–79.2 的合理浮动）、prefill 约 **1100–1300 tok/s**、64K TTFT 约 45–60 秒。若 decode 跌到个位数、prefill 只有几十 tok/s，基本是显存不足触发 Shared 显存回退（官方 mixed 模式实测会跌 20 倍以上），需降低上下文/KV 量化或换更小的 profile。

## API 形状求证依据（源码文件）

| 结论 | 依据 |
|---|---|
| 健康端点 `GET /health` → 200 `{"status":"ok"}` / 503 `{"status":"unavailable"}` | `D:\ninfer\src\src\serve\http_server.cpp`（路由注册 511 行、`handle_health` 668–673 行） |
| 推理 base `127.0.0.1:18081/v1`、管理页 `127.0.0.1:8090` | `D:\ninfer\src\docs\rtx-5070ti-windows.md`（26–27 行）、`apps\windows-manager\Backend\ConfigurationStore.cs`（146 行默认 18081）、`apps\windows-manager\Contracts.cs`（16 行 WebPort 8090） |
| `/v1/chat/completions` OpenAI 兼容；`/v1/messages` Anthropic 兼容；另有 `/v1/models`、`/v1/load`、`/stats`、`/props`、`/slots` | `http_server.cpp` 533–575 行路由 |
| 流式为 SSE `data: {...}` 行 + 终止行 `data: [DONE]`；首 chunk `delta={role,content:""}`；正文/思考分别走 `delta.content` / `delta.reasoning_content` | `D:\ninfer\src\src\serve\openai_chat_response.cpp`（`chunk` 273–283 行、`content_delta`/`reasoning_delta`、`finish` 477 行 `[DONE]`） |
| `stream_options.include_usage=true` 时末尾 usage chunk 带最终 `usage` 与 `timings`（`prompt_per_second`/`predicted_per_second` 等） | `openai_chat_response.cpp` `usage_chunk` 284–290 行、`timings_json` 75–90 行；请求侧 `openai_chat_request.cpp` `parse_stream_options` 946–955 行 |
| `max_tokens`（及 `max_completion_tokens`）受支持；model 字段可省略但给错返回 404 `model_not_found` | `openai_chat_request.cpp` `parse_output_limit` 962–978 行、`parse_chat_completion_request` 995 行注释；`openai_common.cpp` `validate_openai_model` 284–293 行 |
| 官方测速口径（prefill=未缓存输入/引擎 prompt 时间；decode=(输出-1)/predicted 时间；TTFT=首请求至首个非空流事件 → 因此选流式） | `D:\ninfer\src\docs\rtx-5070ti-windows.md` 283 行及参考表 293–318 行 |
