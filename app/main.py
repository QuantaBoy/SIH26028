import sys
from pathlib import Path

if __name__ == "__main__":  # `python app/main.py` puts app/ on sys.path, not the project root
    sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncio
import contextlib

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI

from app.routes import api, pages
from app.services.live import collect_forever
from app.services.weather_db import poll_forever

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")  # works however the app is launched


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    """Keep station weather fresh and collect each day's real runs, in the background."""
    tasks = [asyncio.create_task(poll_forever()), asyncio.create_task(collect_forever())]
    yield
    for t in tasks:
        t.cancel()


app = FastAPI(title="SIH26028", lifespan=lifespan)
app.include_router(pages.router)
app.include_router(api.router, prefix="/api")


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8028, reload=True)  # 0.0.0.0 = reachable from other devices on the LAN
