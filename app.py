"""Fabric Mod Check, adapted from the course agents-sdk-web starter."""

import asyncio
import logging
import json
import os
import tempfile
import uuid
from pathlib import Path

import uvicorn
from agents import SQLiteSession
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from research import CATALOG, investigate

ROOT = Path(__file__).parent
EXAMPLES = json.loads((ROOT / "data" / "examples.json").read_text(encoding="utf-8"))
SESSION_DB = os.getenv("SESSION_DB", str(Path(tempfile.gettempdir()) / "fabric-mod-check.sqlite3"))
REQUEST_TIMEOUT = 220
log = logging.getLogger(__name__)

app = FastAPI(title="Fabric Mod Check")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2400)
    session_id: str | None = Field(default=None, max_length=64)

    @field_validator("message", mode="before")
    @classmethod
    def strip_message(cls, value):
        return value.strip() if isinstance(value, str) else value


class ChatResponse(BaseModel):
    response: str
    session_id: str
    tool_calls: list[dict]


@app.get("/")
def index():
    return FileResponse(ROOT / "index.html")


@app.get("/health")
def health():
    return {"status": "ok", "versions": len(CATALOG.versions)}


@app.get("/catalog")
def catalog():
    summary = CATALOG.summary()
    for mod in summary["mods"]:
        mod["versions"] = CATALOG.list_versions(mod["slug"])["versions"]
    summary["examples"] = {example["id"]: example["question"] for example in EXAMPLES}
    return summary


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    session_id = request.session_id or str(uuid.uuid4())
    session = SQLiteSession(session_id, SESSION_DB)
    try:
        history = await session.get_items(limit=4)
        recent = [
            {"role": message.get("role"), "content": str(message.get("content", ""))[:2400]}
            for message in history
        ]
        try:
            response, tool_calls = await asyncio.wait_for(
                investigate(request.message, history=recent), timeout=REQUEST_TIMEOUT,
            )
        except TimeoutError:
            response = "The investigation timed out. Try asking about one pair of exact versions."
            tool_calls = []
        except Exception as error:
            log.error("Research failed: %s", type(error).__name__)
            response = "The research model is temporarily unavailable. Please try again."
            tool_calls = []
        else:
            await session.add_items([
                {"role": "user", "content": request.message},
                {"role": "assistant", "content": response},
            ])
    finally:
        session.close()
    return ChatResponse(response=response, session_id=session_id, tool_calls=tool_calls)


@app.post("/clear")
async def clear(session_id: str | None = None):
    if session_id:
        session = SQLiteSession(session_id, SESSION_DB)
        try:
            await session.clear_session()
        finally:
            session.close()
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run(app, host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "8000")))
