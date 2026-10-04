# -*- coding: utf-8 -*-
"""疲劳加强版：10 轮工具循环 + 每轮回灌工具结果 + 中途塞长文档（模拟真实 dsh
会话的历史累积与中段检索压力）。判定：全程合法工具调用 + 无畸形。"""
import sys, os, json, urllib.request, time
sys.path.insert(0, os.path.dirname(__file__))
from common import build_doc

API = "http://127.0.0.1:8081/v1/chat/completions"
TOOLS = [{"type": "function", "function": {"name": n, "description": d,
          "parameters": {"type": "object", "properties": {k: {"type": "string"} for k in args},
                         "required": args}}}
         for n, d, args in [
             ("write_file", "Write a file", ["path", "content"]),
             ("run_command", "Run a shell command", ["command"]),
             ("list_dir", "List directory", ["path"]),
             ("read_file", "Read a file", ["path"]),
             ("search_web", "Search the web", ["query"]),
             ("open_browser", "Open a browser page", ["url"]),
             ("python_repl", "Run python code", ["code"])]]
LEGAL = {t["function"]["name"] for t in TOOLS}

def ask(msgs, mx=16384):
    body = {"model": "qwen3.8-27b", "messages": msgs, "max_tokens": mx,
            "temperature": 0.7, "tools": TOOLS}
    t0 = time.time()
    try:
        r = json.load(urllib.request.urlopen(urllib.request.Request(
            API, data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"}), timeout=1200))
        ch = r["choices"][0]
        tc = ch["message"].get("tool_calls")
        return {"ok": True, "finish": ch.get("finish_reason"),
                "names": [t["function"]["name"] for t in tc] if tc else None,
                "content": ch["message"].get("content") or "", "elapsed": time.time() - t0}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:80]}",
                "elapsed": time.time() - t0}

if __name__ == "__main__":
    task = "在 C:/Users/W/Desktop/test 下创建 pelican.html：一个鹈鹕骑自行车的动画页面。"
    msgs = [{"role": "user", "content": task}]
    # 中途塞一份 45K 长文档（把会话推过窗口边界，制造中段检索压力）
    doc, _, _ = build_doc(45000, [(0.5, "CONFIDENTIAL: archive pin is LC-77.")], seed=313)
    fails = 0
    for i in range(1, 11):
        if i == 5:
            msgs.append({"role": "user",
                         "content": doc + "\n\n看完后继续做动画任务。archive pin 是什么？"})
        r = ask(msgs)
        legal = bool(r.get("names")) and all(n in LEGAL for n in (r.get("names") or []))
        tag = "OK " if (r.get("ok") and legal) else "FAIL"
        if not (r.get("ok") and legal):
            fails += 1
        extra = ""
        if i == 5:
            extra = f" pin命中={'LC-77' in r.get('content','')}"
        print(f"轮{i:2d}: [{tag}] finish={r.get('finish')} tools={r.get('names')} "
              f"{r.get('elapsed', 0):.0f}s{extra}")
        if not r.get("ok"):
            print("   err:", r.get("error", ""))
            break
        if legal:
            for j, t in enumerate(r["names"]):
                msgs.append({"role": "assistant", "content": r.get("content", "")[:200],
                             "tool_calls": [{"id": f"c{i}_{j}", "type": "function",
                                             "function": {"name": t, "arguments": "{}"}}]})
                msgs.append({"role": "tool", "tool_call_id": f"c{i}_{j}",
                             "content": f"OK: done (result {i})"})
        else:
            print("   畸形 content 头:", repr((r.get("content") or "")[:100]))
            # 给一次自我纠正机会（模拟 dsh 回传错误）
            msgs.append({"role": "assistant", "content": (r.get("content") or "")[:300]})
            msgs.append({"role": "user", "content": "上次工具调用格式错误，请用标准 tool_calls 重新调用。"})
    print(f"\n判定: {'✅ 10 轮疲劳测试通过' if fails == 0 else f'❌ {fails} 轮失败'}")
