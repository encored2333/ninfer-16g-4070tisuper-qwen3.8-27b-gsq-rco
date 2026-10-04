# -*- coding: utf-8 -*-
"""开发版引擎验证脚本（8091，不动 8081 的在线实例）"""
import json, urllib.request, time, sys

API = "http://127.0.0.1:8091/v1/chat/completions"

def chat(messages, max_tokens=300, temperature=0, timeout=900):
    body = {"model": "qwen3.8-27b", "messages": messages, "max_tokens": max_tokens,
            "temperature": temperature}
    t0 = time.time()
    try:
        req = urllib.request.Request(API, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        r = json.load(urllib.request.urlopen(req, timeout=timeout))
        return {"ok": True, "content": r["choices"][0]["message"].get("content") or "",
                "usage": r.get("usage", {}), "elapsed": time.time() - t0}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "elapsed": time.time() - t0}

def build_doc(target_tokens, needle_depth, needle, seed=0):
    per = 19.4
    n = int(target_tokens / per)
    lines = []
    for i in range(1, n + 1):
        lines.append(f"Log entry {i:05d}: routine telemetry nominal, sector {(i * 7 + seed) % 97} levels stable, calibration drift {((i * 13) % 100) / 100:.2f} within tolerance, no action required.")
    lines[min(max(int(n * needle_depth), 0), n - 1)] = needle
    return "\n".join(lines)

if __name__ == "__main__":
    code = "DEV-01"
    doc = build_doc(30000, 0.3, f"CONFIDENTIAL: vault D code is {code}.", seed=909)
    q = doc + "\n\nWhat is the launch code for vault D? Code only."
    r1 = chat([{"role": "user", "content": q}])
    print(f"turn1: ok={r1['ok']} hit={code in r1.get('content', '')} {r1['elapsed']:.0f}s")
    r2 = chat([{"role": "user", "content": q}])
    print(f"turn2 same-prefix (the old crash point): ok={r2['ok']} hit={code in r2.get('content', '')} {r2['elapsed']:.1f}s")
    r3 = chat([{"role": "user", "content": q}, {"role": "assistant", "content": r1.get("content", "")},
               {"role": "user", "content": "And count 1 to 40, numbers only."}], max_tokens=400)
    print(f"turn3 multi-turn+long out: ok={r3['ok']} out={r3.get('usage', {}).get('completion_tokens')} tok {r3['elapsed']:.0f}s")
