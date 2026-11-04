"""Optional GapGPT OpenAI-compatible chat transport.

API key is server-only; CV excerpts are redacted by interview_context.
Only the exact trusted GapGPT API hostname is allowed (no arbitrary proxies).
"""
import os
import re
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException

_MODEL_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:/-]{0,95}$")
_PLACEHOLDERS = {"", "YOUR_GAPGPT_API_KEY", "YOUR_API_KEY", "YOUR_REAL_API_KEY"}


def configured() -> bool:
    return (os.getenv("LLM_PROVIDER", "").strip().lower() == "gapgpt"
            and os.getenv("GAPGPT_API_KEY", "").strip() not in _PLACEHOLDERS)


def gapgpt_config() -> tuple[str, str, str]:
    if os.getenv("LLM_PROVIDER", "").strip().lower() != "gapgpt":
        raise HTTPException(503, "GapGPT is not selected as LLM provider")
    key = os.getenv("GAPGPT_API_KEY", "").strip()
    if key in _PLACEHOLDERS:
        raise HTTPException(503, "GapGPT API key is not configured")
    model = os.getenv("GAPGPT_MODEL", "gpt-4o-mini").strip()
    if not _MODEL_ID.fullmatch(model):
        raise HTTPException(503, "GapGPT model ID is invalid")
    base = os.getenv("GAPGPT_BASE_URL", "https://api.gapgpt.app/v1").rstrip("/")
    parsed = urlparse(base)
    if (parsed.scheme != "https" or parsed.hostname != "api.gapgpt.app"
            or parsed.port not in (None, 443) or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path != "/v1"):
        raise HTTPException(503, "GapGPT API URL must be https://api.gapgpt.app/v1")
    return key, model, base


async def generate_question(instructions: str, prior_turns: list[dict],
                            latest_answer: str | None) -> str:
    key, model, base = gapgpt_config()
    messages = [{"role": "system", "content": instructions
                 + "\nAsk exactly ONE concise practical interview question; "
                   "do not score or recommend an employment decision."}]
    for turn in prior_turns[-18:]:
        if turn.get("source") not in ("server_llm", "candidate_ai"):
            continue
        messages.append({
            "role": "assistant" if turn["source"] == "server_llm" else "user",
            "content": str(turn.get("text", ""))[:1800],
        })
    messages.append({"role": "user", "content": (
        latest_answer[:2000] if latest_answer is not None else
        "Start the interview with one question about the practical technical experience "
        "in my resume and the job requirements.")})
    # Standard Chat Completions fields; DeepSeek-specific 'thinking' isn't portable.
    payload = {"model": model, "messages": messages, "max_tokens": 330, "stream": False}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(45.0, connect=8.0),
                                     follow_redirects=False) as client:
            response = await client.post(base + "/chat/completions", json=payload,
                                         headers={"Authorization": "Bearer " + key,
                                                  "Content-Type": "application/json"})
        if response.status_code in (401, 403):
            raise HTTPException(503, "GapGPT rejected the API key; check account credentials")
        if response.status_code == 402:
            raise HTTPException(503, "GapGPT account has insufficient credit")
        if response.status_code == 429:
            raise HTTPException(503, "GapGPT request limit reached; try again later")
        if response.status_code == 404:
            raise HTTPException(503, "GapGPT API model or endpoint is unavailable; check GAPGPT_MODEL")
        if response.status_code >= 400:
            raise HTTPException(502, "GapGPT could not process the interview request")
        result = response.json()
        answer = result["choices"][0]["message"]["content"]
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError("Empty response")
        return answer.strip()[:1500]
    except httpx.TimeoutException as exc:
        raise HTTPException(504, "GapGPT request timed out") from exc
    except httpx.RequestError as exc:
        raise HTTPException(502, "Could not connect to GapGPT") from exc
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise HTTPException(502, "GapGPT returned an unsupported response format") from exc
