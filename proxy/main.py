"""
Agent Firewall Proxy
Handles GCP auth and forwards requests to Agent Engine for Beaker and Bunsen.
"""
import os
import logging
import vertexai
from vertexai.preview import reasoning_engines
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("proxy")

PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "stardust-adk")
LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "europe-west2")
BEAKER_ID = os.environ.get("BEAKER_RESOURCE_ID", "")
BUNSEN_ID = os.environ.get("BUNSEN_RESOURCE_ID", "")

vertexai.init(project=PROJECT, location=LOCATION)

app = FastAPI(title="Agent Firewall Proxy")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class PromptRequest(BaseModel):
    text: str


def get_agent_text(response) -> str:
    """Extract text from Agent Engine response."""
    if isinstance(response, list):
        for event in reversed(response):
            if isinstance(event, dict):
                content = event.get("content", {})
                if isinstance(content, dict):
                    parts = content.get("parts", [])
                    for part in parts:
                        if isinstance(part, dict) and part.get("text"):
                            return part["text"]
            if isinstance(event, str):
                return event
    if isinstance(response, dict):
        content = response.get("content", {})
        if isinstance(content, dict):
            parts = content.get("parts", [])
            if parts and parts[0].get("text"):
                return parts[0]["text"]
    return str(response)


@app.post("/beaker/prompt")
async def beaker_prompt(request: PromptRequest):
    if not BEAKER_ID:
        raise HTTPException(status_code=500, detail="BEAKER_RESOURCE_ID not configured")
    logger.info(f"[BEAKER] Prompt: {request.text[:100]}")
    agent = reasoning_engines.ReasoningEngine(BEAKER_ID)
    response = agent.query(user_id="user", message=request.text)
    text = get_agent_text(response)
    logger.info(f"[BEAKER] Response: {text[:100]}")
    return {"text": text}


@app.post("/bunsen/prompt")
async def bunsen_prompt(request: PromptRequest):
    if not BUNSEN_ID:
        raise HTTPException(status_code=500, detail="BUNSEN_RESOURCE_ID not configured")
    logger.info(f"[BUNSEN] Prompt: {request.text[:100]}")
    agent = reasoning_engines.ReasoningEngine(BUNSEN_ID)
    response = agent.query(user_id="user", message=request.text)
    text = get_agent_text(response)
    blocked = text.strip().startswith("I'm sorry, I'm unable")
    logger.info(f"[BUNSEN] Response (blocked={blocked}): {text[:100]}")
    return {
        "text": text,
        "armor_blocked": blocked,
        "armor_triggered": ["model_armor"] if blocked else [],
        "armor_stage": "prompt_or_response" if blocked else "",
    }


@app.get("/health")
def health():
    return {"status": "ok", "beaker": bool(BEAKER_ID), "bunsen": bool(BUNSEN_ID)}
