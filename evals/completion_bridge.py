"""Subprocess-callable bridge to Anthropic's Claude Messages API.

Reads JSON from stdin:
    {"prompt": str, "model": str?, "system": str?, "max_tokens": int?}

Writes JSON to stdout on success:
    {"text": str, "tokens_in": int, "tokens_out": int, "latency_ms": int,
     "model": str, "stop_reason": str}

Exit codes:
    0 — success
    2 — no ANTHROPIC_API_KEY (fail-closed; stderr message NO_API_KEY)
    3 — HTTP or parse error (stderr contains error text)

Model default: claude-haiku-4-5 for the "smol" alias. The model name string
supplied over stdin wins if present.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import time


MODEL_ALIASES = {
    "smol": "claude-haiku-4-5",
    "default": "claude-sonnet-4-5",
    "slow": "claude-opus-4-5",
}


def resolve_api_key() -> str | None:
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if key:
        return key
    home_file = pathlib.Path.home() / ".anthropic"
    if home_file.is_file():
        text = home_file.read_text().strip()
        if text and not text.startswith("#"):
            # accept either bare key or key=val
            if "=" in text.splitlines()[0] and text.splitlines()[0].startswith("ANTHROPIC_API_KEY"):
                return text.splitlines()[0].split("=", 1)[1].strip().strip('"').strip("'")
            return text.splitlines()[0].strip()
    return None


def call_anthropic(api_key: str, model: str, prompt: str, system: str | None, max_tokens: int) -> dict:
    body = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        body["system"] = system
    headers = {
        "content-type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }
    payload = json.dumps(body).encode("utf-8")
    url = "https://api.anthropic.com/v1/messages"

    try:
        import httpx  # type: ignore
        t0 = time.time()
        r = httpx.post(url, headers=headers, content=payload, timeout=60.0)
        latency_ms = int((time.time() - t0) * 1000)
        r.raise_for_status()
        data = r.json()
    except ImportError:
        import urllib.request, urllib.error
        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=60.0) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as e:
            raw = e.read()
            latency_ms = int((time.time() - t0) * 1000)
            raise RuntimeError(f"HTTP {e.code}: {raw.decode('utf-8', 'replace')[:400]}")
        latency_ms = int((time.time() - t0) * 1000)
        data = json.loads(raw.decode("utf-8"))

    # extract text
    text = ""
    for block in data.get("content", []):
        if block.get("type") == "text":
            text += block.get("text", "")
    usage = data.get("usage", {})
    return {
        "text": text,
        "tokens_in": int(usage.get("input_tokens", 0)),
        "tokens_out": int(usage.get("output_tokens", 0)),
        "latency_ms": latency_ms,
        "model": data.get("model", model),
        "stop_reason": data.get("stop_reason", ""),
    }


def main() -> int:
    try:
        req = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError as e:
        print(f"BAD_JSON {e}", file=sys.stderr)
        return 3

    prompt = req.get("prompt", "")
    if not prompt:
        print("BAD_REQUEST empty prompt", file=sys.stderr)
        return 3

    model = req.get("model") or "smol"
    model = MODEL_ALIASES.get(model, model)
    system = req.get("system")
    max_tokens = int(req.get("max_tokens", 256))

    key = resolve_api_key()
    if not key:
        print("NO_API_KEY", file=sys.stderr)
        return 2

    try:
        reply = call_anthropic(key, model, prompt, system, max_tokens)
    except Exception as e:  # noqa: BLE001
        print(f"HTTP_ERR {e}", file=sys.stderr)
        return 3

    sys.stdout.write(json.dumps(reply))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
