# toolcall-probe · 工具调用解析器黑盒探针

无需 GPU、无需 CUDA、无需 CMake 的小型探针集，直接把解析器翻译单元编译成独立可执行文件，
用于在改动 `tool_call_parser.cpp` 时做秒级回归。配套说明见
[`docs/工具调用解析加固-A至G类问题与修复.md`](../../docs/工具调用解析加固-A至G类问题与修复.md)。

## 构建

```bat
build-repo.bat <engine-source-root>
rem 例：build-repo.bat D:\ninfer\src-kvmem
```

需要 Visual Studio 2022（v143）的 C++ 工作负载。`vcvars64.bat` 不在默认位置时，
先 `set VSVARS=<完整路径>` 再运行。

## 三个探针

| 可执行文件 | 覆盖 | 判定 |
| --- | --- | --- |
| `probe.exe` | 51 种形态的整段解析结果 | 与非回归基线逐行对比，差异应仅为预期项 |
| `probe_ae.exe` | A 类（控制 token 污染 / 裸词头部 / wrapper 嵌套 / CDATA）与 E 类（大小写漂移 / 非法名回显） | A1–A8、E1、E2 必须 `calls=1`；反例 N1、N2 必须 `calls=0` 且内容原样 |
| `probe_g3.exe` | 流式解码逐字节一致性 | 每组文本按 1 至 23 字节切块，流式结果必须与非流式完全一致；输出 `G3: no byte loss/duplication at any chunk size` 即通过 |

## 用法

```bat
probe.exe        > after.txt
fc baseline.txt after.txt        rem 只应出现预期内的差异
probe_ae.exe
probe_g3.exe
```

`probe.exe` 每个用例打印一行 `=== 用例名`，随后是 `is_tool_call_response`、`content`、
每个调用的 `name`/`args`，以及全部诊断字段（`marker_seen`、`recovered`、`reason`、
`empty_omitted`、`dup_repaired` 等），便于人工核对。

## 与官方测试的分工

本目录的探针是**黑盒回归**，覆盖形态广、起步快；引擎自带的
`tests/test_tool_call_parser.cpp`（CMake 配置 `BUILD_TESTING=ON` 后构建
`ninfer_tool_call_parser_test`）是**契约测试**，两者都要跑：契约测试必须 `exit=0`，
探针差异必须全部是预期项。
