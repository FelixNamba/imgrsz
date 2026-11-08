"""HTTP server in the bot process: static site + public stats."""
import logging
from pathlib import Path

from aiohttp import web

from .config import config

log = logging.getLogger("imgrsz.web")
WEB_ROOT = Path("/app/web").resolve()


async def stats(request: web.Request) -> web.StreamResponse:
    path = Path(config.stats_path)
    if not path.is_file():
        raise web.HTTPNotFound()
    return web.FileResponse(path, headers={"Cache-Control": "no-store"})


async def static(request: web.Request) -> web.StreamResponse:
    rel = request.match_info.get("tail", "")
    candidate = (WEB_ROOT / rel).resolve()
    if candidate != WEB_ROOT and WEB_ROOT not in candidate.parents:
        raise web.HTTPNotFound()
    if candidate.is_file():
        return web.FileResponse(candidate)
    if candidate.is_dir() and (candidate / "index.html").is_file():
        return web.FileResponse(candidate / "index.html")
    index = WEB_ROOT / "index.html"
    if index.is_file():
        return web.FileResponse(index)
    raise web.HTTPNotFound()


async def start_web(host: str = "0.0.0.0", port: int = 8080) -> web.AppRunner:
    app = web.Application()
    app.router.add_get("/stats.json", stats)
    app.router.add_get("/{tail:.*}", static)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    log.info("web server started on %s:%s", host, port)
    return runner

if __name__ == "__main__":
    import asyncio

    async def _main() -> None:
        await start_web()
        await asyncio.Event().wait()

    asyncio.run(_main())
