import sys
from pathlib import Path

if __name__ == "__main__":  # `python app/main.py` puts app/ on sys.path, not the project root
    sys.path.insert(0, str(Path(__file__).parent.parent))

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from app.routes import api

load_dotenv(Path(__file__).parent.parent / ".env")  # works however the app is launched

app = FastAPI(title="SIH26028")
app.include_router(api.router, prefix="/api")


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/docs")


if __name__ == "__main__":
    uvicorn.run("app.main:app", reload=True)
