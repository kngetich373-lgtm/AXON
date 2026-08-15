from __future__ import annotations

import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urljoin

import requests

PROVIDERS = {
    "OpenAI": {"env": "OPENAI_API_KEY", "base": "https://api.openai.com/v1/", "models": "models", "type": "openai"},
    "OpenRouter": {"env": "OPENROUTER_API_KEY", "base": "https://openrouter.ai/api/v1/", "models": "models", "type": "openai_compat"},
    "Groq": {"env": "GROQ_API_KEY", "base": "https://api.groq.com/openai/v1/", "models": "models", "type": "openai_compat"},
    "DeepSeek": {"env": "DEEPSEEK_API_KEY", "base": "https://api.deepseek.com/v1/", "models": "models", "type": "openai_compat"},
    "xAI": {"env": "XAI_API_KEY", "base": "https://api.x.ai/v1/", "models": "models", "type": "openai_compat"},
    "Kimi / Moonshot": {"env": "MOONSHOT_API_KEY", "base": "https://api.moonshot.ai/v1/", "models": "models", "type": "openai_compat"},
    "Anthropic": {"env": "ANTHROPIC_API_KEY", "base": "https://api.anthropic.com/v1/", "models": "models", "type": "anthropic"},
    "Google Gemini": {"env": "GEMINI_API_KEY", "base": "https://generativelanguage.googleapis.com/v1beta/", "models": "models", "type": "gemini"},
    "Ollama": {"env": "", "base": "http://127.0.0.1:11434/api/", "models": "tags", "type": "ollama"},
}

PROFILES = {
    "Auto": "Balances capability, latency, availability and historical performance.",
    "Free": "Prefer zero-cost/free models, then fall back to the best available model.",
    "Auto Coding": "Prefer coding, tools and reasoning capable models.",
    "Auto Fast": "Prefer low-latency models and diversify across healthy providers.",
    "Auto Best": "Prefer stronger reasoning and general-purpose models.",
    "Local Only": "Use Ollama only; no cloud inference.",
    "Private": "Prefer local Ollama and never send requests to cloud providers.",
}

DEFAULT_SYSTEM = (
    "You are AXON, a concise desktop AI assistant. "
    "Never claim a tool action happened unless AXON confirmed success."
)

# Names that are not normal text-chat targets. They remain visible in the
# catalog but are never selected by the normal conversational router.
OPENAI_SPECIAL = (
    "embedding", "moderation", "dall-e", "gpt-image", "tts", "transcribe",
    "whisper", "sora", "realtime", "audio", "search-preview", "text-",
    "davinci", "curie", "babbage", "ada", "gpt-3.5-turbo"
)

BAD_HEALTH = {
    "FAILED", "AUTH ERROR", "RATE LIMITED", "PAYMENT REQUIRED", "OFFLINE",
    "HTTP 404", "DEPRECATED", "RETIRED", "UNAVAILABLE"
}

# A Gemini catalog is deliberately stored as a small, provider-neutral record.
# Keep the one capability signal that determines whether the GenerateContent
# endpoint is usable; dropping it made every imported Gemini model become
# "specialized" on the next start.
GEMINI_GENERATION_METHODS = {"generatecontent", "generate_content"}
GEMINI_LEGACY_SPECIALTIES = (
    "embedding", "embed", "aqa", "tts", "speech", "audio", "image",
    "imagen", "video", "veo", "deprecated", "retired", "transcri",
)

def _capability_values(item):
    """Return normalized catalog capability values from REST or SDK shapes."""
    values = []
    for field in (
        "supportedGenerationMethods", "supported_generation_methods",
        "supportedActions", "supported_actions",
    ):
        value = item.get(field, []) if isinstance(item, dict) else []
        if isinstance(value, str):
            values.append(value)
        elif isinstance(value, (list, tuple, set)):
            values.extend(value)
    return [str(value) for value in values if value]

def _legacy_gemini_is_chat(mid, item):
    """Conservatively recover old flattened Gemini catalog records.

    Old AXON catalog entries did not retain the generation-method metadata.
    Only normal Gemini/Gemma text model families are recovered by name. This
    intentionally leaves specialist and unfamiliar product records unroutable
    until the user re-imports the provider catalog.
    """
    low = _normalize_model_id("Google Gemini", mid).lower()
    stage = str(item.get("releaseStage") or item.get("release_stage") or item.get("stage") or "").upper()
    if stage in {"DEPRECATED", "RETIRED"} or any(word in low for word in GEMINI_LEGACY_SPECIALTIES):
        return False
    return bool(re.match(r"^(gemini|gemma)-", low))

def _normalize_model_id(provider, mid):
    mid = str(mid or "").strip()
    if provider == "Google Gemini":
        return mid.removeprefix("models/")
    return mid

def _headers(provider, key):
    t = PROVIDERS[provider]["type"]
    if t == "anthropic":
        return {
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
    if t == "gemini":
        return {"x-goog-api-key": key, "content-type": "application/json"}
    if t == "ollama":
        return {}
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

def _model_kind(provider, mid, item=None):
    low = str(mid or "").lower().strip()
    item = item or {}

    # Gemini REST responses historically exposed supportedGenerationMethods;
    # newer SDKs expose supported_actions. Support both catalog shapes.
    methods = {value.lower() for value in _capability_values(item)}
    stage = str(item.get("releaseStage") or item.get("release_stage") or item.get("stage") or "").upper()
    if stage in {"DEPRECATED", "RETIRED"}:
        return "specialized"

    if provider == "Google Gemini":
        if methods:
            return "chat" if methods & GEMINI_GENERATION_METHODS else "specialized"
        return "chat" if _legacy_gemini_is_chat(mid, item) else "specialized"

    if provider == "Ollama":
        return "specialized" if "embed" in low else "chat"

    if provider == "OpenAI":
        if any(x in low for x in OPENAI_SPECIAL):
            return "specialized"
        return "chat" if low.startswith(("gpt-", "o1", "o3", "o4", "codex", "gpt-oss")) else "specialized"

    # OpenAI-compatible catalogs usually don't expose capability metadata.
    # Treat ordinary language model IDs as chat candidates; explicit specialist
    # products remain excluded.
    if any(x in low for x in (
        "embedding", "embed-", "moderation", "tts", "whisper", "transcri",
        "image", "vision-only", "rerank", "reranker"
    )):
        return "specialized"
    return "chat"

def _catalog_model(provider, item):
    if isinstance(item, str):
        mid = _normalize_model_id(provider, item)
        kind = _model_kind(provider, mid)
        return {
            "id": mid, "name": mid, "kind": kind, "routable": kind == "chat",
            "health": None, "free": False, "coding": False, "reasoning": False,
            "fast": False, "vision": False, "tools": True, "context": 0,
        }

    mid = _normalize_model_id(provider, item.get("id") or item.get("name"))
    if not mid:
        return None
    blob = json.dumps(item).lower()
    pricing = item.get("pricing", {})
    free = (
        ":free" in mid.lower()
        or " free" in mid.lower()
        or (
            isinstance(pricing, dict)
            and str(pricing.get("prompt", "1")) in {"0", "0.0", "0.00"}
            and str(pricing.get("completion", "1")) in {"0", "0.0", "0.00"}
        )
    )
    kind = _model_kind(provider, mid, item)
    stage = str(item.get("releaseStage") or item.get("release_stage") or "").upper()
    catalog = {
        "id": mid,
        "name": item.get("name") or mid,
        "kind": kind,
        "routable": kind == "chat" and stage not in {"DEPRECATED", "RETIRED"},
        "health": None,
        "free": free,
        "coding": any(x in blob for x in ("code", "coding", "coder", "programming")),
        "reasoning": any(x in blob for x in ("reason", "thinking", "o1", "o3", "o4")),
        "fast": any(x in blob for x in ("mini", "nano", "flash", "haiku", "small", "lite", "1b", "3b", "7b")),
        "vision": any(x in blob for x in ("vision", "image", "multimodal")),
        "tools": any(x in blob for x in ("tool", "function", "function_call"))
                 or PROVIDERS[provider]["type"] in {"openai", "openai_compat", "anthropic", "gemini"},
        "context": item.get("context_length") or item.get("input_token_limit") or 0,
        "stage": stage or "UNKNOWN",
    }
    if provider == "Google Gemini":
        # Persist the capability data in a canonical form so startup
        # reclassification has the same information as the live import.
        catalog["supported_generation_methods"] = _capability_values(item)
    return catalog

def fetch_models(provider, key=None, timeout=12):
    info = PROVIDERS[provider]
    key = key or ""
    if info["type"] != "ollama" and not key:
        raise ValueError("API key required")

    r = requests.get(
        urljoin(info["base"], info["models"]),
        headers=_headers(provider, key),
        timeout=timeout,
    )
    r.raise_for_status()
    data = r.json()
    raw = data.get("data", data.get("models", []))

    # Gemini can paginate. Pull all pages so "import all" really means all
    # models exposed to this key, not just the first page.
    if info["type"] == "gemini":
        raw = list(raw)
        token = data.get("nextPageToken")
        while token:
            rr = requests.get(
                urljoin(info["base"], "models"),
                headers=_headers(provider, key),
                params={"pageToken": token, "pageSize": 1000},
                timeout=timeout,
            )
            rr.raise_for_status()
            page = rr.json()
            raw.extend(page.get("models", []))
            token = page.get("nextPageToken")

    out = []
    for item in raw:
        model = _catalog_model(provider, item)
        if model:
            out.append(model)
    return sorted(out, key=lambda x: x["id"].lower())

def _error_status(exc):
    code = getattr(getattr(exc, "response", None), "status_code", None)
    if code == 402:
        return "PAYMENT REQUIRED"
    if code in {401, 403}:
        return "AUTH ERROR"
    if code == 404:
        return "HTTP 404"
    if code == 429:
        return "RATE LIMITED"
    if code:
        return f"HTTP {code}"
    return "FAILED"

def provider_health(provider, key=None, timeout=8):
    """Catalog connectivity only. Chat readiness is verified separately."""
    started = time.perf_counter()
    try:
        models = fetch_models(provider, key, timeout)
        return {
            "ok": True,
            "status": "CATALOG ONLINE",
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "models": len(models),
            "routable": sum(1 for m in models if m.get("routable")),
        }
    except requests.HTTPError as e:
        return {
            "ok": False, "status": _error_status(e),
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "error": _response_detail(e) or str(e),
        }
    except Exception as e:
        return {
            "ok": False, "status": "OFFLINE",
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "error": str(e),
        }

def _response_detail(exc):
    try:
        r = exc.response
        if r is not None:
            data = r.json()
            if isinstance(data, dict):
                err = data.get("error")
                if isinstance(err, dict):
                    return str(err.get("message") or err.get("code") or err)
                return str(data.get("message") or data)[:600]
            return r.text[:600]
    except Exception:
        pass
    return ""

class ProviderStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data = {
            "keys": {}, "models": {}, "health": {}, "profile": "Auto",
            "active": None, "metrics": {}, "voice": {
                "mode": "smart", "auto_start": True, "wake_word": "hey axon",
            },
        }
        self._lock = threading.RLock()
        self.load()

    def load(self):
        changed = False
        try:
            if self.path.exists():
                loaded = json.loads(self.path.read_text())
                if isinstance(loaded, dict):
                    self.data.update(loaded)
                    # Keys were stored in old providers.json files. Retain
                    # them for this process so an upgrade does not interrupt
                    # a running session, but remove them on the next save.
                    changed = isinstance(loaded.get("keys"), dict) and bool(loaded.get("keys"))
        except Exception:
            pass
        self.data.setdefault("voice", {})
        self.data["voice"].setdefault("mode", "smart")
        self.data["voice"].setdefault("auto_start", True)
        self.data["voice"].setdefault("wake_word", "hey axon")

        # Reclassify every persisted catalog entry so stale V14 flags cannot
        # keep obsolete models in the normal routing pool.
        for provider, models in list(self.data.get("models", {}).items()):
            if not isinstance(models, list):
                continue
            for model in models:
                if not isinstance(model, dict):
                    continue
                if provider == "Google Gemini" and "supported_generation_methods" not in model:
                    methods = _capability_values(model)
                    if methods:
                        model["supported_generation_methods"] = methods
                        changed = True
                kind = _model_kind(provider, model.get("id") or model.get("name"), model)
                stage = str(
                    model.get("releaseStage") or model.get("release_stage") or model.get("stage") or "UNKNOWN"
                ).upper()
                if model.get("kind") != kind:
                    changed = True
                model["kind"] = kind
                routable = kind == "chat" and stage not in {"DEPRECATED", "RETIRED"}
                if model.get("routable") != routable:
                    changed = True
                model["routable"] = routable
                if model.get("stage") != stage:
                    changed = True
                model["stage"] = stage
                model.setdefault("health", None)
                model.setdefault("last_error", "")
                model.setdefault("last_latency_ms", None)

        for p, info in PROVIDERS.items():
            env = info.get("env")
            if env and not self.get_key(p):
                value = os.getenv(env, "").strip()
                if value:
                    self.data.setdefault("keys", {})[p] = value

        if changed:
            self.save()

    def save(self):
        with self._lock:
            tmp = self.path.with_suffix(".tmp")
            # Provider catalogs are safe to persist; credentials are not.
            # Configure keys through environment variables or the private
            # .env file, never through providers.json.
            persisted = {key: value for key, value in self.data.items() if key != "keys"}
            tmp.write_text(json.dumps(persisted, indent=2))
            tmp.replace(self.path)

    def set_key(self, provider, key):
        self.data.setdefault("keys", {})[provider] = (key or "").strip()
        self.save()

    def get_key(self, provider):
        return self.data.get("keys", {}).get(provider, "")

    def set_models(self, provider, models):
        self.data.setdefault("models", {})[provider] = models
        self.save()

    def models(self, provider):
        return self.data.get("models", {}).get(provider, [])

    def connected(self):
        return [p for p in PROVIDERS if self.get_key(p) or p == "Ollama"]

    def set_profile(self, profile):
        self.data["profile"] = profile
        self.save()

    def profile(self):
        return self.data.get("profile", "Auto")

    def set_active(self, provider, model):
        self.data["active"] = {"provider": provider, "model": model}
        self.save()

    def active(self):
        return self.data.get("active")

    def set_health(self, provider, status, **extra):
        self.data.setdefault("health", {})[provider] = {
            "status": status, "updated": time.time(), **extra
        }
        self.save()

    def health(self, provider):
        return self.data.get("health", {}).get(provider, {})

    def set_metric(self, provider, model, **metrics):
        self.data.setdefault("metrics", {}).setdefault(provider, {})[model] = metrics
        self.save()

    def metric(self, provider, model):
        return self.data.get("metrics", {}).get(provider, {}).get(model, {})

    def set_voice(self, **values):
        self.data.setdefault("voice", {}).update(values)
        self.save()

    def voice(self):
        return self.data.get("voice", {})

def _runtime_eligible(provider, model):
    if not isinstance(model, dict) or not model.get("routable", False):
        return False
    if model.get("kind") != "chat":
        return False
    if model.get("stage") in {"DEPRECATED", "RETIRED"}:
        return False

    # Failed/rate-limited models should only be quarantined while their
    # cooldown is active. Once retry_at has passed, let the router try them
    # again so temporary provider errors don't permanently strand AXON with
    # "No verified chat model" / "All eligible models failed".
    retry_at = model.get("retry_at")
    if retry_at:
        try:
            if time.time() < float(retry_at):
                return False
        except (TypeError, ValueError):
            pass
        return True

    if model.get("health") in BAD_HEALTH:
        return False
    return True

def _score_model(provider, model, prompt, profile, metric=None):
    if not _runtime_eligible(provider, model):
        return -10000
    low, prof = prompt.lower(), profile.lower()
    score = 50.0

    if provider == "Ollama":
        score += 8 if ("local" in prof or "private" in prof) else 0
    else:
        score += 10 if ("local" not in prof and "private" not in prof) else -35

    if "coding" in prof or any(x in low for x in ("code", "python", "bug", "debug", "program", "api", "script")):
        score += 24 if model.get("coding") else -4
    if any(x in low for x in ("reason", "prove", "architecture", "analyze deeply", "complex")):
        score += 18 if model.get("reasoning") else 0
    if "free" in prof:
        score += 35 if model.get("free") else -15
    if "fast" in prof or "fast" in low:
        score += 25 if model.get("fast") else 0
    if "best" in prof:
        score += 15 if model.get("reasoning") else 0

    metric = metric or {}
    if metric.get("success_rate") is not None:
        score += max(-15, min(15, (metric["success_rate"] - 0.8) * 50))
    if metric.get("latency_ms"):
        score += max(-15, 12 - metric["latency_ms"] / 200)
    if metric.get("samples", 0) == 0:
        score += 4
    return score

def choose_candidates(store, text, limit=7):
    """Choose a diverse candidate set instead of seven models from one provider."""
    candidates = []
    profile = store.profile()
    active = store.active()

    # An explicitly active model is a preference, not a lock. Keep fallbacks.
    if active:
        ap, am = active.get("provider"), active.get("model")
        if ap in PROVIDERS:
            for m in store.models(ap):
                if m.get("id") == am and _runtime_eligible(ap, m):
                    candidates.append((ap, am))
                    break

    scored = []
    for provider in store.connected():
        if profile in {"Local Only", "Private"} and provider != "Ollama":
            continue
        # Catalog online is enough to discover candidates; runtime health is
        # learned per model. Do not discard an entire provider just because one
        # previous model failed.
        for model in store.models(provider):
            if _runtime_eligible(provider, model):
                scored.append((
                    _score_model(provider, model, text, profile, store.metric(provider, model["id"])),
                    provider, model["id"]
                ))

    scored.sort(reverse=True, key=lambda x: x[0])
    seen = {p for p, _ in candidates}
    # First pass: maximize provider diversity.
    for _, provider, mid in scored:
        if provider not in seen:
            candidates.append((provider, mid))
            seen.add(provider)
        if len(candidates) >= limit:
            return candidates[:limit]
    # Second pass: fill remaining slots with the best remaining models.
    for _, provider, mid in scored:
        pair = (provider, mid)
        if pair not in candidates:
            candidates.append(pair)
        if len(candidates) >= limit:
            break
    return candidates[:limit]

def choose_model(store, text):
    c = choose_candidates(store, text, 1)
    return c[0] if c else (None, None)

def _openai_request(provider, model, prompt, system, key, timeout, stream=False):
    if provider == "OpenAI":
        payload = {
            "model": model, "input": prompt,
            "instructions": system or DEFAULT_SYSTEM, "stream": stream,
        }
        return requests.post(
            PROVIDERS[provider]["base"] + "responses",
            headers=_headers(provider, key), json=payload,
            timeout=timeout, stream=stream,
        )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system or DEFAULT_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        "stream": stream,
    }
    return requests.post(
        PROVIDERS[provider]["base"] + "chat/completions",
        headers=_headers(provider, key), json=payload,
        timeout=timeout, stream=stream,
    )

def _request_json(provider, model, prompt, system, key, timeout, stream=False):
    t = PROVIDERS[provider]["type"]
    if t == "ollama":
        payload = {
            "model": model,
            "prompt": ((system + "\n\n") if system else "") + prompt,
            "stream": stream, "options": {"temperature": 0.2},
        }
        return requests.post(
            PROVIDERS[provider]["base"] + "generate",
            json=payload, timeout=timeout, stream=stream,
        )
    if t == "anthropic":
        payload = {
            "model": model, "max_tokens": 1800,
            "system": system or DEFAULT_SYSTEM,
            "messages": [{"role": "user", "content": prompt}],
            "stream": stream,
        }
        return requests.post(
            PROVIDERS[provider]["base"] + "messages",
            headers=_headers(provider, key), json=payload,
            timeout=timeout, stream=stream,
        )
    if t == "gemini":
        model = _normalize_model_id(provider, model)
        endpoint = "streamGenerateContent?alt=sse" if stream else "generateContent"
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:{endpoint}"
        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}]
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        return requests.post(
            url, headers=_headers(provider, key), json=payload,
            timeout=timeout, stream=stream,
        )
    return _openai_request(provider, model, prompt, system, key, timeout, stream)

def _parse_nonstream(provider, data):
    t = PROVIDERS[provider]["type"]
    if t == "ollama":
        return str(data.get("response", "")).strip()
    if t == "anthropic":
        return "".join(
            x.get("text", "") for x in data.get("content", [])
            if isinstance(x, dict)
        ).strip()
    if t == "gemini":
        return "".join(
            p.get("text", "")
            for c in data.get("candidates", [])
            for p in c.get("content", {}).get("parts", [])
            if isinstance(p, dict)
        ).strip()
    if provider == "OpenAI":
        if data.get("output_text"):
            return str(data["output_text"]).strip()
        parts = [
            c.get("text", "")
            for item in data.get("output", [])
            for c in item.get("content", [])
            if isinstance(c, dict) and c.get("text")
        ]
        if parts:
            return "".join(parts).strip()
    choices = data.get("choices", [])
    if choices:
        return str(choices[0].get("message", {}).get("content", "")).strip()
    return ""

def _record_model(store, provider, model, status, error="", latency=None, cooldown=0):
    models = store.models(provider)
    for m in models:
        if m.get("id") == model:
            m["health"] = status
            m["last_error"] = str(error)[:700]
            if latency is not None:
                m["last_latency_ms"] = latency
            if cooldown:
                m["retry_at"] = time.time() + cooldown
            elif status == "READY":
                m.pop("retry_at", None)
    store.set_models(provider, models)

def _update_metric(store, provider, model, latency, success):
    old = store.metric(provider, model) or {}
    n = int(old.get("samples", 0)) + 1
    oldlat = float(old.get("latency_ms", latency))
    oldrate = float(old.get("success_rate", 1.0))
    store.set_metric(
        provider, model,
        latency_ms=round((oldlat * (n - 1) + latency) / n),
        success_rate=((oldrate * (n - 1) + (1.0 if success else 0.0)) / n),
        samples=n,
        last_test=time.time(),
    )

def _mark_failure(store, provider, model, exc):
    status = _error_status(exc)
    cooldown = 60 if status == "RATE LIMITED" else 300 if status in {"PAYMENT REQUIRED", "AUTH ERROR"} else 120
    _record_model(store, provider, model, status, exc, cooldown=cooldown)
    return status

def chat_one(store, provider, model, prompt, system=None, timeout=45):
    key = store.get_key(provider)
    started = time.perf_counter()
    r = _request_json(provider, model, prompt, system, key, timeout, False)
    try:
        r.raise_for_status()
    except requests.HTTPError as first:
        # OpenAI Responses is preferred; Chat Completions is a compatibility
        # fallback for accounts/models that only expose the latter.
        if provider == "OpenAI":
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system or DEFAULT_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
            }
            try:
                r = requests.post(
                    PROVIDERS[provider]["base"] + "chat/completions",
                    headers=_headers(provider, key), json=payload,
                    timeout=timeout,
                )
                r.raise_for_status()
            except Exception as second:
                _mark_failure(store, provider, model, second)
                raise second from first
        else:
            _mark_failure(store, provider, model, first)
            raise

    text = _parse_nonstream(provider, r.json())
    if not text:
        exc = RuntimeError("provider returned no generated text")
        _mark_failure(store, provider, model, exc)
        raise exc

    latency = round((time.perf_counter() - started) * 1000)
    _update_metric(store, provider, model, latency, True)
    _record_model(store, provider, model, "READY", latency=latency)
    store.set_health(provider, "CHAT READY", latency_ms=latency)
    return text, provider, model, latency

def chat(store, prompt, system=None, timeout=45):
    candidates = choose_candidates(store, prompt, 7)
    if not candidates:
        raise RuntimeError(
            "No verified chat model is available. Import a provider catalog and "
            "run TEST CHAT / TEST ALL CONNECTIONS."
        )
    errors = []
    for provider, model in candidates:
        try:
            result = chat_one(store, provider, model, prompt, system, timeout)
            store.set_active(provider, model)
            return result[:3]
        except Exception as exc:
            errors.append(f"{provider}/{model}: {_error_status(exc)} — {str(exc)[:180]}")
    raise RuntimeError("All eligible models failed. " + " | ".join(errors[:7]))

def parallel_race(store, prompt, system=None, timeout=35, limit=3):
    candidates = choose_candidates(store, prompt, limit)
    if not candidates:
        raise RuntimeError("No verified chat model is available.")
    errors = []
    with ThreadPoolExecutor(max_workers=len(candidates), thread_name_prefix="axon-model") as pool:
        futures = {
            pool.submit(chat_one, store, p, m, prompt, system, timeout): (p, m)
            for p, m in candidates
        }
        for future in as_completed(futures):
            provider, model = futures[future]
            try:
                result = future.result()
                if result[0]:
                    store.set_active(provider, model)
                    return result[:3] + ("RACE",)
            except Exception as exc:
                errors.append(f"{provider}/{model}: {_error_status(exc)}")
    raise RuntimeError("Parallel model race failed. " + " | ".join(errors[:limit]))

def _stream_chunk(provider, data):
    t = PROVIDERS[provider]["type"]
    if t == "ollama":
        return data.get("response", "")
    if t == "anthropic":
        return data.get("delta", {}).get("text", "") if data.get("type") == "content_block_delta" else ""
    if t == "gemini":
        return "".join(
            p.get("text", "")
            for c in data.get("candidates", [])
            for p in c.get("content", {}).get("parts", [])
            if isinstance(p, dict)
        )
    if provider == "OpenAI" and data.get("type") == "response.output_text.delta":
        return data.get("delta", "")
    choices = data.get("choices", [])
    if choices:
        return choices[0].get("delta", {}).get("content", "") or ""
    return ""

def _stream_openai_response(provider, model, prompt, system, key, timeout, on_token):
    payload = {
        "model": model, "input": prompt,
        "instructions": system or DEFAULT_SYSTEM, "stream": True,
    }
    r = requests.post(
        PROVIDERS[provider]["base"] + "responses",
        headers=_headers(provider, key), json=payload,
        timeout=timeout, stream=True,
    )
    r.raise_for_status()
    full = []
    for raw in r.iter_lines(decode_unicode=True):
        if not raw:
            continue
        line = raw.strip()
        if line.startswith("data:"):
            line = line[5:].strip()
        if line in {"[DONE]", "[DONE],", ""}:
            continue
        try:
            data = json.loads(line)
        except Exception:
            continue
        chunk = _stream_chunk(provider, data)
        if chunk:
            full.append(chunk)
            on_token and on_token(chunk)
    text = "".join(full).strip()
    if not text:
        raise RuntimeError("provider returned no generated text")
    return text

def _stream_chat_completions(provider, model, prompt, system, key, timeout, on_token):
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system or DEFAULT_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        "stream": True,
    }
    r = requests.post(
        PROVIDERS[provider]["base"] + "chat/completions",
        headers=_headers(provider, key), json=payload,
        timeout=timeout, stream=True,
    )
    r.raise_for_status()
    full = []
    for raw in r.iter_lines(decode_unicode=True):
        if not raw:
            continue
        line = raw.strip()
        if line.startswith("data:"):
            line = line[5:].strip()
        if line in {"[DONE]", "[DONE],", ""}:
            continue
        try:
            data = json.loads(line)
        except Exception:
            continue
        chunk = data.get("choices", [{}])[0].get("delta", {}).get("content", "")
        if isinstance(chunk, list):
            chunk = "".join(
                str(x.get("text", "")) if isinstance(x, dict) else str(x)
                for x in chunk
            )
        if chunk:
            full.append(chunk)
            on_token and on_token(chunk)
    text = "".join(full).strip()
    if not text:
        raise RuntimeError("provider returned no generated text")
    return text

def _stream_generic(provider, model, prompt, system, key, timeout, on_token):
    r = _request_json(provider, model, prompt, system, key, timeout, True)
    r.raise_for_status()
    full = []
    for raw in r.iter_lines(decode_unicode=True):
        if not raw:
            continue
        line = raw.strip()
        if line.startswith("data:"):
            line = line[5:].strip()
        if line in {"[DONE]", "[DONE],", ""}:
            continue
        try:
            data = json.loads(line)
        except Exception:
            continue
        chunk = _stream_chunk(provider, data)
        if chunk:
            full.append(chunk)
            on_token and on_token(chunk)
    text = "".join(full).strip()
    if not text:
        raise RuntimeError("provider returned no generated text")
    return text

def stream_one(store, provider, model, prompt, system=None, on_token=None, timeout=60):
    key = store.get_key(provider)
    started = time.perf_counter()
    emitted = []

    def buffered(fn):
        chunks = []
        text = fn(lambda c: chunks.append(c) if c else None)
        if not text:
            raise RuntimeError("provider returned no generated text")
        emitted.extend(chunks)
        return text

    if provider == "OpenAI":
        try:
            text = buffered(lambda cb: _stream_openai_response(
                provider, model, prompt, system, key, timeout, cb
            ))
        except Exception as first:
            text = buffered(lambda cb: _stream_chat_completions(
                provider, model, prompt, system, key, timeout, cb
            ))
    else:
        text = buffered(lambda cb: _stream_generic(
            provider, model, prompt, system, key, timeout, cb
        ))

    if on_token:
        for chunk in emitted:
            on_token(chunk)

    latency = round((time.perf_counter() - started) * 1000)
    _update_metric(store, provider, model, latency, True)
    _record_model(store, provider, model, "READY", latency=latency)
    store.set_health(provider, "CHAT READY", latency_ms=latency)
    return text, provider, model

def stream_chat(store, prompt, system=None, on_token=None, timeout=60):
    candidates = choose_candidates(store, prompt, 7)
    if not candidates:
        raise RuntimeError(
            "No verified chat model is available. Import a provider catalog "
            "and test at least one chat model."
        )
    errors = []
    for provider, model in candidates:
        try:
            result = stream_one(
                store, provider, model, prompt, system, on_token, timeout
            )
            store.set_active(provider, model)
            return result
        except Exception as exc:
            status = _mark_failure(store, provider, model, exc)
            errors.append(f"{provider}/{model}: {status} — {str(exc)[:180]}")
    raise RuntimeError("All eligible models failed. " + " | ".join(errors[:7]))

def validate_model(store, provider, model, timeout=20):
    started = time.perf_counter()
    try:
        text, _, _, latency = chat_one(
            store, provider, model,
            "Reply with exactly: AXON_OK",
            system="Reply with exactly: AXON_OK",
            timeout=timeout,
        )
        return {
            "ok": bool(text), "status": "READY" if text else "EMPTY",
            "latency_ms": latency, "model": model,
        }
    except requests.HTTPError as exc:
        status = _mark_failure(store, provider, model, exc)
        return {
            "ok": False, "status": status, "model": model,
            "error": _response_detail(exc) or str(exc),
            "latency_ms": round((time.perf_counter() - started) * 1000),
        }
    except Exception as exc:
        status = _mark_failure(store, provider, model, exc)
        return {
            "ok": False, "status": status, "model": model,
            "error": str(exc),
            "latency_ms": round((time.perf_counter() - started) * 1000),
        }

def validate_provider(store, provider, key=None, timeout=20, max_models=3):
    """Validate catalog + a few representative chat models.

    We intentionally don't fire 100+ billable probes automatically. The full
    catalog is imported, but routing learns health lazily and can be asked to
    probe more models from the Models page.
    """
    if provider != "Ollama":
        store.set_key(provider, key or store.get_key(provider))
    h = provider_health(provider, key or store.get_key(provider), timeout=timeout)
    if not h["ok"]:
        store.set_health(provider, h["status"], latency_ms=h["latency_ms"], error=h.get("error"))
        return h

    models = fetch_models(provider, key or store.get_key(provider), timeout=timeout)
    store.set_models(provider, models)
    candidates = [m for m in models if m.get("routable")][:max_models]
    results = []
    for model in candidates:
        results.append(validate_model(store, provider, model["id"], timeout))
        if any(x["ok"] for x in results[-1:]):
            # One healthy representative is enough to prove provider chat access.
            break
    ready = [x for x in results if x.get("ok")]
    status = "CHAT READY" if ready else ("CATALOG ONLINE" if candidates else "NO CHAT MODELS")
    store.set_health(
        provider, status,
        latency_ms=h.get("latency_ms"),
        models=len(models),
        routable=sum(1 for m in models if m.get("routable")),
        ready=len(ready),
        last_error="" if ready else (results[-1].get("error") if results else ""),
    )
    return {
        **h, "status": status, "ready": len(ready),
        "tests": results, "models_data": models,
    }
