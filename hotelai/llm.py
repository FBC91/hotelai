"""
hotelai.llm
============

Wrapper singleton del Anthropic SDK con cost tracking.

Precios (abril 2026) en USD por 1M tokens:
    Claude Sonnet 4.6   · input 3.00 · output 15.00
    Claude Haiku 4.5    · input 0.80 · output 4.00

Si Anthropic cambia precios, actualizar PRICING.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from anthropic import Anthropic

from .settings import settings

logger = logging.getLogger("hotelai.llm")


# Precio USD por 1M tokens (input, output)
PRICING: dict[str, tuple[float, float]] = {
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-sonnet-4-5-20250929": (3.00, 15.00),  # fallback
    "claude-haiku-4-5-20251001": (0.80, 4.00),
    "claude-haiku-4-5": (0.80, 4.00),
}


@lru_cache(maxsize=1)
def get_client() -> Anthropic:
    """Cliente Anthropic singleton."""
    key = settings.anthropic_api_key.get_secret_value()
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY no está seteada en env vars.")
    return Anthropic(api_key=key)


def compute_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    """Costo en USD para una llamada. Devuelve 0 si el modelo no está en PRICING."""
    pricing = PRICING.get(model)
    if not pricing:
        logger.warning("modelo desconocido para pricing: %s", model)
        return 0.0
    pin, pout = pricing
    return (tokens_in * pin + tokens_out * pout) / 1_000_000


def call_with_tools(
    *,
    model: str,
    system: str,
    user_text: str,
    tools: list[dict[str, Any]],
    max_tokens: int = 1024,
    temperature: float = 0.2,
    extra_context: str | None = None,
) -> dict[str, Any]:
    """Llama a Claude forzando uso de tool_use.

    El contenido del huésped va en `user_text` y se envuelve en `<guest_message>`
    delimiters para que el system prompt pueda decirle al modelo que ese bloque
    es DATOS, no instrucciones.

    Returns:
        {
            "tool_name": str,
            "tool_input": dict,
            "tokens_in": int,
            "tokens_out": int,
            "cost_usd": float,
            "stop_reason": str,
            "raw": Message
        }
    """
    client = get_client()

    user_content = f"<guest_message>\n{user_text}\n</guest_message>"
    if extra_context:
        user_content = f"{extra_context}\n\n{user_content}"

    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        system=system,
        tools=tools,
        tool_choice={"type": "any"},  # forzar uso de algún tool
        messages=[{"role": "user", "content": user_content}],
    )

    # Extraer el primer (y único esperado) tool_use block
    tool_use = next((b for b in resp.content if b.type == "tool_use"), None)
    if not tool_use:
        # No es esperado bajo tool_choice=any, pero blindamos.
        logger.error("Claude no devolvió tool_use; stop_reason=%s", resp.stop_reason)
        tool_name = None
        tool_input = {}
    else:
        tool_name = tool_use.name
        tool_input = tool_use.input

    tokens_in = resp.usage.input_tokens
    tokens_out = resp.usage.output_tokens

    return {
        "tool_name": tool_name,
        "tool_input": tool_input,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost_usd": compute_cost(model, tokens_in, tokens_out),
        "stop_reason": resp.stop_reason,
        "raw": resp,
    }


__all__ = ["get_client", "compute_cost", "call_with_tools", "PRICING"]
