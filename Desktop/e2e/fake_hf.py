"""A minimal Hugging Face stand-in for e2e tests: any repo has one small GGUF per common quant, served slowly.

  GET /api/models/<owner>/<repo>/tree/main      -> file listing
  GET /<owner>/<repo>/resolve/main/<file>        -> SIZE bytes, in CHUNK-sized pieces with DELAY seconds between them
                                                    (honours Range so resume works)
"""
import asyncio
import sys

from aiohttp import web

SIZE = 8 * 2**20
CHUNK = 256 * 2**10
DELAY = 0.05  # ~1.6 s for a full download
QUANTS = ("Q4_0", "Q4_K_M")


async def tree(request: web.Request) -> web.Response:
    return web.json_response([{"type": "file", "path": f"model-{q}.gguf", "size": SIZE} for q in QUANTS])


async def resolve(request: web.Request) -> web.StreamResponse:
    start = 0
    if rng := request.headers.get("Range"):
        start = int(rng.split("=")[1].split("-")[0])
    resp = web.StreamResponse(status=206 if start else 200, headers={"Content-Length": str(SIZE - start)})
    await resp.prepare(request)
    sent = start
    while sent < SIZE:
        n = min(CHUNK, SIZE - sent)
        try:
            await resp.write(b"\0" * n)
        except ConnectionResetError:  # the client cancelled
            break
        sent += n
        await asyncio.sleep(DELAY)
    return resp


if __name__ == "__main__":
    app = web.Application()
    app.router.add_get("/api/models/{owner}/{repo}/tree/main", tree)
    app.router.add_get("/{owner}/{repo}/resolve/main/{file}", resolve)
    web.run_app(app, host="127.0.0.1", port=int(sys.argv[1]), print=lambda *_: None)
