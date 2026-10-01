# NInfer on 16GB VRAM: RTX 4070 Ti SUPER 跑 Qwen3.8-27B (GSQ-RCO Q3)

> 在 **RTX 4070 Ti SUPER (16GB)** 上，通过**源码构建 sm_89 引擎**，完整复现 RTX 50 系专属的
> NInfer + Qwen3.8-27B GSQ-RCO Q3 量化部署，并附带全套实测数据。
>
> **结论先行：解码 112 tok/s @52K 上下文，比 RTX 5070 Ti 官方实测（99.4–105.6 tok/s）还快 9%。**

RTX 40 系用户没有官方预编译引擎可用（现成引擎只含 RTX 50 系的 sm_120a 机器码），本仓库提供
从源码到上线的完整闭环：模型转换 → 引擎编译 → 运行目录组装 → 启动调优 → 性能验证。

## 实测结果（RTX 4070 Ti SUPER 16GB vs 官方 RTX 5070 Ti 16GB）

| 指标 | 5070 Ti 官方参考 | 4070 Ti SUPER 本机实测 | 达成率 |
|---|---|---|---|
| 解码 @52K 输入 | 99.4 – 105.6 tok/s | **112.0 tok/s** | **109%** |
| 解码 短上下文专项 | ~123.6 tok/s | **139.7 tok/s** | ~113% |
| Prefill @52K 输入 | 1,695 tok/s | **1,454.9 tok/s** | 86% |
| Prefill @3.3K 输入 | — | **1,664.6 tok/s** | — |
| TTFT @52K 输入 | 36.9 s | **35.7 s** | ≈持平 |
| TTFT 短对话 | — | **0.35 s** | — |

模型配置：Qwen3.8-27B **ISTA 变体** · GSQ-RCO 逐张量混精量化（IQ3_S 主体 + attention key / mlp down 用 IQ4_XS · MTP 模块 Q6_K · proposal 头 Q4_K）
另有**视觉版**制品（text,mtp,vision，1176 张量）：支持图片/视频输入，实测发图识别通过（详见性能实测文档）。
运行配置：strict 显存严格驻留 · **KV 池 97,280 tokens（rk8v4）** · 逻辑上下文 80K · MTP×4 自适应草稿 + ngram 查找

> 相比官方软件包的 Swift XXS 档（IQ3_XXS 主体），ISTA 的 IQ3_S 主体困惑度更优
> （上游实测 WikiText-2 PPL 7.071，优于官方 IQ3_S 产物的 7.286）。

## 仓库内容

```
├── docs/
│   ├── 部署文档.md        ← 主文档：依赖全集 / 模型转换 / 源码编译 / 组装 / 启动调优 / 换显卡适配 / 20 条踩坑
│   ├── 性能实测.md        ← 全套 bench 数据与官方参考对比、复测方法
│   └── 模型转换指南.md    ← GSQ-RCO 原版 GGUF → .ninfer 完整方法（哈希校验 / 双变体 / 常见坑）
├── scripts/
│   ├── fetch-asset.bat            vcpkg 资产下载器（代理→镜像→直连三级回退，国内网络救星）
│   ├── build-sm89.bat             一键 CMake 配置 + CUDA 算子编译 + nvprune + 链接
│   ├── start_qwen3_8_27b_ninfer.bat        启动模板（文本版，strict，80K）
│   ├── start_qwen3_8_27b_ninfer_vision.bat 启动模板（视觉版，支持图片/视频，48K）
│   ├── resume-sm89.bat            低并发续编（32GB 内存机器防 OOM）
│   └── validate/
│       ├── bench.py               OpenAI 兼容接口基准测试（quick/full 两档，纯标准库）
│       ├── watch_vram.ps1         显存驻留监控
│       └── README.md              用法
├── conversion/
│   └── *.conversion.json          本仓库实测转换的完整报告（脱敏后）
└── LICENSE                        Apache-2.0（沿用上游）
```

**引擎成品（ninfer-serve.exe，sm_89）** 不入库（约 1.07 GB），见本仓库
[Releases](../../releases) 页面的附件，下载后按部署文档第 6 节组装即可跳过编译。
**模型权重（11.6 GB .ninfer）** 不入库，请按 [模型转换指南](docs/模型转换指南.md) 从
HuggingFace 原版 GGUF 自行转换（CPU 上 1 分钟内完成）。

## 快速开始（已编译机器，5 分钟）

```bat
:: 1. 转换模型（详见 docs/模型转换指南.md，约 1 分钟）
:: 2. 组装运行目录（详见 docs/部署文档.md 第 6 节）
:: 3. 启动
set CUDA_VISIBLE_DEVICES=0
D:\ninfer\runtime\engine\ninfer-serve.exe <模型.ninfer> ^
  --model-id qwen3.8-27b --max-context 81920 --prefill-chunk 256 ^
  --cuda-memory-policy strict --kv-dtype rk8v4 --host-cache-mib 6144 ^
  --default-max-tokens 0 --spec mtp --draft-tokens 4 --adaptive-mtp --lookup-ngram 31 ^
  --port 8081
:: API: http://127.0.0.1:8081/v1 （OpenAI / Anthropic 兼容）
```

## 40 系 / 其他显卡适配速查

| 你的显卡 | 引擎二进制 | 需要做的事 |
|---|---|---|
| RTX 4080 / 4090 (sm_89) | **直接复用本仓库 Release 的成品** | 仅需首启重新校准 + 重测显存上限 |
| RTX 4070 Ti / 4070 SUPER (sm_89, 12GB) | 同上 | 显存更小，上下文上限按比例下调（文档第 7 节有方法） |
| RTX 5070 Ti / 5080 / 5090 (sm_120a) | **直接用官方软件包**，无需本仓库 | 换卡后重新校准即可 |
| RTX 30 系 (sm_86) | 需重编译：`CMAKE_CUDA_ARCHITECTURES=86` | 其余流程完全一致 |

详见 [部署文档 · 换显卡适配指南](docs/部署文档.md#9-换显卡适配指南)。

## 环境要求

- Windows 11，NVIDIA 驱动 ≥ R580（实测 616.56）
- 16GB 显存（12GB 可跑，上下文相应缩减）；系统内存建议 32GB（编译 CUDA 算子峰值较高，需 `-j 8` 防溢出，文档有说明）
- 磁盘 ≥ 60GB：源码/构建 ~15GB + 模型 GGUF 12GB + .ninfer 11.6GB + 依赖缓存 ~10GB
- 工具链：VS2022 Build Tools (MSVC v143 **14.44.35207**)、CUDA Toolkit **13.4**、CMake **≥4.4.3**、Ninja、Git、Python 3.11（转换用）、vcpkg（classic 模式）

## 致谢与来源

- 引擎上游：[Neroued/ninfer](https://github.com/Neroued/ninfer) · 汇总线
  [iamwavecut/ninfer-all](https://github.com/iamwavecut/ninfer-all) · 本分支路线来自
  [Ryan-gsq/ninfer-16g-5070ti-5080-5090-qwen3.8-27b-gsq-rco](https://github.com/Ryan-gsq/ninfer-16g-5070ti-5080-5090-qwen3.8-27b-gsq-rco)
  （其文档与软件包构成本项目的基础，本仓库是其 **RTX 40 系适配分支**）
- 模型与量化：Qwen3.8-27B（阿里 Qwen 团队）· GSQ-RCO 量化：ISTA-DASLab / Swift 变体作者
- 本仓库所有改动与实测数据基于 Apache-2.0 开源合规再分发
