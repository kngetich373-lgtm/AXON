"""Browser, web-search, application, and terminal services for AXON Workspace."""
from __future__ import annotations

import os
from pathlib import Path
import shlex
import shutil
import subprocess
import webbrowser
from urllib.parse import quote_plus

import requests

from .actions import ActionResult
from .config import WEB_SEARCH_API_KEY, WEB_SEARCH_PROVIDER


DEFAULT_APP_ALIASES = {
    "terminal": "kitty", "kitty": "kitty", "files": "thunar",
    "browser": "firefox", "firefox": "firefox", "wireshark": "wireshark",
    "code": "code", "vscode": "code", "visual studio code": "code",
    "obsidian": "obsidian", "john": "john", "john the ripper": "john",
}

BLOCKED_COMMANDS = {
    "rm", "dd", "mkfs", "sudo", "su", "shutdown", "reboot", "poweroff",
    "halt", "init", "chmod", "chown", "kill", "killall", "pkill", "systemctl",
}
SECURITY_TOOLS = {
    "nmap", "masscan", "john", "hashcat", "hydra", "msfconsole", "msfvenom",
    "sqlmap", "aircrack-ng", "nikto", "gobuster", "dirb", "feroxbuster", "wpscan",
}
SHELL_METACHARACTERS = set("|;&><`$")


def build_map_url(place: str, satellite: bool = False) -> str:
    """Return a Google Maps URL; Google resolves named places without scraping."""
    normalized = str(place or "world").strip()
    if normalized.lower() in {"world", "the world", "globe"}:
        layer = "/data=!3m1!1e3" if satellite else ""
        return f"https://www.google.com/maps/@0,0,2z{layer}"
    url = "https://www.google.com/maps/search/?api=1&query=" + quote_plus(normalized)
    if satellite:
        # Google Maps accepts this view preference for modern map links and
        # still degrades to the place view if a browser does not honour it.
        url += "&basemap=satellite"
    return url


def build_youtube_music_url(query: str = "") -> str:
    query = str(query or "").strip()
    if not query:
        return "https://music.youtube.com/"
    return "https://music.youtube.com/search?q=" + quote_plus(query)


def open_external_url(url: str) -> ActionResult:
    try:
        opened = webbrowser.open(url, new=2)
    except Exception as exc:
        return ActionResult.failure("AXON could not open the browser.", str(exc), url=url)
    if not opened:
        return ActionResult.failure("AXON could not hand the link to a browser.", url=url)
    return ActionResult.success("Opened the requested page in your browser.", url=url)


class BraveSearch:
    """Official Brave Search API client; AXON does not scrape search engines."""

    endpoint = "https://api.search.brave.com/res/v1/web/search"

    def __init__(self, api_key: str | None = None, provider: str | None = None):
        self.api_key = (api_key if api_key is not None else WEB_SEARCH_API_KEY).strip()
        self.provider = (provider if provider is not None else WEB_SEARCH_PROVIDER).strip().lower()

    def search(self, query: str, count: int = 5) -> ActionResult:
        if self.provider != "brave":
            return ActionResult.failure(
                f"Unsupported web-search provider '{self.provider}'. Configure WEB_SEARCH_PROVIDER=brave.",
            )
        if not self.api_key:
            return ActionResult.failure(
                "Web search is not configured. Add WEB_SEARCH_API_KEY to .env, then restart AXON.",
            )
        try:
            response = requests.get(
                self.endpoint,
                headers={"Accept": "application/json", "X-Subscription-Token": self.api_key},
                params={"q": query, "count": max(1, min(int(count), 10))},
                timeout=20,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            return ActionResult.failure("Web search failed. Check your connection and API key.", str(exc))
        results = []
        for item in payload.get("web", {}).get("results", [])[:count]:
            url = str(item.get("url", "")).strip()
            title = str(item.get("title", url)).strip()
            if url:
                results.append({"title": title, "url": url, "snippet": str(item.get("description", "")).strip()})
        if not results:
            return ActionResult.success(f"No web results found for {query}.", results=[])
        lines = [f"Web results for {query}:"]
        for index, item in enumerate(results, 1):
            lines.append(f"{index}. {item['title']}\n{item['url']}\n{item['snippet']}")
        return ActionResult.success("\n\n".join(lines), results=results, links=results)


class ApplicationLauncher:
    def __init__(self, aliases: dict[str, str] | None = None):
        self.aliases = dict(DEFAULT_APP_ALIASES)
        self.aliases.update({str(k).lower(): str(v) for k, v in (aliases or {}).items()})

    def resolve(self, name: str) -> tuple[str, list[str]] | None:
        requested = str(name or "").strip().lower()
        command = self.aliases.get(requested)
        if not command:
            return None
        # A remembered phrase may be a human-friendly app name rather than an
        # executable. Reuse the built-in registry before parsing arguments.
        command = DEFAULT_APP_ALIASES.get(str(command).strip().lower(), command)
        try:
            args = shlex.split(command)
        except ValueError:
            return None
        return requested, args

    def open(self, name: str) -> ActionResult:
        resolved = self.resolve(name)
        if not resolved:
            return ActionResult.failure(
                f"No application alias exists for '{name}'. Save one with “remember open {name} means open APP”."
            )
        requested, args = resolved
        if not args or shutil.which(args[0]) is None:
            return ActionResult.failure(f"{args[0] if args else requested} is not installed or not on PATH.")
        try:
            subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError as exc:
            return ActionResult.failure(f"Could not open {requested}.", str(exc))
        return ActionResult.success(f"Opened {requested}.", command=args)


class TerminalService:
    """Runs a single, confirmed command without invoking a shell."""

    def __init__(self, approved_root: Path | None = None):
        self.approved_root = (approved_root or Path.cwd()).resolve()

    @staticmethod
    def validate(command: str, authorization: bool = False) -> ActionResult:
        command = str(command or "").strip()
        if not command:
            return ActionResult.failure("No command was provided.")
        if any(char in command for char in SHELL_METACHARACTERS) or "\n" in command:
            return ActionResult.failure("Shell operators, redirection, and command chaining are blocked.")
        try:
            args = shlex.split(command)
        except ValueError as exc:
            return ActionResult.failure("The command could not be parsed safely.", str(exc))
        if not args:
            return ActionResult.failure("No command was provided.")
        executable = Path(args[0]).name.lower()
        if executable in BLOCKED_COMMANDS:
            return ActionResult.failure(f"{executable} is blocked by AXON's safety policy.")
        if executable in SECURITY_TOOLS and not authorization:
            return ActionResult.failure(
                "This security tool requires explicit authorization in Sentinel before it can run."
            )
        return ActionResult.success("Command approved for confirmation.", args=args)

    def run(self, command: str, authorization: bool = False, timeout: int = 45) -> ActionResult:
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            return ActionResult.failure("AXON will not execute user commands as root.")
        validated = self.validate(command, authorization)
        if not validated.ok:
            return validated
        args = validated.data["args"]
        if shutil.which(args[0]) is None:
            return ActionResult.failure(f"{args[0]} is not installed or not on PATH.")
        try:
            completed = subprocess.run(
                args, cwd=self.approved_root, text=True, capture_output=True,
                timeout=max(1, min(int(timeout), 120)), check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return ActionResult.failure("The command could not be started.", str(exc), command=args)
        output = (completed.stdout or "").strip()
        error = (completed.stderr or "").strip()
        message = f"Command finished with exit code {completed.returncode}."
        if output:
            message += f"\n\nOutput:\n{output[:8000]}"
        if error:
            message += f"\n\nErrors:\n{error[:4000]}"
        if completed.returncode:
            return ActionResult.failure(message, command=args, exit_code=completed.returncode, stdout=output, stderr=error)
        return ActionResult.success(message, command=args, exit_code=completed.returncode, stdout=output, stderr=error)
