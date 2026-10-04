# -*- coding: utf-8 -*-
"""KVMem 256K 全维度测试 - 公共基础设施"""
import json, os, re, time, subprocess, urllib.request, urllib.error
from datetime import datetime

API = "http://127.0.0.1:8081/v1/chat/completions"
RESULTS = r"D:\ninfer\kvmem-tests\results"
ENGINE_LOG = r"D:\ninfer\kvmem-run.log"      # 当前引擎日志（bat 启动重定向）
FUSE = r"D:\ninfer\kvmem-tests\FUSE.tripped"
os.makedirs(RESULTS, exist_ok=True)

def fuse_tripped():
    """组级熔断：楔死事故后剩余测试组快速结束"""
    return os.path.exists(FUSE)

# ---------------- 题面构造 ----------------

def filler_lines(n, seed=0):
    """生成 n 行互不相同的英文填充日志（约 19 token/行）"""
    out = []
    for i in range(1, n + 1):
        out.append(f"Log entry {i:05d}: routine telemetry nominal, sector {(i * 7 + seed) % 97} levels stable, calibration drift {((i * 13) % 100) / 100:.2f} within tolerance, no action required.")
    return out

def filler_lines_zh(n):
    out = []
    for i in range(1, n + 1):
        out.append(f"日志条目 {i:05d}：例行遥测正常，分区{(i * 7) % 89} 电平稳定，校准漂移 {((i * 13) % 100) / 100:.2f} 在容差范围内，无需处理。")
    return out

LINES_PER_1K = 1000 / 19.4   # 实测约 19.4 token/行（英文）；中文约 22.5 token/行

def build_doc(target_tokens, needles=None, lang="en", seed=0):
    """构造约 target_tokens 的题面；needles: [(depth_pct, text)]"""
    mk = (lambda n: filler_lines_zh(n)) if lang == "zh" else (lambda n: filler_lines(n, seed))
    per = 22.5 if lang == "zh" else 19.4
    n = int(target_tokens / per)
    lines = mk(n)
    placed = []
    for depth, text in (needles or []):
        idx = min(max(int(n * depth), 0), n - 1)
        while idx in placed and idx < n - 1:
            idx += 1
        lines[idx] = text
        placed.append(idx)
    return "\n".join(lines), n, placed

# ---------------- API 客户端 ----------------

_canary_fail_streak = {"n": 0}

def canary(timeout=8):
    """引擎探活：2 秒小请求。失败计连续次数"""
    a = chat([{"role": "user", "content": "ping"}], max_tokens=5, timeout=timeout)
    ok = bool(a.get("ok"))
    _canary_fail_streak["n"] = 0 if ok else _canary_fail_streak["n"] + 1
    return ok

def restart_engine(max_wait=240):
    """熔断模式：不再杀进程（强杀楔死引擎=GPU 掉线，已两次实锤）。
    仅当引擎进程不存在时才允许冷启动新实例；楔死（进程在但不响应）返回 False 由调用方记录。"""
    import subprocess
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq ninfer-serve.exe"],
                         capture_output=True, text=True, timeout=15).stdout
    alive = "ninfer-serve.exe" in out
    if alive:
        print("  [fuse] 引擎进程存活但疑似楔死 —— 拒绝强杀（保护 GPU），熔断")
        return False
    logf = open(ENGINE_LOG, "ab")
    subprocess.Popen(["cmd", "/c", r"D:\llamacpp\bat\新建文件夹\start_qwen3_8_27b_gsq_kvmem.bat"],
                     stdin=subprocess.DEVNULL, stdout=logf, stderr=subprocess.STDOUT,
                     creationflags=0x00000008)
    t0 = time.time()
    while time.time() - t0 < max_wait:
        time.sleep(8)
        body = json.dumps({"model": "qwen3.8-27b", "messages": [{"role": "user", "content": "ping"}],
                           "max_tokens": 5}).encode()
        try:
            req = urllib.request.Request(API, data=body, headers={"Content-Type": "application/json"})
            json.load(urllib.request.urlopen(req, timeout=30))
            _canary_fail_streak["n"] = 0
            return True
        except Exception:
            continue
    return False

def chat(messages, max_tokens=300, temperature=0, timeout=420, stream=False, _retry=True):
    """非流式请求。返回 dict: content/usage/status/error/elapsed。
    楔死保护：请求前金丝雀探活，连续 2 次失败自动重启引擎后重试一次。"""
    body = {"model": "qwen3.8-27b", "messages": messages,
            "max_tokens": max_tokens, "temperature": temperature, "stream": stream}
    t0 = time.time()
    if _canary_fail_streak["n"] >= 2 and _retry:
        print("  [canary] 引擎疑似楔死，自动重启...")
        if restart_engine():
            _canary_fail_streak["n"] = 0
            return chat(messages, max_tokens=max_tokens, temperature=temperature,
                        timeout=timeout, stream=stream, _retry=False)
    try:
        req = urllib.request.Request(API, data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        r = json.load(urllib.request.urlopen(req, timeout=timeout))
        msg = r["choices"][0]["message"]
        _canary_fail_streak["n"] = 0
        return {"ok": True, "content": (msg.get("content") or msg.get("reasoning_content") or ""),
                "usage": r.get("usage", {}), "finish": r["choices"][0].get("finish_reason"),
                "elapsed": time.time() - t0}
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode("utf-8", "replace")[:300]
        except Exception:
            detail = ""
        return {"ok": False, "status": e.code, "error": detail, "elapsed": time.time() - t0}
    except Exception as e:
        if _retry:
            ename = type(e).__name__
            transient = ("10061" in str(e) or "10054" in str(e) or "URLError" in ename
                         or "Connection" in ename or "timed out" in str(e) or "timeout" in ename.lower())
            if transient:
                print(f"  [fuse] 传输层异常({ename})，尝试无杀重启（引擎已死时）...")
                if restart_engine():
                    return chat(messages, max_tokens=max_tokens, temperature=temperature,
                                timeout=timeout, stream=stream, _retry=False)
                # 熔断：楔死引擎不杀（护 GPU），本条记失败并拉闸
                open(FUSE, "w").write(datetime.now().isoformat())
                save("F_extra", f"wedge_{int(time.time())}", {"pass": False, "note":
                    f"引擎楔死/失联: {ename} {str(e)[:80]}（熔断不杀，保护 GPU）", "severity": "engine-defect"})
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "elapsed": time.time() - t0}

def chat_stream(messages, max_tokens=512, temperature=0, timeout=1800):
    """流式请求。返回首字节时间/心跳数/内容/总时长"""
    body = {"model": "qwen3.8-27b", "messages": messages,
            "max_tokens": max_tokens, "temperature": temperature, "stream": True}
    t0 = time.time(); first = None; beats = 0; content = []
    try:
        req = urllib.request.Request(API, data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        resp = urllib.request.urlopen(req, timeout=timeout)
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data: "):
                continue
            if first is None:
                first = time.time() - t0
            payload = line[6:]
            if payload == "[DONE]":
                continue
            if line.startswith(":"):
                beats += 1
                continue
            try:
                j = json.loads(payload)
                d = j.get("choices", [{}])[0].get("delta", {})
                c = d.get("content")
                if c:
                    content.append(c)
            except Exception:
                if payload.strip() == "":
                    beats += 1
        return {"ok": True, "ttfb": first, "beats": beats, "content": "".join(content),
                "elapsed": time.time() - t0}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "elapsed": time.time() - t0,
                "ttfb": first, "beats": beats, "content": "".join(content)}

# ---------------- 引擎日志旁证 ----------------

_log_cache = {"size": 0, "lines": []}

def engine_lines(pattern, reread=False):
    """grep 引擎日志（增量缓存），返回匹配行列表。pattern 为正则字符串"""
    try:
        sz = os.path.getsize(ENGINE_LOG)
        if reread or sz != _log_cache["size"]:
            with open(ENGINE_LOG, "r", encoding="utf-8", errors="replace") as f:
                _log_cache["lines"] = f.read().splitlines()
            _log_cache["size"] = sz
        rx = re.compile(pattern, re.I)
        return [l for l in _log_cache["lines"] if rx.search(l)]
    except FileNotFoundError:
        return []

def last_req_lines(n=3):
    return engine_lines(r"req#\d+ done")[-n:]

# ---------------- 资源采样 ----------------

def gpu_mem():
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=index,memory.used,memory.total",
             "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=10).stdout
        rows = [l.strip().split(",") for l in out.strip().splitlines() if l.strip()]
        # CUDA 序 0 = 4070TiS = nvidia-smi 里 16GB 那块
        for idx, used, total in rows:
            if int(total) > 15000:
                return {"used_mib": int(used), "total_mib": int(total)}
        return None
    except Exception:
        return None

def host_mem():
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "[math]::Round((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1MB,2)"],
            capture_output=True, text=True, timeout=15).stdout.strip()
        return {"free_gb": float(out)}
    except Exception:
        return None

# ---------------- 结果落盘 ----------------

def save(group, case, data):
    path = os.path.join(RESULTS, f"{group}.json")
    db = {}
    if os.path.exists(path):
        try:
            db = json.load(open(path, encoding="utf-8"))
        except Exception:
            db = {}
    db[case] = {"ts": datetime.now().isoformat(timespec="seconds"), **data}
    json.dump(db, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    flag = "PASS" if data.get("pass") else ("FAIL" if data.get("pass") is False else "----")
    print(f"[{flag}] {group}.{case}: {data.get('note', '')[:110]}")

def needle_pass(ans, expect):
    if not ans or not ans.get("ok"):
        return False, f"request failed: {ans.get('error', ans.get('status', ''))!s:.80}"
    hit = expect.lower() in (ans.get("content") or "").lower()
    return hit, (expect if hit else f"miss(got:{(ans.get('content') or '')[-60:]!r})")
