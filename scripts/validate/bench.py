#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NInfer 推理服务验证/基准脚本（仅 Python 标准库，无第三方依赖）。

用法:
    py -3.11 bench.py --mode quick            # 健康检查 + 1 条短对话（TTFT/decode/输出 token 数）
    py -3.11 bench.py --mode full             # 额外: decode 专项 + ~4K 输入 + ~64K 输入 + 5070Ti 对比表
    py -3.11 bench.py --base http://127.0.0.1:18081 --model Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp

API 形状求证依据（D:/ninfer/src 源码，非猜测）:
  - GET  /health        -> 200 {"status":"ok"} / 503 {"status":"unavailable"}
                           (src/serve/http_server.cpp: HttpServer 路由注册 + handle_health)
  - GET  /v1/models     -> {"object":"list","data":[{"id":"<--model-id 注册名>",...}]}
  - POST /v1/chat/completions  OpenAI 兼容; 流式为 SSE: 逐行 "data: {...}", 终止行 "data: [DONE]"
                           (src/serve/openai_chat_response.cpp: OpenAIChatStream::finish)
  - 请求字段: model 可省略(单模型常驻); 一旦给出必须与 --model-id 完全一致, 否则 404 model_not_found
                           (src/serve/openai_chat_request.cpp parse_chat_completion_request;
                            src/serve/openai_common.cpp validate_openai_model)
  - max_tokens / max_completion_tokens 均支持; stream_options.include_usage 支持
                           (src/serve/openai_chat_request.cpp parse_output_limit / parse_stream_options)
  - include_usage 时最后一个 chunk 携带顶层 usage + timings:
      usage:   prompt_tokens / completion_tokens / total_tokens
      timings: prompt_n / prompt_ms / prompt_per_second / predicted_n / predicted_ms /
               predicted_per_second          (openai_chat_response.cpp usage_chunk + timings_json)
  - 为什么选流式: 官方测速口径 (docs/rtx-5070ti-windows.md):
      预填充速度 = 未缓存输入 tokens / 引擎 prompt 时间  -> timings.prompt_per_second
      解码速度   = (输出 tokens - 1) / 引擎 predicted 时间 -> timings.predicted_per_second
      客户端 TTFT = 从发出请求计到第一个非空思考/正文/工具流事件 -> 必须流式才能测。
    非流式响应同样带 usage+timings(make_chat_completion_response), 但无法测客户端 TTFT。
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

DEFAULT_BASE = "http://127.0.0.1:18081"
DEFAULT_MODEL = "Qwen3.8-27B-GSQ-RCO-IQ3_S-mtp"

# 官方 5070 Ti 实测参考(docs/rtx-5070ti-windows.md 64K 输入档, 512 输出):
#   XXS 64K/strict: prefill 1695.4 tok/s, decode 99.36 tok/s, 客户端 TTFT 36.918 s
#   S   64K/strict: prefill 1666.2 tok/s, decode 105.59 tok/s, 客户端 TTFT 37.557 s
REF_5070TI = {
    "prefill_64k": 1695.4,
    "decode_64k_low": 99.36,
    "decode_64k_high": 105.59,
    "ttft_64k_s": 36.92,
}
EXPECTED_RATIO = 0.75  # RTX 4070 Ti SUPER 预期约为 5070 Ti 的 75%

# 长输入构造方式: 固定英文句子按 ~4 字符/token 估算重复到目标 token 量级,
# 实际 token 数以服务端返回的 usage.prompt_tokens 为准(打印出来)。
SEED_SENTENCE = (
    "The quick brown fox jumps over the lazy dog near the harbor, while a curious "
    "pelican watches the fishing boats and counts the waves in complete silence. "
)
SEED_APPROX_TOKENS = max(1, len(SEED_SENTENCE) // 4)

TAIL_INSTRUCTION = (
    "\n\n请完全忽略上面的全部内容，直接从 1 数到 200，每行输出一个数字，"
    "不要输出任何其他文字或解释。"
)


class BenchError(Exception):
    """带用户可读说明的基准错误。"""


def service_down_error(base, reason):
    return BenchError(
        "[服务未启动] 无法连接 {base} ({reason})。\n"
        "  排查提示:\n"
        "  1. 若用 NInfer 管理器启动: 打开管理页 http://127.0.0.1:8090 选择配置启动模型;\n"
        "     推理 API 默认地址是 http://127.0.0.1:18081/v1 (docs/rtx-5070ti-windows.md)。\n"
        "  2. 若手动启动: ninfer-serve --host 127.0.0.1 --port 18081 --model <模型文件> ...\n"
        "  3. 确认服务进程存在、端口正确、未被防火墙拦截。\n"
        "  4. 可运行同目录 watch_vram.ps1 观察显存, 确认模型是否已加载。".format(
            base=base, reason=reason
        )
    )


# ---------------------------------------------------------------- HTTP 工具

def http_get_json(base, path, api_key="", timeout=15.0):
    url = base + path
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = "Bearer " + api_key
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "replace")), resp.status
    except urllib.error.HTTPError as exc:
        detail = exc.read(500).decode("utf-8", "replace")
        return {"_http_error": exc.code, "_detail": detail}, exc.code
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise service_down_error(base, reason) from None
    except (TimeoutError, OSError) as exc:  # socket 层超时/中断
        raise service_down_error(base, exc) from None


def chat_stream_once(base, model, messages, max_tokens, api_key, timeout, label):
    """发一次流式 /v1/chat/completions, 边收边测 TTFT, 返回结果摘要 dict。"""
    body = {
        "model": model,
        "messages": messages,
        "max_tokens": int(max_tokens),
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    url = base + "/v1/chat/completions"
    data = json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
    if api_key:
        headers["Authorization"] = "Bearer " + api_key
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")

    t0 = time.perf_counter()
    ttft = None
    text_chars = 0
    finish_reason = None
    usage = None
    timings = None
    saw_done = False
    t_last_event = t0

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content_type = resp.headers.get("Content-Type", "")
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                payload = line[len("data:"):].strip()
                if payload == "[DONE]":
                    saw_done = True
                    break
                try:
                    chunk = json.loads(payload)
                except ValueError:
                    continue
                t_last_event = time.perf_counter()
                # usage chunk: 顶层 usage 非 null, 且携带最终 timings
                if chunk.get("usage") is not None:
                    usage = chunk["usage"]
                    timings = chunk.get("timings") or timings
                choices = chunk.get("choices") or []
                if choices:
                    choice = choices[0]
                    delta = choice.get("delta") or {}
                    piece = delta.get("content") or delta.get("reasoning_content") or ""
                    if piece:
                        text_chars += len(piece)
                        if ttft is None:
                            ttft = t_last_event - t0
                    if choice.get("finish_reason"):
                        finish_reason = choice["finish_reason"]
    except urllib.error.HTTPError as exc:
        detail = exc.read(500).decode("utf-8", "replace")
        raise BenchError(
            "HTTP {code} 来自 {url}\n响应: {detail}".format(code=exc.code, url=url, detail=detail)
        ) from None
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise service_down_error(base, reason) from None
    except (TimeoutError, OSError) as exc:
        if ttft is None:
            raise BenchError(
                "[超时] {label}: {timeout}s 内未等到首个流事件(可能是 prefill 太慢或 timeout 太小)。"
                " 可用 --timeout 调大。底层错误: {exc}".format(label=label, timeout=timeout, exc=exc)
            ) from None
        raise BenchError(
            "[流中断] {label}: 已收到首 token 后连接中断/超时: {exc}".format(label=label, exc=exc)
        ) from None

    t_total = time.perf_counter() - t0
    result = {
        "label": label,
        "ttft": ttft,
        "total": t_total,
        "text_chars": text_chars,
        "finish_reason": finish_reason,
        "usage": usage or {},
        "timings": timings or {},
        "saw_done": saw_done,
    }
    if ttft is None:
        raise BenchError(
            "[异常] {label}: 连接正常但从未收到非空流事件(总等待 {t:.1f}s)。"
            " 检查模型是否为纯思考卡死, 或服务端日志。".format(label=label, t=t_total)
        )
    if not saw_done:
        print("  [警告] {label}: 流未以 [DONE] 结束, 结果可能不完整。".format(label=label))
    return result


# ---------------------------------------------------------------- 报告辅助

def fmt(value, pattern="{:.1f}", missing="n/a"):
    if value is None:
        return missing
    return pattern.format(value)


def print_case_result(res):
    usage = res["usage"]
    timings = res["timings"]
    prompt_tokens = usage.get("prompt_tokens")
    completion_tokens = usage.get("completion_tokens")
    engine_prompt_tps = timings.get("prompt_per_second")
    engine_pred_tps = timings.get("predicted_per_second")
    client_decode_tps = None
    if completion_tokens and res["ttft"] is not None and res["total"] > res["ttft"]:
        client_decode_tps = max(0, completion_tokens - 1) / (res["total"] - res["ttft"])
    print("  实际输入 tokens   : {}".format(prompt_tokens if prompt_tokens is not None else "n/a"))
    print("  输出 tokens       : {}".format(completion_tokens if completion_tokens is not None else "n/a"))
    print("  客户端 TTFT       : {} s".format(fmt(res["ttft"], "{:.3f}")))
    print("  prefill (引擎)    : {} tok/s".format(fmt(engine_prompt_tps, "{:.1f}")))
    print("  decode  (引擎)    : {} tok/s".format(fmt(engine_pred_tps, "{:.2f}")))
    print("  decode  (客户端)  : {} tok/s".format(fmt(client_decode_tps, "{:.2f}")))
    print("  总耗时            : {} s".format(fmt(res["total"], "{:.2f}")))
    print("  finish_reason     : {}".format(res["finish_reason"] or "n/a"))


def collect_metrics(res):
    """从单次结果提取 (prompt_tokens, completion_tokens, ttft, prefill_tps, decode_tps)。"""
    usage = res["usage"]
    timings = res["timings"]
    return (
        usage.get("prompt_tokens"),
        usage.get("completion_tokens"),
        res["ttft"],
        timings.get("prompt_per_second"),
        timings.get("predicted_per_second"),
    )


def build_long_messages(target_tokens):
    reps = max(1, -(-int(target_tokens) // SEED_APPROX_TOKENS))
    filler = SEED_SENTENCE * reps
    approx = reps * SEED_APPROX_TOKENS
    messages = [
        {
            "role": "user",
            "content": filler + TAIL_INSTRUCTION,
        }
    ]
    return messages, approx, reps


def print_comparison(long_res):
    print("=" * 78)
    print("与 RTX 5070 Ti 官方参考对比 (64K 输入档, docs/rtx-5070ti-windows.md)")
    print("=" * 78)
    if long_res is None:
        print("64K 用例未运行, 无对比数据。")
        return
    _, _, ttft, prefill_tps, decode_tps = collect_metrics(long_res)
    ref = REF_5070TI
    ratio_ref_prefill = ref["prefill_64k"] * EXPECTED_RATIO
    ratio_ref_dec_lo = ref["decode_64k_low"] * EXPECTED_RATIO
    ratio_ref_dec_hi = ref["decode_64k_high"] * EXPECTED_RATIO

    prefill_ratio = ("{:.0%}".format(prefill_tps / ref["prefill_64k"])
                     if prefill_tps else "n/a")
    decode_ref_mid = (ref["decode_64k_low"] + ref["decode_64k_high"]) / 2.0
    decode_ratio = ("{:.0%}".format(decode_tps / decode_ref_mid)
                    if decode_tps else "n/a")

    rows = [
        ("Prefill tok/s", "{:,.1f}".format(ref["prefill_64k"]),
         fmt(prefill_tps, "{:,.1f}"), prefill_ratio,
         "~{:.0f}".format(ratio_ref_prefill)),
        ("Decode tok/s", "{:.1f} - {:.1f}".format(ref["decode_64k_low"], ref["decode_64k_high"]),
         fmt(decode_tps, "{:.1f}"), decode_ratio,
         "~{:.1f} - {:.1f}".format(ratio_ref_dec_lo, ratio_ref_dec_hi)),
        ("客户端 TTFT s", "~{:.1f}".format(ref["ttft_64k_s"]),
         fmt(ttft, "{:.1f}"), "-", "-"),
    ]
    widths = [16, 16, 12, 10, 16]
    header = ("指标", "5070Ti 参考", "本机实测", "实测/参考", "75% 预期")
    line = "  ".join(str(h).ljust(w) for h, w in zip(header, widths))
    print(line)
    print("-" * len(line))
    for row in rows:
        print("  ".join(str(c).ljust(w) for c, w in zip(row, widths)))
    print("-" * len(line))
    print("说明: RTX 4070 Ti SUPER 预期约为 5070 Ti 的 {}。decode 引擎口径 =".format(EXPECTED_RATIO))
    print("(输出-1)/predicted 时间, 与官方一致; 若速度远低于 75% 预期, 多半是显存")
    print("不足触发 Shared 显存回退(mixed), 请用 watch_vram.ps1 查看余量。")


# ---------------------------------------------------------------- 流程

def check_health(base, api_key):
    url_desc = base + "/health"
    try:
        payload, status = http_get_json(base, "/health", api_key=api_key, timeout=15.0)
    except BenchError as exc:
        print("[失败] GET {}".format(url_desc))
        raise
    if status == 200 and payload.get("status") == "ok":
        print("[OK] GET {} -> 200 {{\"status\":\"ok\"}} 服务就绪".format(url_desc))
        return True
    if status == 503:
        print("[失败] GET {} -> 503 服务已启动但引擎不可用(模型可能仍在加载)。".format(url_desc))
        print("       稍等模型加载完成后再试, 或查看服务端日志/管理页 http://127.0.0.1:8090。")
        return False
    print("[失败] GET {} -> {} 异常响应: {}".format(url_desc, status, payload))
    return False


def resolve_model(base, requested, api_key):
    """从 /v1/models 读注册名; 请求的 model 字段必须与之一致, 否则 404。"""
    try:
        payload, status = http_get_json(base, "/v1/models", api_key=api_key, timeout=15.0)
    except BenchError as exc:
        print("[警告] GET /v1/models 失败: {}".format(str(exc).splitlines()[0]))
        print("       继续使用 --model 的值作为请求 model。")
        return requested
    if status == 200:
        data = payload.get("data") or []
        ids = [item.get("id") for item in data if isinstance(item, dict)]
        if ids:
            registered = ids[0]
            print("[OK] 服务端注册模型 id: {}".format(registered))
            if registered != requested:
                print("[警告] --model '{}' 与注册名不一致; 请求改用注册名 '{}'。"
                      .format(requested, registered))
                print("       (model 字段与注册名不一致会返回 404 model_not_found)")
            return registered
        print("[警告] /v1/models 返回空列表, 继续使用 --model 的值。")
        return requested
    print("[警告] GET /v1/models -> {}, 继续使用 --model 的值。".format(status))
    return requested


def run_short_conversation(args, model, label="短对话"):
    messages = [{"role": "user", "content": "用一句话介绍你自己。"}]
    res = chat_stream_once(args.base, model, messages, args.short_max_tokens,
                           args.api_key, args.timeout, label)
    print("  [{}] 请求完成".format(label))
    print_case_result(res)
    return res


def run_decode_case(args, model):
    """decode 专项: 短输入 + 数数指令, 吃满 max_tokens, 测纯解码速度。"""
    messages = [{"role": "user",
                 "content": "从 1 数到 200，每行输出一个数字，不要输出任何解释。"}]
    res = chat_stream_once(args.base, model, messages, args.decode_max_tokens,
                           args.api_key, args.timeout, "decode 专项(短输入)")
    print("  [decode 专项] 请求完成 (max_tokens={})".format(args.decode_max_tokens))
    print_case_result(res)
    return res


def run_long_case(args, model, target_tokens, label):
    messages, approx, reps = build_long_messages(target_tokens)
    print("  [构造] 目标 ~{} tokens: 固定句子({} 字符 ≈ {} tokens) x {} 次 ≈ {} tokens,"
          " 实际以 usage.prompt_tokens 为准".format(
              target_tokens, len(SEED_SENTENCE), SEED_APPROX_TOKENS, reps, approx))
    res = chat_stream_once(args.base, model, messages, args.decode_max_tokens,
                           args.api_key, args.timeout, label)
    print("  [{}] 请求完成".format(label))
    print_case_result(res)
    return res


def main():
    parser = argparse.ArgumentParser(
        description="NInfer 推理服务验证/基准脚本(仅标准库)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=("示例:\n"
                "  py -3.11 bench.py --mode quick\n"
                "  py -3.11 bench.py --mode full --base http://127.0.0.1:18081\n"
                "API 形状依据见文件头部 docstring 与同目录 README.md"))
    parser.add_argument("--base", default=DEFAULT_BASE,
                        help="推理 API 根地址(默认 %(default)s)")
    parser.add_argument("--model", default=DEFAULT_MODEL,
                        help="预期注册模型名(默认 %(default)s); 会先用 /v1/models 校正")
    parser.add_argument("--mode", choices=["quick", "full"], default="quick",
                        help="quick=健康检查+短对话; full=额外 decode 专项+4K+64K+对比表")
    parser.add_argument("--api-key", default="",
                        help="若服务端启用了 --api-key 则必填(默认空)")
    parser.add_argument("--timeout", type=float, default=900.0,
                        help="单请求 socket 超时秒数(默认 %(default)s)")
    parser.add_argument("--short-max-tokens", type=int, default=512,
                        help="短对话 max_tokens 上限(默认 %(default)s)")
    parser.add_argument("--decode-max-tokens", type=int, default=256,
                        help="decode/长输入用例的 max_tokens(默认 %(default)s)")
    parser.add_argument("--mid-tokens", type=int, default=4000,
                        help="full 模式中档输入目标 token 数(默认 %(default)s)")
    parser.add_argument("--long-tokens", type=int, default=65536,
                        help="full 模式长档输入目标 token 数(默认 %(default)s)")
    args = parser.parse_args()

    base = args.base.rstrip("/")
    print("NInfer 基准验证  mode={}  base={}  预期模型={}".format(args.mode, base, args.model))
    print("-" * 78)

    results = {}
    try:
        # 1) 健康检查
        if not check_health(base, args.api_key):
            return 2

        # 2) 校正模型名
        model = resolve_model(base, args.model, args.api_key)
        print("-" * 78)

        # 3) 短对话 (full 模式下兼作 warm-up)
        results["short"] = run_short_conversation(args, model)

        if args.mode == "full":
            print("-" * 78)
            results["decode"] = run_decode_case(args, model)

            print("-" * 78)
            results["mid"] = run_long_case(args, model, args.mid_tokens,
                                           "~{} 输入".format(args.mid_tokens))

            print("-" * 78)
            print("[长输入] 64K 档可能耗时 1 分钟以上(4070 Ti SUPER 预期 TTFT ~50s), 请耐心等待...")
            sys.stdout.flush()
            results["long"] = run_long_case(args, model, args.long_tokens,
                                            "~{} 输入".format(args.long_tokens))

            print()
            print("=" * 78)
            print("结果汇总 (prefill/decode 为引擎 timings 口径, 与官方测法一致)")
            print("=" * 78)
            widths = [22, 14, 12, 12, 18, 18]
            header = ("用例", "输入 tok", "输出 tok", "TTFT s", "prefill tok/s", "decode tok/s")
            print("  ".join(str(h).ljust(w) for h, w in zip(header, widths)))
            for key in ("short", "decode", "mid", "long"):
                res = results.get(key)
                if not res:
                    continue
                pt, ct, ttft, pf, dc = collect_metrics(res)
                row = (res["label"],
                       fmt(pt, "{:,.0f}"),
                       fmt(ct, "{:,.0f}"),
                       fmt(ttft, "{:.2f}"),
                       fmt(pf, "{:,.1f}"),
                       fmt(dc, "{:.2f}"))
                print("  ".join(str(c).ljust(w) for c, w in zip(row, widths)))
            print()
            print_comparison(results.get("long"))
    except BenchError as exc:
        print()
        print(str(exc))
        return 1
    except KeyboardInterrupt:
        print("\n[中断] 用户终止。")
        return 130

    print()
    print("完成。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
