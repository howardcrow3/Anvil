"""A scripted OpenAI-compatible chat server for e2e tests: no network, deterministic replies.

  • last message is a tool result  -> "Tool said: <content>"
  • user text contains "run"       -> calls the `bash` tool with `echo hello-from-tool`
  • user text contains "fail"      -> HTTP 500 (to exercise the error path)
  • anything else                  -> a short markdown reply
"""
import json
import sys

from aiohttp import web


def sse(obj) -> bytes:
    return f"data: {json.dumps(obj)}\n\n".encode()


def chunk(delta, finish=None):
    return {"id": "fake", "object": "chat.completion.chunk", "model": "fake-model",
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}


async def completions(request: web.Request) -> web.StreamResponse:
    body = await request.json()
    messages = body["messages"]
    last = messages[-1]
    user_texts = [m["content"] for m in messages if m["role"] == "user" and isinstance(m.get("content"), str)]
    prompt = user_texts[-1].lower() if user_texts else ""

    if last["role"] != "tool" and "fail" in prompt:
        return web.json_response({"error": {"message": "fake model failure"}}, status=500)

    resp = web.StreamResponse(headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache"})
    await resp.prepare(request)
    if last["role"] == "tool":
        for piece in ("Tool said: ", str(last["content"]).strip()):
            await resp.write(sse(chunk({"content": piece})))
        await resp.write(sse(chunk({}, "stop")))
    elif "run" in prompt:
        await resp.write(sse(chunk({"content": "Running a command. "})))
        await resp.write(sse(chunk({"tool_calls": [{
            "index": 0, "id": "call_1", "type": "function",
            "function": {"name": "bash", "arguments": json.dumps({"command": "echo hello-from-tool"})}}]})))
        await resp.write(sse(chunk({}, "tool_calls")))
    else:
        for piece in ("Hello ", "**world**", "! Here is `code`:\n\n```python\nprint('hi')\n```\n"):
            await resp.write(sse(chunk({"content": piece})))
        await resp.write(sse(chunk({}, "stop")))
    await resp.write(b"data: [DONE]\n\n")
    return resp


async def models(_request: web.Request) -> web.Response:
    return web.json_response({"object": "list", "data": [{"id": "fake-model", "object": "model"}]})


if __name__ == "__main__":
    app = web.Application()
    app.router.add_post("/v1/chat/completions", completions)
    app.router.add_get("/v1/models", models)
    web.run_app(app, host="127.0.0.1", port=int(sys.argv[1]), print=lambda *_: None)
