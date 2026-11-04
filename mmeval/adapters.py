"""Request builders and response parsers for each provider (candidate r6).

Shapes follow the providers' current documentation, read 2026-10-26 (protocol/SOURCES.md):
  anthropic_messages  POST /v1/messages; image block (base64 source) BEFORE the text block; max_tokens;
                      response: content[].text, stop_reason, model, usage.input_tokens/output_tokens
  openai_chat         POST /v1/chat/completions; image_url data URL with an explicit `detail`;
                      max_completion_tokens; response: choices[0].message.content, finish_reason, model,
                      usage.prompt_tokens/completion_tokens
  ollama_chat         POST /api/chat; message.images = [base64]; stream false; options.num_predict etc.;
                      response: message.content, done_reason, model, prompt_eval_count/eval_count and
                      load/total durations (ns)
An adapter that builds a request has NOT shown that authentication or the model works. Only an
authorised, recorded run shows that.
"""
import base64

from .config import PROVIDERS


class AdapterError(ValueError):
    """The response did not have the shape this adapter expects."""


def _sampling(arm):
    s = dict(arm.get("sampling") or {})
    return {k: v for k, v in s.items() if v is not None}


def build_request(arm, image_bytes, media_type, prompt, credential=None):
    """Return (url, headers, payload). The credential is used only for the header; it is never stored."""
    kind = PROVIDERS[arm["provider"]]["adapter"]
    b64 = base64.b64encode(image_bytes).decode() if image_bytes is not None else None
    url = arm["endpoint"]
    n = int(arm.get("max_output_tokens") or 4096)
    if kind == "anthropic_messages":
        content = []
        if b64 is not None:
            content.append({"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}})
        content.append({"type": "text", "text": prompt})
        payload = {"model": arm["model_requested"], "max_tokens": n,
                   "messages": [{"role": "user", "content": content}], **_sampling(arm)}
        headers = {"anthropic-version": "2023-06-01", "content-type": "application/json"}
        if credential:
            headers["x-api-key"] = credential
        return url, headers, payload
    if kind == "openai_chat":
        content = []
        if b64 is not None:
            img = {"url": f"data:{media_type};base64,{b64}"}
            if arm.get("image_detail"):
                img["detail"] = arm["image_detail"]
            content.append({"type": "image_url", "image_url": img})
        content.append({"type": "text", "text": prompt})
        payload = {"model": arm["model_requested"], "max_completion_tokens": n,
                   "messages": [{"role": "user", "content": content}], **_sampling(arm)}
        headers = {"Content-Type": "application/json"}
        if credential:
            headers["Authorization"] = f"Bearer {credential}"
        return url, headers, payload
    if kind == "ollama_chat":
        msg = {"role": "user", "content": prompt}
        if b64 is not None:
            msg["images"] = [b64]
        opts = {"num_predict": n, **_sampling(arm)}
        ctx = (arm.get("local_runtime") or {}).get("num_ctx")
        if ctx:
            opts["num_ctx"] = ctx
        payload = {"model": arm["model_requested"], "messages": [msg], "stream": False, "options": opts}
        if arm.get("thinking") in (True, False):
            payload["think"] = arm["thinking"]
        return url, {"Content-Type": "application/json"}, payload
    raise AdapterError(f"no adapter for {kind}")


def parse_response(arm, data):
    """Return {text, finish, served_model, usage, timing}. finish is one of stop, length, refusal, other."""
    kind = PROVIDERS[arm["provider"]]["adapter"]
    if not isinstance(data, dict):
        raise AdapterError("response is not a JSON object")
    if kind == "anthropic_messages":
        blocks = data.get("content")
        if not isinstance(blocks, list):
            raise AdapterError("anthropic response has no content list")
        text = "".join(b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") in (None, "text"))
        sr = data.get("stop_reason")
        finish = {"end_turn": "stop", "stop_sequence": "stop", "max_tokens": "length", "refusal": "refusal"}.get(sr, "other")
        u = data.get("usage") or {}
        return {"text": text, "finish": finish, "finish_raw": sr, "served_model": data.get("model"),
                "usage": {"input_tokens": u.get("input_tokens"), "output_tokens": u.get("output_tokens")},
                "timing": {}}
    if kind == "openai_chat":
        ch = (data.get("choices") or [None])[0]
        if not isinstance(ch, dict) or not isinstance(ch.get("message"), dict):
            raise AdapterError("openai-style response has no choices[0].message")
        msg = ch["message"]
        text = msg.get("content") or ""
        fr = ch.get("finish_reason")
        finish = {"stop": "stop", "length": "length", "content_filter": "refusal"}.get(fr, "other")
        if msg.get("refusal"):
            finish = "refusal"
        u = data.get("usage") or {}
        det = u.get("completion_tokens_details") or {}
        return {"text": text, "finish": finish, "finish_raw": fr, "served_model": data.get("model"),
                "usage": {"input_tokens": u.get("prompt_tokens"), "output_tokens": u.get("completion_tokens"),
                          "reasoning_tokens": det.get("reasoning_tokens")},
                "timing": {}}
    if kind == "ollama_chat":
        msg = data.get("message")
        if not isinstance(msg, dict):
            raise AdapterError("ollama response has no message")
        dr = data.get("done_reason")
        finish = {"stop": "stop", "length": "length"}.get(dr, "other")
        ns = lambda k: (data.get(k) / 1e6) if isinstance(data.get(k), (int, float)) else None
        return {"text": msg.get("content") or "", "finish": finish, "finish_raw": dr,
                "served_model": data.get("model"),
                "usage": {"input_tokens": data.get("prompt_eval_count"), "output_tokens": data.get("eval_count")},
                "timing": {"load_ms": ns("load_duration"), "total_ms": ns("total_duration"),
                           "prompt_eval_ms": ns("prompt_eval_duration"), "eval_ms": ns("eval_duration")}}
    raise AdapterError(f"no adapter for {kind}")
