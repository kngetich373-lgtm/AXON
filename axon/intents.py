"""Small, deterministic natural-language intent parser for workspace actions."""
from __future__ import annotations

from dataclasses import dataclass, field
import re


@dataclass(frozen=True)
class Intent:
    name: str
    args: dict[str, str] = field(default_factory=dict)


def _clean_place(value: str) -> str:
    value = re.sub(r"^(?:open|show|find)\s+", "", value, flags=re.I)
    value = re.sub(r"^(?:(?:a|the)\s+)?(?:satellite\s+)?map\s+(?:of\s+)?", "", value, flags=re.I)
    value = re.sub(r"\s+(?:on\s+(?:the\s+)?map|in\s+(?:a\s+)?satellite(?:\s+view)?|on\s+satellite|satellite(?:\s+view)?)\s*$", "", value, flags=re.I)
    value = re.sub(r"\s+(?:map|satellite(?:\s+view)?)\s*$", "", value, flags=re.I)
    return value.strip(" ,.") or "world"


def parse_intent(text: str) -> Intent | None:
    raw = str(text or "").strip()
    low = raw.lower()
    if not raw:
        return None

    if low in {"what do you remember", "what do you remember about me", "show memory", "show my memory"}:
        return Intent("memory_show")
    if low in {"clear all memory", "clear my memory", "forget everything"}:
        return Intent("memory_clear")
    match = re.match(r"^forget\s+(?:my\s+)?(.+?)\s*$", raw, re.I)
    if match:
        return Intent("memory_forget", {"key": match.group(1).strip()})
    match = re.match(r"^remember\s+(?:that\s+)?open\s+(.+?)\s+means\s+open\s+(.+?)\s*$", raw, re.I)
    if match:
        return Intent("remember_alias", {"alias": match.group(1).strip(), "command": match.group(2).strip()})
    match = re.match(r"^remember\s+(?:that\s+)?my\s+(.+?)\s+(?:is|are)\s+(.+?)\s*$", raw, re.I)
    if match:
        return Intent("remember_fact", {"key": match.group(1).strip(), "value": match.group(2).strip()})
    match = re.match(r"^remember\s+(?:that\s+)?(.+?)\s*$", raw, re.I)
    if match:
        return Intent("remember_note", {"value": match.group(1).strip()})

    match = re.match(r"^(?:search(?:\s+the\s+web)?(?:\s+for)?|web\s+search(?:\s+for)?|look\s+up)\s+(.+)$", raw, re.I)
    if match:
        return Intent("web_search", {"query": match.group(1).strip()})
    match = re.match(r"^open\s+(?:search\s+)?result\s+(\d+)\s*$", raw, re.I)
    if match:
        return Intent("open_search_result", {"index": match.group(1)})

    if any(word in low for word in ("map", "satellite")) and re.match(r"^(?:open|show|find)\s+", raw, re.I):
        return Intent("map", {"place": _clean_place(raw), "satellite": str("satellite" in low)})

    if low in {"open youtube music", "open my youtube music", "open music"}:
        return Intent("youtube_music", {"query": ""})
    match = re.match(r"^(?:play|listen\s+to)\s+(.+?)(?:\s+on\s+youtube\s+music)?\s*$", raw, re.I)
    if match:
        return Intent("youtube_music", {"query": match.group(1).strip()})

    match = re.match(r"^(?:generate|create)\s+(?:an?\s+)?image\s+(?:of\s+)?(.+)$", raw, re.I)
    if match:
        return Intent("image_generate", {"prompt": match.group(1).strip()})
    match = re.match(r"^(?:make|create)\s+(?:a\s+)?poster\s+(?:for\s+)?(.+)$", raw, re.I)
    if match:
        return Intent("poster_generate", {"prompt": match.group(1).strip()})
    if re.match(r"^edit\s+(?:this\s+)?image", raw, re.I):
        return Intent("image_edit", {"prompt": re.sub(r"^edit\s+(?:this\s+)?image\s*:?\s*", "", raw, flags=re.I)})

    if low in {"take a screenshot", "take screenshot", "screenshot"}:
        return Intent("screenshot", {"window": "false"})
    if "screenshot of this window" in low:
        return Intent("screenshot", {"window": "true"})
    if re.search(r"(?:take|capture) (?:a )?(?:photo|picture).*(?:camera|webcam)|(?:take|capture) (?:a )?(?:camera|webcam) (?:photo|picture)", low):
        return Intent("camera")

    match = re.match(r"^(?:analyze|summarize)\s+(?:this\s+)?(?:file|pdf)?\s*(.+)$", raw, re.I)
    if match and match.group(1).strip():
        return Intent("file_analyze", {"path": match.group(1).strip()})
    match = re.match(r"^read\s+(?:file\s+)?(.+)$", raw, re.I)
    if match:
        return Intent("file_read", {"path": match.group(1).strip()})
    match = re.match(r"^write\s+(.+?)\s+to\s+(.+)$", raw, re.I | re.S)
    if match:
        return Intent("file_write", {"content": match.group(1).strip(), "path": match.group(2).strip()})
    match = re.match(r"^open\s+(?:file\s+)?(.+)$", raw, re.I)
    if match and ("/" in match.group(1) or "." in match.group(1) or match.group(1).startswith("~")):
        return Intent("file_open", {"path": match.group(1).strip()})

    match = re.match(r"^(?:run|execute)\s+(.+)$", raw, re.I)
    if match:
        return Intent("terminal", {"command": match.group(1).strip()})
    match = re.match(r"^(?:open|launch|start)\s+(.+)$", raw, re.I)
    if match:
        return Intent("open_app", {"name": match.group(1).strip()})
    return None
