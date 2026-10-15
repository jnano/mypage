"""실행: cd backend && uv run python -m app.worker  (SIGINT·SIGTERM 으로 하던 일을 마치고 멈춘다)"""

import asyncio
import logging
import signal

from app.db.session import engine
from app.worker.main import run


async def _main() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    try:
        await run(stop)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(_main())
