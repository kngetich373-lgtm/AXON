from datetime import datetime
import re

from ..config import GOALS_FILE, MISSIONS_FILE, EXPERIENCE_FILE, PERSONAL_MEMORY_FILE
from ..storage import load_json, save_json


DEFAULT_PERSONAL_MEMORY = {
    "enabled": False,
    "facts": {},
    "aliases": {},
    "places": {},
    "preferences": {
        "music_auto_open": False,
        "external_auto_open": False,
    },
    "recent_summaries": [],
}

SENSITIVE_MEMORY = re.compile(
    r"(?:api[ _-]?key|secret|password|passphrase|access[ _-]?token|bearer\s+|private[ _-]?key)",
    re.IGNORECASE,
)

class Memory:
    def __init__(self):
        self.goals = load_json(GOALS_FILE, [])
        self.missions = load_json(MISSIONS_FILE, [])
        self.experience = load_json(EXPERIENCE_FILE, [])
        stored = load_json(PERSONAL_MEMORY_FILE, {})
        self.personal = self._normalise_personal(stored)

    @staticmethod
    def _normalise_personal(value):
        personal = {
            "enabled": DEFAULT_PERSONAL_MEMORY["enabled"],
            "facts": {}, "aliases": {}, "places": {},
            "preferences": dict(DEFAULT_PERSONAL_MEMORY["preferences"]),
            "recent_summaries": [],
        }
        if not isinstance(value, dict):
            return personal
        personal["enabled"] = bool(value.get("enabled", False))
        for key in ("facts", "aliases", "places"):
            if isinstance(value.get(key), dict):
                personal[key] = {str(k): str(v) for k, v in value[key].items()}
        if isinstance(value.get("preferences"), dict):
            personal["preferences"].update({
                str(k): bool(v) if isinstance(v, bool) else v
                for k, v in value["preferences"].items()
            })
        if isinstance(value.get("recent_summaries"), list):
            personal["recent_summaries"] = [str(x) for x in value["recent_summaries"][-20:]]
        return personal

    def _save_personal(self):
        save_json(PERSONAL_MEMORY_FILE, self.personal)

    def enable_personal_memory(self, enabled=True):
        self.personal["enabled"] = bool(enabled)
        self._save_personal()

    def personal_enabled(self):
        return bool(self.personal.get("enabled"))

    def remember_fact(self, key, value):
        key, value = str(key).strip(), str(value).strip()
        if not key or not value:
            return False, "A memory needs both a label and a value."
        if SENSITIVE_MEMORY.search(key) or SENSITIVE_MEMORY.search(value):
            return False, "AXON does not store API keys, passwords, tokens, or other secrets."
        self.personal["enabled"] = True
        self.personal["facts"][key.lower()] = value
        self._save_personal()
        return True, f"Remembered {key}: {value}."

    def remember_alias(self, alias, command):
        alias, command = str(alias).strip().lower(), str(command).strip()
        if not alias or not command:
            return False, "An app alias needs both a phrase and an application command."
        if SENSITIVE_MEMORY.search(alias) or SENSITIVE_MEMORY.search(command):
            return False, "AXON does not store secrets as application aliases."
        self.personal["enabled"] = True
        self.personal["aliases"][alias] = command
        self._save_personal()
        return True, f"Remembered app alias: {alias} opens {command}."

    def alias(self, alias):
        return self.personal.get("aliases", {}).get(str(alias).strip().lower())

    def set_preference(self, key, value):
        self.personal["enabled"] = True
        self.personal["preferences"][str(key)] = value
        self._save_personal()

    def preference(self, key, default=None):
        return self.personal.get("preferences", {}).get(key, default)

    def remember_place(self, label, place):
        label, place = str(label).strip().lower(), str(place).strip()
        if not label or not place:
            return False, "A saved place needs a label and a place name."
        self.personal["enabled"] = True
        self.personal["places"][label] = place
        self._save_personal()
        return True, f"Saved place {label}: {place}."

    def forget(self, key):
        normalized = str(key).strip().lower()
        removed = False
        for section in ("facts", "aliases", "places"):
            if normalized in self.personal[section]:
                del self.personal[section][normalized]
                removed = True
        if removed:
            self._save_personal()
            return True, f"Forgot {key}."
        return False, f"I do not have a saved memory named {key}."

    def clear_personal_memory(self):
        self.personal = self._normalise_personal({})
        self._save_personal()

    def personal_summary(self):
        if not self.personal_enabled():
            return "Personal working memory is off. Say “remember …” to save a preference or alias."
        lines = []
        if self.personal["facts"]:
            lines.append("Facts: " + "; ".join(f"{k}: {v}" for k, v in self.personal["facts"].items()))
        if self.personal["aliases"]:
            lines.append("App aliases: " + "; ".join(f"{k} → {v}" for k, v in self.personal["aliases"].items()))
        if self.personal["places"]:
            lines.append("Places: " + "; ".join(f"{k}: {v}" for k, v in self.personal["places"].items()))
        preferences = self.personal["preferences"]
        lines.append("Preferences: " + "; ".join(f"{k}={v}" for k, v in preferences.items()))
        return "\n".join(lines)

    def add_goal(self, text):
        self.goals.append({"text": text, "status": "ACTIVE", "created": datetime.now().isoformat(timespec="seconds")})
        save_json(GOALS_FILE, self.goals)

    def add_mission(self, text):
        self.missions.append({"text": text, "status": "RUNNING", "created": datetime.now().isoformat(timespec="seconds")})
        save_json(MISSIONS_FILE, self.missions)

    def record(self, kind, request, result, success):
        # Experience is persistent too: never retain a secret merely because it
        # appeared in a command or assistant reply.
        if SENSITIVE_MEMORY.search(str(request)) or SENSITIVE_MEMORY.search(str(result)):
            return
        self.experience.append({
            "time": datetime.now().isoformat(timespec="seconds"),
            "kind": kind, "request": request, "result": result, "success": bool(success)
        })
        save_json(EXPERIENCE_FILE, self.experience[-200:])

    def summary(self):
        if not self.experience:
            return "No learned experience has been recorded yet."
        recent = self.experience[-5:]
        return "\n".join(f"• {x['kind']}: {x['result']}" for x in recent)

    def active_goals(self):
        return [g for g in self.goals if g.get("status") == "ACTIVE"][-5:]

    def active_missions(self):
        return [m for m in self.missions if m.get("status") == "RUNNING"][-5:]
