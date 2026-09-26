"""Shared, bounded Responses API transport for routing and grounded generation."""

import json

import httpx

from assistops.config import Settings


async def structured_response(
    settings: Settings,
    *,
    instructions,
    content,
    schema,
    name,
    max_output_tokens=600,
    transport=None,
):
    body = {
        "model": settings.rag_model,
        "store": False,
        "instructions": instructions,
        "input": json.dumps(content, ensure_ascii=False, separators=(",", ":")),
        "max_output_tokens": max_output_tokens,
        "temperature": 0,
        "text": {"format": {"type": "json_schema", "name": name, "strict": True, "schema": schema}},
    }
    payload = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(payload) > 16000 or not 1 <= max_output_tokens <= 600:
        raise ValueError("Generation input or output limit exceeded")
    if not settings.openai_api_key:
        raise ValueError("OpenAI key is not configured")
    async with httpx.AsyncClient(timeout=15, transport=transport) as client:
        # No automatic retry: a lost response may still have been billed.
        response = await client.post(
            "https://api.openai.com/v1/responses",
            content=payload,
            headers={
                "Authorization": f"Bearer {settings.openai_api_key.get_secret_value()}",
                "Content-Type": "application/json",
            },
        )
    if response.status_code != 200:
        raise RuntimeError(f"Generation failed (HTTP {response.status_code})")
    return response.json()
