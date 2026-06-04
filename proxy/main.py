"""
Agent Firewall Proxy
Handles GCP auth and forwards requests to Agent Engine for Beaker and Bunsen.
"""
import os
import logging
import requests as http_requests
import google.auth
import google.auth.transport.requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("proxy")

LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "europe-west2")
BEAKER_ID = os.environ.get("BEAKER_RESOURCE_ID", "")
BUNSEN_ID = os.environ.get("BUNSEN_RESOURCE_ID", "")

AGENT_ENGINE_BASE = f"https://{LOCATION}-aiplatform.googleapis.com/v1"

app = FastAPI(title="Agent Firewall Proxy")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class PromptRequest(BaseModel):
    text: str


def get_token() -> str:
    creds, _ = google.auth.default()
    creds.refresh(google.auth.transport.requests.Request())
    return creds.token


def query_agent(resource_id: str, message: str) -> str:
    url = f"{AGENT_ENGINE_BASE}/{resource_id}:streamQuery"
    resp = http_requests.post(
        url,
        headers={"Authorization": f"Bearer {get_token()}", "Content-Type": "application/json"},
        json={"input": {"user_id": "user", "message": message}},
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    logger.info(f"Agent Engine raw response: {str(data)[:300]}")

    # streamQuery returns the final event directly or a list — extract model text
    if isinstance(data, list):
        for event in reversed(data):
            if isinstance(event, dict):
                parts = event.get("content", {}).get("parts", [])
                for part in parts:
                    if isinstance(part, dict) and part.get("text"):
                        return part["text"]
    if isinstance(data, dict):
        parts = data.get("content", {}).get("parts", [])
        if parts and parts[0].get("text"):
            return parts[0]["text"]
    return str(data)


@app.post("/beaker/prompt")
async def beaker_prompt(request: PromptRequest):
    if not BEAKER_ID:
        raise HTTPException(status_code=500, detail="BEAKER_RESOURCE_ID not configured")
    logger.info(f"[BEAKER] Prompt: {request.text[:100]}")
    text = query_agent(BEAKER_ID, request.text)
    logger.info(f"[BEAKER] Response: {text[:100]}")
    return {"text": text}


@app.post("/bunsen/prompt")
async def bunsen_prompt(request: PromptRequest):
    if not BUNSEN_ID:
        raise HTTPException(status_code=500, detail="BUNSEN_RESOURCE_ID not configured")
    logger.info(f"[BUNSEN] Prompt: {request.text[:100]}")
    text = query_agent(BUNSEN_ID, request.text)
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
