import re

from .actions import ActionPlan, ActionResult
from .capture import take_camera_photo, take_screenshot, take_window_screenshot
from .file_tools import FileService
from .image_tools import ImageService
from .intents import parse_intent
from .tools import system_status, launch_calculator
from .providers import chat, parallel_race, stream_chat
from .workspace import (
    ApplicationLauncher, BraveSearch, TerminalService, build_map_url,
    build_youtube_music_url, open_external_url,
)


class CommandRouter:
    def __init__(self, ollama, memory, provider_store=None, knowledge=None, capabilities=None, integrations=None):
        self.ollama = ollama
        self.memory = memory
        self.provider_store = provider_store
        self.knowledge = knowledge
        self.capabilities = capabilities
        self.integrations = integrations
        self.search = BraveSearch()
        self.files = FileService()
        self.terminal = TerminalService()
        self.last_search_results = []

    def _record_action(self, request, result):
        if isinstance(result, ActionResult):
            self.memory.record("workspace action", request, result.message[:4000], result.ok)
        return result

    def _confirm(self, ui, plan, preference=None):
        if preference and self.memory.personal_enabled() and self.memory.preference(preference, False):
            return True, None
        if not ui or not hasattr(ui, "confirm_action"):
            return False, ActionResult.failure(
                "This action needs an active AXON window so you can review and approve it."
            )
        try:
            approved = bool(ui.confirm_action(plan))
        except Exception as exc:
            return False, ActionResult.failure("AXON could not show the action confirmation.", str(exc))
        if not approved:
            return False, ActionResult.failure("Cancelled. No action was performed.")
        return True, None

    def _plan(self, ui, title, summary, details, preference=None):
        return self._confirm(ui, ActionPlan(title, summary, details), preference)

    def _image_service(self):
        key = self.provider_store.get_key("OpenAI") if self.provider_store else ""
        return ImageService(key)

    def route(self, text, ui=None):
        raw = text.strip()
        low = raw.lower()

        # Deterministic runtime diagnostics: never ask the LLM to invent system status.
        if "self-diagnostic" in low or "capability audit" in low or "runtime capability audit" in low:
            if self.capabilities:
                return ActionResult.success(self.capabilities.text())

        # Deterministic knowledge-graph operations. These use the indexed graph rather
        # than asking the model to fabricate relationships.
        if self.knowledge and "index" in low and "knowledge graph" in low:
            graph = self.knowledge.refresh()
            return ActionResult.success(f"Knowledge graph indexed successfully. indexed=True; nodes={len(graph.nodes)}; edges={len(graph.edges)}; root={self.knowledge.root}")
        if self.knowledge and "knowledge graph" in low and any(k in low for k in ("depend", "relationship", "relationships", "neighbors", "imports")):
            result = self.knowledge.query(raw, limit=100)
            return ActionResult.success(result)

        if self.integrations and ("read my gmail" in low or "read my emails" in low or "check my inbox" in low):
            try:
                msgs = self.integrations.gmail.list_inbox(10)
                lines = [f"{m.id} | {m.sender or 'unknown'} | {m.subject or '(no subject)'} | {(m.snippet or m.body[:180]).replace(chr(10),' ')[:180]}" for m in msgs]
                return ActionResult.success("Gmail inbox:\n" + ("\n".join(lines) if lines else "Inbox is empty."))
            except Exception as exc:
                return ActionResult.failure("Gmail is not ready.", str(exc))
        if self.integrations and "whatsapp" in low and any(k in low for k in ("read", "check", "messages", "chats")):
            try:
                chats = self.integrations.whatsapp_linked.chats(15)
                return ActionResult.success("WhatsApp chats:\n" + ("\n".join(x.get("text","")[:300] for x in chats) if chats else "No chats found."))
            except Exception as exc:
                return ActionResult.failure("WhatsApp linked device is not ready.", str(exc))

        if "calculator" in low and any(word in low for word in ["build", "create", "make", "open", "launch"]):
            approved, result = self._plan(ui, "Open calculator", "Open the AXON Kids Calculator.", "Application: AXON Kids Calculator")
            if not approved:
                return self._record_action(raw, result)
            if ui:
                ui.after(0, launch_calculator)
            return self._record_action(raw, ActionResult.success("Opened the AXON Kids Calculator."))

        if "system status" in low or low in {"status", "system"}:
            status = system_status()
            result = ActionResult.success(
                f"CPU {status['cpu']:.0f}% · RAM {status['ram']:.0f}% · Disk {status['disk']:.0f}% · Host {status['host']}"
            )
            return self._record_action(raw, result)

        if low.startswith(("create a goal", "add goal", "goal:")):
            goal = re.sub(r"^(create a goal|add goal|goal:)\s*", "", raw, flags=re.I).strip() or raw
            self.memory.add_goal(goal)
            return self._record_action(raw, ActionResult.success(f"Goal created: {goal}"))
        if low.startswith(("start mission", "mission:")):
            mission = re.sub(r"^(start mission|mission:)\s*", "", raw, flags=re.I).strip() or raw
            self.memory.add_mission(mission)
            return self._record_action(raw, ActionResult.success(f"Mission queued: {mission}"))
        if low in {"what did you learn", "show learned experience", "show experience"}:
            return ActionResult.success(self.memory.summary())

        intent = parse_intent(raw)
        if not intent:
            return None

        if intent.name == "memory_show":
            return ActionResult.success(self.memory.personal_summary())
        if intent.name == "memory_clear":
            approved, result = self._plan(
                ui, "Clear personal memory", "Erase all saved personal facts, places, aliases, and preferences.",
                "This cannot be undone. Conversation experience and goals are not affected."
            )
            if not approved:
                return self._record_action(raw, result)
            self.memory.clear_personal_memory()
            return self._record_action(raw, ActionResult.success("Cleared personal working memory."))
        if intent.name == "memory_forget":
            ok, message = self.memory.forget(intent.args["key"])
            return self._record_action(raw, ActionResult(ok, message))
        if intent.name == "remember_alias":
            ok, message = self.memory.remember_alias(intent.args["alias"], intent.args["command"])
            return self._record_action(raw, ActionResult(ok, message))
        if intent.name == "remember_fact":
            ok, message = self.memory.remember_fact(intent.args["key"], intent.args["value"])
            return self._record_action(raw, ActionResult(ok, message))
        if intent.name == "remember_note":
            ok, message = self.memory.remember_fact("note", intent.args["value"])
            return self._record_action(raw, ActionResult(ok, message))

        if intent.name == "web_search":
            query = intent.args["query"]
            approved, result = self._plan(ui, "Search the web", f"Search Brave for: {query}", "External service: Brave Search API")
            if not approved:
                return self._record_action(raw, result)
            result = self.search.search(query)
            if result.ok:
                self.last_search_results = result.data.get("results", [])
            return self._record_action(raw, result)
        if intent.name == "open_search_result":
            index = int(intent.args["index"]) - 1
            if not 0 <= index < len(self.last_search_results):
                return ActionResult.failure("That search result is not available. Search the web first, then use “open result 1”.")
            item = self.last_search_results[index]
            approved, result = self._plan(ui, "Open web result", f"Open result {index + 1}: {item['title']}", item["url"], "external_auto_open")
            if not approved:
                return self._record_action(raw, result)
            return self._record_action(raw, open_external_url(item["url"]))

        if intent.name == "map":
            place = intent.args["place"]
            satellite = intent.args.get("satellite") == "True"
            url = build_map_url(place, satellite)
            view = "satellite" if satellite else "standard"
            approved, result = self._plan(ui, "Open map", f"Open {place} in {view} map view.", url, "external_auto_open")
            if not approved:
                return self._record_action(raw, result)
            return self._record_action(raw, open_external_url(url))

        if intent.name == "youtube_music":
            query = intent.args["query"]
            url = build_youtube_music_url(query)
            description = f"Open YouTube Music search for: {query}" if query else "Open YouTube Music."
            approved, result = self._plan(ui, "Open YouTube Music", description, url, "music_auto_open")
            if not approved:
                return self._record_action(raw, result)
            opened = open_external_url(url)
            if opened.ok:
                opened.message = "Opened YouTube Music in your browser. Playback is controlled by YouTube Music and your account."
            return self._record_action(raw, opened)

        if intent.name == "image_generate":
            prompt = intent.args["prompt"]
            approved, result = self._plan(ui, "Generate image", f"Generate image: {prompt}", "External service: OpenAI Images API. A request may use API credits.")
            if not approved:
                return self._record_action(raw, result)
            return self._record_action(raw, self._image_service().generate(prompt))
        if intent.name == "poster_generate":
            prompt = intent.args["prompt"]
            approved, result = self._plan(ui, "Create poster", f"Create a local poster with title: {prompt}", "Output: AXON output folder. The original files will not be changed.")
            if not approved:
                return self._record_action(raw, result)
            return self._record_action(raw, self._image_service().poster(prompt))
        if intent.name == "image_edit":
            return ActionResult.failure("Select an image in the Images page, enter the edit request, then choose Edit Image. AXON always saves a new file.")

        if intent.name == "file_analyze":
            path = intent.args["path"]
            approved, result = self._plan(ui, "Analyze file", f"Read and analyze: {path}", "AXON will read metadata and supported content without changing the file.")
            if not approved:
                return self._record_action(raw, result)
            return self._record_action(raw, self.files.analyze(path))
        if intent.name == "file_read":
            path = intent.args["path"]
            approved, result = self._plan(ui, "Read file", f"Read text file: {path}", "Read-only file access.")
            if not approved:
                return self._record_action(raw, result)
            return self._record_action(raw, self.files.read_text(path))
        if intent.name == "file_write":
            path, content = intent.args["path"], intent.args["content"]
            approved, result = self._plan(ui, "Write file", f"Write text to: {path}", "If this file exists AXON will create a timestamped backup before replacing it.")
            if not approved:
                return self._record_action(raw, result)
            return self._record_action(raw, self.files.write_text(path, content))
        if intent.name == "file_open":
            path = intent.args["path"]
            approved, result = self._plan(ui, "Open file", f"Open file with the desktop application: {path}", "External desktop application launch.")
            if not approved:
                return self._record_action(raw, result)
            return self._record_action(raw, self.files.open_file(path))

        if intent.name == "screenshot":
            description = "Capture this AXON window." if intent.args.get("window") == "true" else "Capture the entire screen."
            approved, result = self._plan(ui, "Take screenshot", description, "Output: AXON output folder. Nothing is captured without this approval.")
            if not approved:
                return self._record_action(raw, result)
            if intent.args.get("window") == "true" and ui:
                return self._record_action(raw, take_window_screenshot(ui.winfo_rootx(), ui.winfo_rooty(), ui.winfo_width(), ui.winfo_height()))
            return self._record_action(raw, take_screenshot())
        if intent.name == "camera":
            approved, result = self._plan(ui, "Take camera photo", "Capture one photo from the default webcam.", "Output: AXON output folder. The camera is not accessed without this approval.")
            if not approved:
                return self._record_action(raw, result)
            return self._record_action(raw, take_camera_photo())

        if intent.name == "terminal":
            command = intent.args["command"]
            validated = self.terminal.validate(command, authorization=False)
            if not validated.ok:
                return self._record_action(raw, validated)
            approved, result = self._plan(ui, "Run Kali command", f"Run command: {command}", f"Working directory: {self.terminal.approved_root}\nElevation: not requested\nShell: not used")
            if not approved:
                return self._record_action(raw, result)
            return self._record_action(raw, self.terminal.run(command, authorization=False))
        if intent.name == "open_app":
            launcher = ApplicationLauncher(self.memory.personal.get("aliases", {}))
            resolved = launcher.resolve(intent.args["name"])
            if not resolved:
                return ActionResult.failure(
                    f"No application alias exists for '{intent.args['name']}'. Say “remember open {intent.args['name']} means open APP” to save one."
                )
            _, command = resolved
            approved, result = self._plan(ui, "Open application", f"Open {intent.args['name']}.", f"Command: {' '.join(command)}\nElevation: not requested")
            if not approved:
                return self._record_action(raw, result)
            return self._record_action(raw, launcher.open(intent.args["name"]))
        return None

    def answer(self, text, fast=False):
        if not self.provider_store:
            return self.ollama.chat(text, system="You are AXON, a concise local-first Kali Linux assistant. Reply in plain text without Markdown or asterisks."), "Ollama", self.ollama.model
        system = ("You are AXON, a concise Kali Linux desktop AI assistant. Never claim a desktop action happened unless a governed tool returned success. Explain commands clearly and briefly. Reply in plain text without Markdown or asterisks.")
        if fast:
            return parallel_race(self.provider_store, text, system=system)[:3]
        return chat(self.provider_store, text, system=system)

    def stream_answer(self, text, on_token):
        if not self.provider_store:
            return self.ollama.chat(text, system="You are AXON, a concise local-first Kali Linux assistant. Reply in plain text without Markdown or asterisks."), "Ollama", self.ollama.model
        system = ("You are AXON, a concise Kali Linux desktop AI assistant. Never claim a desktop action happened unless a governed tool returned success. Explain commands clearly and briefly. Reply in plain text without Markdown or asterisks.")
        return stream_chat(self.provider_store, text, system=system, on_token=on_token)
