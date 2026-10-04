# -*- coding: utf-8 -*-
"""处方配置下的 dsh 式工具循环复测：4 轮工具调用 + 结果回传"""
import json, urllib.request, time

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
task = "在 C:/Users/W/Desktop/test 下创建 pelican.html：一个鹈鹕骑自行车的动画页面，要会动。"

def ask(msgs, mx=16384, temp=0.7):
    body = {"model": "qwen3.8-27b", "messages": msgs, "max_tokens": mx,
            "temperature": temp, "tools": TOOLS}
    t0 = time.time()
    r = json.load(urllib.request.urlopen(urllib.request.Request(
        API, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}), timeout=900))
    ch = r["choices"][0]
    tc = ch["message"].get("tool_calls")
    return (ch.get("finish_reason"), [t["function"]["name"] for t in tc] if tc else None,
            ch["message"].get("content") or "", time.time() - t0)

if __name__ == "__main__":
    msgs = [{"role": "user", "content": task}]
    for i in range(4):
        fin, names, content, dt = ask(msgs)
        ok = bool(names) and all(n in LEGAL for n in (names or []))
        print(f"轮{i+1}: finish={fin} tools={names} 合法={ok} {dt:.0f}s content_len={len(content)}")
        if ok:
            for j, t in enumerate(names):
                msgs.append({"role": "assistant", "content": "",
                             "tool_calls": [{"id": f"c{i}_{j}", "type": "function",
                                             "function": {"name": t, "arguments": "{}"}}]})
                msgs.append({"role": "tool", "tool_call_id": f"c{i}_{j}",
                             "content": f"OK: executed successfully (mock result {i})"})
        else:
            print("  畸形输出 content 头:", repr(content[:120]))
            break
