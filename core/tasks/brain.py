"""core/tasks/brain.py — one round of a tool-calling model.

The engine drives the loop; this answers one question: given the conversation
so far and the tools on offer, what does the model say or call next?

It walks the same Gemini ladder and cooldowns as core/gemini.py, with one
difference. gemini.call() leads with a Live rung and can fall to a provider
through a path that passes no tools — right for one-shot calls, wrong here,
where a turn landing on either would come back as prose describing a call.
So this uses the ladder's REST models, and makes the configured provider a
real tool-calling rung.

Turns are stored vendor-neutral, so a task that began on Gemini can continue on
a fallback provider, and survives a restart:

    {"role": "user",  "text"}
    {"role": "model", "text", "calls": [{id, name, args, sig}]}
    {"role": "tool",  "results": [{id, name, result}]}

Gemini 3 attaches a thought signature to every function call and rejects the
next request without it, so signatures are kept with the history; a model that
rejects another model's signatures after a fallback is asked again without them.
"""
from __future__ import annotations

import base64
import json
import time


class NoModel(RuntimeError):
    """Nothing answered. `transient` means waiting is likely to help: quota,
    an overloaded model, a dropped connection — as opposed to no key at all."""

    def __init__(self, message: str, transient: bool):
        super().__init__(message)
        self.transient = transient


_NETWORK_HINTS = ("connecterror", "connection", "timed out", "timeout", "getaddrinfo",
                  "temporarily", "network", "unreachable", "reset by peer")


def _is_network(msg: str) -> bool:
    low = msg.lower()
    return any(h in low for h in _NETWORK_HINTS)


def to_gemini(turns: list, signatures: bool = True) -> list:
    from google.genai import types

    out = []
    for t in turns:
        if t["role"] == "user":
            out.append(types.Content(role="user", parts=[types.Part(text=t.get("text") or "")]))
        elif t["role"] == "model":
            parts = [types.Part(text=t["text"])] if t.get("text") else []
            for c in t.get("calls") or []:
                kw = {"function_call": types.FunctionCall(name=c["name"], args=c.get("args") or {})}
                if signatures and c.get("sig"):
                    kw["thought_signature"] = base64.b64decode(c["sig"])
                parts.append(types.Part(**kw))
            if parts:
                out.append(types.Content(role="model", parts=parts))
        elif t["role"] == "tool":
            out.append(types.Content(role="user", parts=[
                types.Part.from_function_response(name=r["name"], response={"result": r["result"]})
                for r in t["results"]]))
    return out


def to_openai(turns: list, system: str) -> list:
    msgs = [{"role": "system", "content": system}]
    for t in turns:
        if t["role"] == "user":
            msgs.append({"role": "user", "content": t.get("text") or ""})
        elif t["role"] == "model":
            m = {"role": "assistant", "content": t.get("text") or None}
            if t.get("calls"):
                m["tool_calls"] = [{"id": c["id"], "type": "function", "function": {
                    "name": c["name"], "arguments": json.dumps(c.get("args") or {})}}
                    for c in t["calls"]]
            msgs.append(m)
        elif t["role"] == "tool":
            msgs += [{"role": "tool", "tool_call_id": r["id"], "name": r["name"],
                      "content": str(r["result"])} for r in t["results"]]
    return msgs


def _ask_gemini(model: str, system: str, turns: list, decls) -> dict:
    from google.genai import types

    from core import gemini

    cfg = {"system_instruction": system,
           "automatic_function_calling": types.AutomaticFunctionCallingConfig(disable=True)}
    if decls:
        cfg["tools"] = [{"function_declarations": decls}]
    client = gemini.client(timeout_ms=120_000)
    try:
        resp = client.models.generate_content(model=model, contents=to_gemini(turns),
                                              config=types.GenerateContentConfig(**cfg))
    except Exception as e:
        if "signature" not in str(e).lower():
            raise
        resp = client.models.generate_content(model=model, contents=to_gemini(turns, signatures=False),
                                              config=types.GenerateContentConfig(**cfg))
    cand = (resp.candidates or [None])[0]
    text, calls = [], []
    for part in (getattr(getattr(cand, "content", None), "parts", None) or []):
        if getattr(part, "thought", False):
            continue
        fc = getattr(part, "function_call", None)
        if fc is not None and fc.name:
            sig = getattr(part, "thought_signature", None)
            calls.append({"id": fc.id or f"call_{len(calls)}_{int(time.time() * 1000)}",
                          "name": fc.name, "args": dict(fc.args or {}),
                          "sig": base64.b64encode(sig).decode("ascii") if sig else ""})
        elif getattr(part, "text", None):
            text.append(part.text)
    if not text and not calls:
        raise RuntimeError(f"empty answer ({getattr(cand, 'finish_reason', 'no candidate')})")
    return {"text": "".join(text).strip(), "calls": calls}


def _ask_local(system: str, turns: list, decls: list | None) -> dict:
    """Tool-call through Mark 56's loopback-only Ollama adapter.

    The local adapter currently exposes text generation rather than native
    tool calls, so the model must return a small JSON envelope. Only tools
    already allowlisted by TaskTools are present in decls, and the engine
    validates names again before execution.
    """
    from core import local_model

    if not local_model.enabled():
        raise RuntimeError("local model mode is disabled")

    history = []
    for turn in turns:
        role = turn.get("role")
        if role == "user":
            history.append("USER: " + str(turn.get("text") or ""))
        elif role == "model":
            if turn.get("text"):
                history.append("ASSISTANT: " + str(turn["text"]))
            for call in turn.get("calls") or []:
                history.append("ASSISTANT TOOL CALL: " + call["name"] + " "
                               + json.dumps(call.get("args") or {}, ensure_ascii=False))
        elif role == "tool":
            for result in turn.get("results") or []:
                history.append("TOOL RESULT (" + str(result.get("name") or "") + "): "
                               + str(result.get("result") or ""))

    tool_block = json.dumps(decls or [], ensure_ascii=False)
    prompt = (
        system
        + "\\n\\n[LOCAL TASK MODEL PROTOCOL]\\n"
        + "Return exactly one JSON object and no Markdown. Shape: "
        + '{"text":"optional progress or final answer","calls":[{"name":"tool_name","args":{}}]}. '
        + "Use calls=[] when finished. Never invent a tool; choose only from the declarations. "
        + "Do not claim a tool succeeded before its result is returned.\\n"
        + "AVAILABLE TOOLS: " + tool_block
        + "\\n\\nCONVERSATION:\\n" + "\\n".join(history[-80:])
    )
    raw = local_model.generate(prompt, timeout_ms=120_000)
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`").strip()
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
    try:
        data = json.loads(cleaned)
    except Exception:
        left, right = cleaned.find("{"), cleaned.rfind("}")
        if left < 0 or right <= left:
            raise RuntimeError("local model did not return the required JSON task response")
        data = json.loads(cleaned[left:right + 1])
    if not isinstance(data, dict):
        raise RuntimeError("local model task response must be a JSON object")

    allowed = {str(d.get("name")) for d in (decls or []) if isinstance(d, dict)}
    calls = []
    for index, call in enumerate(data.get("calls") or []):
        if not isinstance(call, dict):
            continue
        name = str(call.get("name") or "").strip()
        args = call.get("args") or {}
        if name not in allowed:
            raise RuntimeError("local model requested a tool that is not allowlisted")
        if not isinstance(args, dict):
            raise RuntimeError("local model tool arguments must be an object")
        calls.append({"id": f"local_call_{index}_{int(time.time() * 1000)}",
                      "name": name, "args": args, "sig": ""})
    text = data.get("text") or ""
    if not isinstance(text, str):
        raise RuntimeError("local model response text must be a string")
    if not text.strip() and not calls:
        raise RuntimeError("local model returned neither text nor a tool call")
    return {"text": text.strip(), "calls": calls}


def ask(system: str, turns: list, decls: list | None) -> dict:
    """One tool-calling model turn, preferring Gemini and falling back locally."""
    from core import gemini
    from core.action_loader import strip_meta

    decls = strip_meta(decls) if decls else None
    errors, transient = [], False
    rungs: list = []
    if gemini.api_key():
        ladder = [
            model for model in gemini._LADDERS[gemini.SMART]
            if model != gemini.LIVE and not model.startswith(gemini.PROVIDER_PREFIX)
        ]
        rungs = gemini.usable_rungs(ladder)

    for model in rungs:
        try:
            return _ask_gemini(model, system, turns, decls)
        except Exception as exc:
            msg = str(exc)
            errors.append(f"{model}: {msg[:120]}")
            if gemini.is_quota_error(msg):
                gemini._cool(model)
                transient = True
            elif gemini.is_gone_error(msg):
                gemini._cool(model, gemini._GONE_SECONDS)
            elif gemini.is_unavailable_error(msg):
                gemini._cool(model, gemini._UNAVAILABLE_SECONDS)
                transient = True
            elif _is_network(msg):
                transient = True
            print(f"[Tasks] {model} failed: {msg[:160]}")

    try:
        return _ask_local(system, turns, decls)
    except Exception as exc:
        errors.append(f"local model: {str(exc)[:160]}")
        print(f"[Tasks] local model failed: {str(exc)[:160]}")

    if not gemini.api_key() and not errors:
        errors.append("Gemini is not configured")
    raise NoModel("no task model answered — " + "; ".join(errors[-3:]),
                  transient=transient)
