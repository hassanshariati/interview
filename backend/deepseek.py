"""Server-side DeepSeek chat for a bounded, consented interview.

Never expose DeepSeek credentials to the browser. Never send the full CV:
the context builder selects and redacts bounded professional excerpts.
"""
import os
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException


def configured() -> bool:
    return (os.getenv("LLM_PROVIDER", "").strip().lower() == "deepseek"
            and os.getenv("DEEPSEEK_API_KEY", "").strip() not in ("", "YOUR_DEEPSEEK_API_KEY"))


def deepseek_config() -> tuple[str, str, str]:
    if os.getenv("LLM_PROVIDER", "").strip().lower() != "deepseek":
        raise HTTPException(503, "DeepSeek is not selected as LLM provider")
    key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not key or key == "YOUR_DEEPSEEK_API_KEY":
        raise HTTPException(503, "DeepSeek API key is not configured")
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-flash").strip()
    if model not in ("deepseek-flash", "deepseek-v4-pro"):
        raise HTTPException(503, "Unsupported DeepSeek model configuration")
    base = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
    parsed = urlparse(base)
    if parsed.scheme != "https" or parsed.hostname != "api.deepseek.com" or parsed.port not in (None, 443) or parsed.username or parsed.password or parsed.path not in ("", "/v1"):
        # Fail closed so a misconfigured host cannot steal the API key.
        raise HTTPException(503, "DeepSeek base URL configuration is invalid")
    return key, model, base


async def generate_question(instructions: str, prior_turns: list[dict],
                            latest_answer: str | None) -> str:
    key, model, base = deepseek_config()
    messages = [
        {"role": "system", "content": instructions + "\nAsk exactly ONE concise, practical interview question in the candidate's language. No scoring or hiring recommendation."}
    ]
    for turn in prior_turns[-18:]:
        if turn.get("source") not in ("server_llm", "candidate_ai"):
            continue  # Candidate-controlled transcript entries cannot impersonate the model.
        messages.append({"role": "assistant" if turn["source"] == "server_llm" else "user",
                         "content": str(turn.get("text", ""))[:1800]})
    if latest_answer is not None:
        messages.append({"role": "user", "content": latest_answer[:2000]})
    else:
        messages.append({"role": "user", "content": "Begin the interview now with one useful technical question based on my CV and target job."})
    payload = {"model": model, "messages": messages, "max_tokens": 330,
               "thinking": {"type": "disabled"}, "stream": False}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(45.0, connect=8.0),
                                     follow_redirects=False) as client:
            response = await client.post(base + "/chat/completions", json=payload,
                                         headers={"Authorization": "Bearer " + key,
                                                  "Content-Type": "application/json"})
        if response.status_code in (401, 403):
            raise HTTPException(503, "DeepSeek API key was rejected; check server credentials")
        if response.status_code in (402, 429):
            raise HTTPException(503, "DeepSeek quota or account credit is unavailable")
        if response.status_code >= 400:
            raise HTTPException(502, "DeepSeek did not accept the interview request")
        data = response.json()
        question = data["choices"][0]["message"]["content"]
        if not isinstance(question, str) or not question.strip():
            raise ValueError("Empty generated question")
        return question.strip()[:1500]
    except httpx.TimeoutException as exc:
        raise HTTPException(504, "DeepSeek response timed out") from exc
    except httpx.RequestError as exc:
        raise HTTPException(502, "Could not reach DeepSeek API") from exc
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise HTTPException(502, "DeepSeek returned an invalid response") from exc
