# -*- coding: utf-8 -*-
"""复现 dsh 的畸形工具调用：带 tools 的请求 x3，检查 tool_calls 合法性"""
import json, urllib.request, time

API = "http://127.0.0.1:8081/v1/chat/completions"

TOOLS = [
    {"type": "function", "function": {"name": "write_file",
      "description": "Write text content to a file at the given absolute path",
      "parameters": {"type": "object", "properties": {
          "path": {"type": "string", "description": "absolute file path"},
          "content": {"type": "string", "description": "file content"}},
        "required": ["path", "content"]}}},
    {"type": "function", "function": {"name": "run_command",
      "description": "Run a shell command and return stdout/stderr",
      "parameters": {"type": "object", "properties": {
          "command": {"type": "string"}}, "required": ["command"]}}},
    {"type": "function", "function": {"name": "list_dir",
      "description": "List directory entries",
      "parameters": {"type": "object", "properties": {
          "path": {"type": "string"}}, "required": ["path"]}}},
]

def ask(messages, tools=None, temperature=0.7):
    body = {"model": "qwen3.8-27b", "messages": messages, "max_tokens": 2000,
            "temperature": temperature, "stream": False}
    if tools:
        body["tools"] = tools
    req = urllib.request.Request(API, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    r = json.load(urllib.request.urlopen(req, timeout=600))
    ch = r["choices"][0]
    msg = ch["message"]
    return {"finish": ch.get("finish_reason"), "tool_calls": msg.get("tool_calls"),
            "content_head": (msg.get("content") or "")[:150],
            "elapsed": time.time() - t0, "usage": r.get("usage", {})}

if __name__ == "__main__":
    task = "在 C:\\Users\\W\\Desktop\\test 目录下创建一个鹈鹕骑自行车的 HTML 动画页面。"
    for i, temp in enumerate([1.0, 0.7, 0.3], 1):
        m = [{"role": "user", "content": task}]
        r = ask(m, tools=TOOLS, temperature=temp)
        tc = r["tool_calls"]
        ok = bool(tc) and all(t.get("function", {}).get("name") in
                              {"write_file", "run_command", "list_dir"} for t in (tc or []))
        print(f"[temp={temp}] finish={r['finish']} tool_calls={'None' if not tc else [t['function']['name'] for t in tc]} "
              f"合法={ok} {r['elapsed']:.0f}s")
        if not ok:
            print("  content头:", repr(r["content_head"][:100]))
