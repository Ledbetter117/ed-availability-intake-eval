"""Explicit model / endpoint / modality configuration for multi-model runs (candidate r6).

Nothing here is inferred from a model name. An arm names its provider, endpoint, route, modalities and
the data classes it may receive. Validation happens before any transport object exists, and every
refusal raises ConfigError with the rule that failed.

Rules enforced (each has a regression check in tests/test_harness.py, section G):
  - unknown provider                      -> refused
  - provider/route mismatch               -> refused (cloud providers are cloud; local providers are local)
  - cloud endpoint not on the provider's documented host -> refused
  - local arm endpoint not loopback, and not a PRIVATE IP literal listed in trusted_local_hosts -> refused
  - a trusted_local_hosts entry that is a name or a public address -> refused (a name can resolve anywhere)
  - task needs an image but the arm does not declare image input -> refused
  - private (local-only) data offered to a cloud arm -> refused
  - dispatch with placeholders (model, limits, credentials) -> refused; dry-run is allowed
A local arm has no fallback: there is no field for one, and an unknown field is an error.
"""
import copy, hashlib, ipaddress, json, re
from urllib.parse import urlsplit

PLACEHOLDER = "TBD-AT-EXECUTION"

# Documented endpoints, verified 2026-10-26 against the providers' current docs (see protocol/SOURCES.md).
PROVIDERS = {
    "anthropic": {"route": "cloud", "hosts": {"api.anthropic.com"}, "adapter": "anthropic_messages",
                  "default_endpoint": "https://api.anthropic.com/v1/messages", "credential": True},
    "openai": {"route": "cloud", "hosts": {"api.openai.com"}, "adapter": "openai_chat",
               "default_endpoint": "https://api.openai.com/v1/chat/completions", "credential": True},
    "openai_compatible_local": {"route": "local", "hosts": None, "adapter": "openai_chat",
                                "default_endpoint": None, "credential": False},
    "ollama_local": {"route": "local", "hosts": None, "adapter": "ollama_chat",
                     "default_endpoint": "http://127.0.0.1:11434/api/chat", "credential": False},
}
DATA_CLASSES = {"public_synthetic", "private_local_only"}
MODALITIES = {"text", "image"}
ARM_STATUS = {"queued", "qualification_pending", "ready", "disabled"}
LOOPBACK_NAMES = {"localhost"}

ARM_FIELDS = {
    "arm_id", "role", "provider", "route", "endpoint", "model_requested", "modalities",
    "image_capability_verified", "credential_env", "max_output_tokens", "sampling", "thinking",
    "image_detail", "image_preprocessing", "allowed_data_classes", "status", "dispatch_enabled",
    "limits", "local_runtime", "notes",
}
LIMIT_FIELDS = {"max_calls", "max_attempts_per_trial", "timeout_s", "max_input_tokens_total",
                "max_output_tokens_total", "max_usd", "max_elapsed_s"}
LOCAL_FIELDS = {"runtime", "runtime_version", "weights_sha256", "quantization", "chat_template",
                "num_ctx", "gpu", "served_model_digest"}


class ConfigError(ValueError):
    """A configuration that must not reach transport."""


def safe_identifier(value):
    """IDs are used in filenames and report rows; accept portable single components."""
    return (isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value) is not None
            and not value.endswith(".") and value.split(".")[0].upper() not in
            {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))})


def _host_is_loopback(host):
    if host in LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def trusted_host_ok(host):
    """A trusted local host must be a PRIVATE IP literal (e.g. 192.168.x.x, 10.x.x.x). A name is refused: it could
    resolve anywhere, including to a cloud provider. Loopback needs no listing."""
    try:
        ip = ipaddress.ip_address(str(host).strip("[]"))
    except ValueError:
        return False
    return ip.is_private and not ip.is_loopback and not ip.is_unspecified


def endpoint_allowed(arm, url, trusted_local_hosts=()):
    """True when url is a destination this arm may send to. Used by config validation AND by the
    transport, so a request built some other way still cannot leave its route."""
    p = PROVIDERS.get(arm.get("provider"))
    if p is None:
        return False
    parts = urlsplit(url or "")
    host = (parts.hostname or "").lower()
    if parts.scheme not in ("http", "https") or not host or parts.username is not None or parts.password is not None:
        return False
    if p["route"] == "cloud":
        return parts.scheme == "https" and host in p["hosts"]
    if arm.get("credential_env"):
        return arm.get("provider") == "openai_compatible_local" and _host_is_loopback(host)
    trusted = {str(h).lower() for h in trusted_local_hosts if trusted_host_ok(h)}
    return _host_is_loopback(host) or host in trusted


def validate_arm(arm, *, task_needs_image=True, data_class="public_synthetic", trusted_local_hosts=(),
                 for_dispatch=False, capability_check=False):
    """Raise ConfigError if this arm may not run this task; return a normalised copy otherwise."""
    if not isinstance(arm, dict):
        raise ConfigError("arm is not an object")
    unknown = set(arm) - ARM_FIELDS
    if unknown:
        raise ConfigError(f"{arm.get('arm_id')}: unknown field(s) {sorted(unknown)} (no fallback or override fields exist)")
    a = copy.deepcopy(arm)
    aid = a.get("arm_id") or "?"
    if not safe_identifier(a.get("arm_id")):
        raise ConfigError("arm_id must be a portable filename identifier (letters, numbers, dot, underscore or hyphen)")
    prov = a.get("provider")
    if prov not in PROVIDERS:
        raise ConfigError(f"{aid}: unknown provider {prov!r}; allowed: {sorted(PROVIDERS)}")
    p = PROVIDERS[prov]
    if a.get("route") != p["route"]:
        raise ConfigError(f"{aid}: provider {prov} is a {p['route']} route; arm says {a.get('route')!r}")
    a.setdefault("endpoint", p["default_endpoint"])
    if not a.get("endpoint"):
        raise ConfigError(f"{aid}: a local endpoint must be stated explicitly")
    if not endpoint_allowed(a, a["endpoint"], trusted_local_hosts):
        raise ConfigError(f"{aid}: endpoint {a['endpoint']!r} is not allowed for a {p['route']} arm"
                          + (" (local arms: loopback or an explicitly trusted local host only)" if p["route"] == "local" else ""))
    mods = set(a.get("modalities") or [])
    if not mods or not mods <= MODALITIES:
        raise ConfigError(f"{aid}: modalities must be a non-empty subset of {sorted(MODALITIES)}")
    if task_needs_image and "image" not in mods:
        raise ConfigError(f"{aid}: the task sends an image but the arm does not declare image input")
    classes = set(a.get("allowed_data_classes") or [])
    if not classes or not classes <= DATA_CLASSES:
        raise ConfigError(f"{aid}: allowed_data_classes must be a non-empty subset of {sorted(DATA_CLASSES)}")
    if "private_local_only" in classes and p["route"] != "local":
        raise ConfigError(f"{aid}: a cloud arm may never be allowed private_local_only data")
    if data_class not in DATA_CLASSES:
        raise ConfigError(f"unknown data class {data_class!r}")
    if data_class not in classes:
        raise ConfigError(f"{aid}: data class {data_class} is not allowed for this arm")
    if a.get("status") not in ARM_STATUS:
        raise ConfigError(f"{aid}: status must be one of {sorted(ARM_STATUS)}")
    lim = a.get("limits") or {}
    if set(lim) - LIMIT_FIELDS:
        raise ConfigError(f"{aid}: unknown limit field(s) {sorted(set(lim) - LIMIT_FIELDS)}")
    if set(a.get("local_runtime") or {}) - LOCAL_FIELDS:
        raise ConfigError(f"{aid}: unknown local_runtime field(s)")
    credential_env = a.get("credential_env")
    if credential_env is not None and (not isinstance(credential_env, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", credential_env)):
        raise ConfigError(f"{aid}: credential_env must name an environment variable, never contain a credential")
    if p["route"] == "local" and credential_env and prov != "openai_compatible_local":
        raise ConfigError(f"{aid}: local authentication is supported only by openai_compatible_local on loopback")
    if p["credential"] and not a.get("credential_env"):
        raise ConfigError(f"{aid}: a cloud arm must name its credential environment variable")
    if prov != "openai" and a.get("image_detail") not in (None, ""):
        raise ConfigError(f"{aid}: image_detail is an OpenAI request field; leave it empty for {prov}")
    if for_dispatch:
        missing = []
        if a.get("model_requested") in (None, "", PLACEHOLDER):
            missing.append("model_requested")
        if not a.get("image_capability_verified") and task_needs_image and not capability_check:
            # the capability check is the run that establishes this; every other run requires it
            missing.append("image_capability_verified (run the capability check first)")
        for k in ("max_calls", "max_attempts_per_trial", "timeout_s"):
            if not isinstance(lim.get(k), int) or lim.get(k) <= 0:
                missing.append(f"limits.{k}")
        if a.get("status") != "ready":
            missing.append("status=ready")
        if a.get("dispatch_enabled") is not True:
            missing.append("dispatch_enabled=true")
        if missing:
            raise ConfigError(f"{aid}: not dispatchable: " + "; ".join(missing))
    return a


def arm_identity(arm):
    """The fields that define an arm for a manifest. Status, notes, dispatch flags and OPERATIONAL limits (call and
    token caps, timeouts) are excluded: raising a cap to finish a stopped run must not orphan it. The retry policy
    (max_attempts_per_trial) changes what an answer can be, so it stays in the identity."""
    keep = {k: arm.get(k) for k in sorted(ARM_FIELDS - {"status", "notes", "dispatch_enabled", "limits"})}
    keep["retry_policy"] = {"max_attempts_per_trial": (arm.get("limits") or {}).get("max_attempts_per_trial")}
    return keep


def canonical_hash(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def load_config(path):
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    if not isinstance(cfg, dict) or not isinstance(cfg.get("arms"), list):
        raise ConfigError("config must be an object with an 'arms' list")
    bad = [h for h in (cfg.get("trusted_local_hosts") or []) if not trusted_host_ok(h)]
    if bad:
        raise ConfigError(f"trusted_local_hosts must be private IP literals; refused: {bad}")
    ids = [a.get("arm_id") for a in cfg["arms"]]
    if len(ids) != len(set(ids)):
        raise ConfigError("duplicate arm_id in config")
    return cfg
