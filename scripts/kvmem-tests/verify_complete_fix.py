# -*- coding: utf-8 -*-
"""完全修复版严谨验证（8091 dev 实例）
验证目标：MTP 投机 + host-backed 超池采纳 同时工作，且生成内容正确、无崩溃。
方法：3 个独立会话循环（72K/129K/72K），每循环 = 冷预填 → 同前缀重发（原炸点）
      → 换针续问（跨深度检索）→ 逐轮核对答案 + 引擎日志证据。
"""
import sys, os, json, urllib.request, time
sys.path.insert(0, os.path.dirname(__file__))
from common import build_doc

API = "http://127.0.0.1:8091/v1/chat/completions"

def ask(messages, mx=300, timeout=1500):
    body = {"model": "qwen3.8-27b", "messages": messages, "max_tokens": mx, "temperature": 0}
    t0 = time.time()
    try:
        req = urllib.request.Request(API, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        r = json.load(urllib.request.urlopen(req, timeout=timeout))
        return {"ok": True, "content": r["choices"][0]["message"].get("content") or "",
                "usage": r.get("usage", {}), "elapsed": time.time() - t0}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:90]}", "elapsed": time.time() - t0}

def alive():
    a = ask([{"role": "user", "content": "ping"}], mx=5, timeout=25)
    return a.get("ok")

def engine_evidence():
    import re
    log = r"D:\ninfer\kvmem-dev-run.log"
    try:
        s = open(log, "r", encoding="utf-8", errors="replace").read()
    except FileNotFoundError:
        return {}
    return {
        "adopt_host_backed": len(re.findall(r"adopt host-backed", s)),
        "adopt_declined": len(re.findall(r"adopt declined", s)),
        "not_materializable": len(re.findall(r"not materializable", s)),
        "invariant": len(re.findall(r"invariant was violated", s)),
        "mtp_accepted": (re.findall(r"mtp accepted (\d+)/(\d+)", s)[-1] if re.findall(r"mtp accepted", s) else None),
    }

if __name__ == "__main__":
    cycles = [
        {"tok": 72000,  "seed": 4242, "code": "VR-01", "depth": 0.30},
        {"tok": 129000, "seed": 9090, "code": "VR-02", "depth": 0.45},
        {"tok": 72000,  "seed": 1717, "code": "VR-03", "depth": 0.10},
    ]
    all_pass = True
    for ci, c in enumerate(cycles, 1):
        doc, _, _ = build_doc(c["tok"], [(c["depth"], f"CONFIDENTIAL: vault D code is {c['code']}.")],
                              seed=c["seed"])
        q = doc + "\n\nWhat is the launch code for vault D? Code only."
        r1 = ask([{"role": "user", "content": q}])
        p1 = c["code"] in r1.get("content", "")
        r2 = ask([{"role": "user", "content": q}])          # 同前缀重发（原炸点）
        p2 = c["code"] in r2.get("content", "")
        r3 = ask([{"role": "user", "content": q},
                  {"role": "assistant", "content": r2.get("content", "")},
                  {"role": "user", "content": "Repeat the vault D code. Code only."}])
        p3 = c["code"] in r3.get("content", "")
        cycle_pass = all([r1["ok"], r2["ok"], r3["ok"], p1, p2, p3])
        all_pass = all_pass and cycle_pass
        print(f"循环{ci} ({c['tok']//1000}K, 针@{int(c['depth']*100)}%): "
              f"t1={'OK' if r1['ok'] and p1 else 'FAIL'}({r1['elapsed']:.0f}s) "
              f"t2重发={'OK' if r2['ok'] and p2 else 'FAIL'}({r2['elapsed']:.1f}s) "
              f"t3续问={'OK' if r3['ok'] and p3 else 'FAIL'}({r3['elapsed']:.0f}s) "
              f"{'=> PASS' if cycle_pass else '=> FAIL'}")
        if not r2["ok"]:
            print("  引擎存活:", alive())
    ev = engine_evidence()
    print(f"\n引擎证据: adopt_host_backed={ev['adopt_host_backed']} "
          f"adopt_declined={ev['adopt_declined']} not_materializable={ev['not_materializable']} "
          f"invariant={ev['invariant']} mtp_accepted={ev['mtp_accepted']}")
    verdict = all_pass and ev["not_materializable"] == 0 and ev["invariant"] == 0 and ev["adopt_host_backed"] > 0
    print("总体判定:", "✅ 完全修复验证通过" if verdict else "❌ 未通过（见上）")
