import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import json
import math
import re
import time
import psutil
import shutil
import subprocess
import logging
from pathlib import Path
from urllib.parse import quote_plus

from .actions import ActionPlan, ActionResult
from .config import AXON_OUTPUT_DIR, OLLAMA_MODEL, WAKE_WORD, GEMINI_API_KEY, GEMINI_LIVE_MODEL, GEMINI_VOICE
from .file_tools import PdfService
from . import config
from .ollama import OllamaClient
from .memory import Memory, MemoryManager
from .router import CommandRouter
from .intents import parse_intent
from .browser_control import browser_control
from .gemini_voice import GeminiLiveVoice
from .tools import system_status, ToolRegistry
from .security import PermissionManager
from .core import Agent, EventBus
from .skills import SkillRegistry
from .knowledge import ProjectKnowledge
from .providers import PROVIDERS, PROFILES, ProviderStore, fetch_models, provider_health, validate_provider, validate_model, choose_candidates
from .workspace import open_external_url
from .integrations import AXONIntegrations
from .capabilities import CapabilityAuditor
from .integrations.tools import register_integration_tools

# AXON V15 visual system — preserve the original gold/glass command-center identity.
BG = "#080706"
SIDEBAR = "#100D09"
PANEL = "#17130E"
PANEL2 = "#21180E"
PANEL3 = "#0D0B09"
INPUT = "#17120D"
BORDER = "#5B4526"
HOVER_BORDER = "#9A6A2B"
TEXT = "#F7F2E8"
MUTED = "#B9AA93"
MUTED_QUIET = "#766A59"
PURPLE = "#7C4DFF"
PURPLE2 = "#A678FF"
CYAN = "#35D69B"
CYAN_SOFT = "#173F32"
GREEN = "#35D69B"
RED = "#FF5B5B"
AMBER = "#F6B84B"
BLUE = "#6FB6FF"
GOLD = "#F4B84A"
GOLD_SOFT = "#8D652E"
GLASS = "#14100C"
USER_BUBBLE = "#4A2A78"
ASSISTANT_BUBBLE = "#21170D"
LOG = logging.getLogger(__name__)

NAV = [
    ("⌂", "Home"), ("◈", "Brain"), ("◎", "Goals"), ("🚀", "Missions"),
    ("◉", "Models"), ("◎", "World"), ("▣", "Knowledge"), ("⬡", "Security"),
    ("◌", "Observe"), ("ϟ", "Voice"), ("▣", "Images"), ("▤", "Files & PDFs"),
    ("◌", "Memory"), ("⬢", "Sentinel"), ("✧", "UI Studio"), ("⚙", "Settings")
]


class AXONApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("AXON 0.1.1 — AI Operating System")
        # Responsive startup: never launch wider/taller than the physical display.
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        width = min(1400, max(980, sw - 40))
        height = min(900, max(650, sh - 80))
        self.geometry(f"{width}x{height}+{max(0, (sw-width)//2)}+{max(0, (sh-height)//2)}")
        self.minsize(980, 650)
        self.configure(bg=BG)
        self.protocol("WM_DELETE_WINDOW", self.shutdown)
        self.ollama = OllamaClient()
        self.memory = Memory()
        self.layered_memory = MemoryManager()
        self.skills = SkillRegistry()
        self.knowledge = ProjectKnowledge(config.PROJECT_ROOT) if hasattr(config, "PROJECT_ROOT") else None
        self.provider_store = ProviderStore(config.PROVIDERS_FILE)
        self.integrations = AXONIntegrations()
        self.capabilities = CapabilityAuditor(self)
        self.router = CommandRouter(self.ollama, self.memory, self.provider_store, self.knowledge, self.capabilities, self.integrations)
        self.event_bus = EventBus()
        self.permissions = PermissionManager()
        self.tool_registry = ToolRegistry(self.permissions)
        self.agent = Agent(self.router, self.memory, self.tool_registry, self.permissions, self.event_bus, self.skills, self.layered_memory, self.knowledge)
        register_integration_tools(self.tool_registry, self.integrations)
        self.tool_registry.register(name="axon.capabilities.audit", description="Run a runtime capability audit using actual AXON state.", handler=lambda context=None, **_: self.capabilities.text(), risk=__import__("axon.security", fromlist=["Risk"]).Risk.LOW, requires_confirmation=False)
        self.tool_registry.register(name="axon.skills.list", description="List installed AXON Agent Skills.", handler=lambda context=None, **_: [s.name for s in self.skills.list()], risk=__import__("axon.security", fromlist=["Risk"]).Risk.LOW, requires_confirmation=False)
        self.tool_registry.register(name="axon.skills.match", description="Find Agent Skills relevant to a request.", handler=lambda request, context=None, **_: [s.name for s in self.skills.match(request)], risk=__import__("axon.security", fromlist=["Risk"]).Risk.LOW, requires_confirmation=False)
        if self.knowledge is not None:
            self.tool_registry.register(name="axon.knowledge.search", description="Search the active project knowledge graph.", handler=lambda query, context=None, **_: [n.__dict__ for n in self.knowledge.search(query)], risk=__import__("axon.security", fromlist=["Risk"]).Risk.LOW, requires_confirmation=False)
        self.gemini_voice = GeminiLiveVoice(GEMINI_API_KEY, self.gemini_voice_text, self.voice_state, GEMINI_LIVE_MODEL, GEMINI_VOICE, on_audio_level=self.voice_audio_level)
        self.gemini_voice.set_output_transcript_callback(self.gemini_voice_output_text)
        self.gemini_voice.set_input_transcript_callbacks(self.gemini_voice_partial_text, self.gemini_voice_error)
        self._voice_output_buffer = ""
        self._shutdown_started = False
        self._voice_output_job = None
        self._voice_ui_jobs = set()
        self._voice_command_lock = threading.Lock()
        self.voice_provider = "gemini"
        self.current_page = "Home"
        self.busy = False
        self._build_shell()
        self.show_page("Home")
        self.refresh()
        self.after(1200, self.auto_voice_start)

    # ---------- visual system ----------
    def card(self, parent, bg=PANEL, **kw):
        return tk.Frame(parent, bg=bg, highlightthickness=1, highlightbackground=BORDER, **kw)

    def label(self, parent, text, size=10, fg=TEXT, bold=False, bg=PANEL, **kw):
        return tk.Label(parent, text=text, bg=bg, fg=fg,
                        font=("DejaVu Sans", size, "bold" if bold else "normal"), **kw)

    def button(self, parent, text, command, accent=False, compact=False, outline=False, **kw):
        """Create a quiet secondary action or the single violet primary action."""
        bg = GOLD if accent else (INPUT if outline else PANEL2)
        fg = "#140F09" if accent else (TEXT if outline else MUTED)
        return tk.Button(
            parent, text=text, command=command, relief="flat", bd=0,
            bg=bg, fg=fg,
            activebackground="#FFD36A" if accent else (HOVER_BORDER if outline else "#1B2940"),
            activeforeground="#FFFFFF", cursor="hand2",
            highlightthickness=1 if outline else 0,
            highlightbackground=BORDER if outline else bg,
            highlightcolor=CYAN if outline else bg,
            font=("DejaVu Sans", 9 if compact else 10, "bold" if accent else "normal"),
            padx=11 if compact else 16, pady=6 if compact else 9, **kw
        )

    def _build_shell(self):
        """Build the original AXON gold/glass command-center shell.

        The V15 backend is deliberately kept independent from this presentation
        layer. Existing pages continue to render inside the same content host.
        """
        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)

        # Global top bar
        self.topbar = tk.Frame(self, bg="#120E0A", height=82, highlightthickness=1, highlightbackground=GOLD_SOFT)
        self.topbar.grid(row=0, column=0, columnspan=2, sticky="ew")
        self.topbar.grid_propagate(False)
        self.topbar.grid_columnconfigure(1, weight=1)

        brand = tk.Frame(self.topbar, bg="#120E0A")
        brand.grid(row=0, column=0, sticky="nsw", padx=(20, 16))
        logo = tk.Canvas(brand, width=54, height=54, bg="#120E0A", highlightthickness=0)
        logo.pack(side="left", pady=13)
        logo.create_oval(4,4,50,50,fill="#1A130B",outline=GOLD,width=2)
        logo.create_text(27,27,text="A",fill=GOLD,font=("DejaVu Sans",22,"bold"))
        btxt=tk.Frame(brand,bg="#120E0A"); btxt.pack(side="left", pady=13)
        self.label(btxt,"AXON",20,TEXT,True,"#120E0A").pack(anchor="w")
        self.label(btxt,"AI OPERATING SYSTEM",8,GOLD,True,"#120E0A").pack(anchor="w")
        self.vlabel=self.label(btxt,"V0.1.1",8,GOLD,True,"#120E0A")
        self.vlabel.pack(anchor="w",pady=(2,0))

        search_shell=tk.Frame(self.topbar,bg=INPUT,highlightthickness=1,highlightbackground=GOLD_SOFT)
        search_shell.grid(row=0,column=1,sticky="ew",padx=8,pady=18)
        search_shell.grid_columnconfigure(1,weight=1)
        tk.Label(search_shell,text="⌕",bg=INPUT,fg=GOLD,font=("DejaVu Sans",20)).grid(row=0,column=0,padx=(14,8))
        self.global_search=tk.Entry(search_shell,bg=INPUT,fg=TEXT,insertbackground=GOLD,relief="flat",bd=0,font=("DejaVu Sans",11))
        self.global_search.insert(0,"Ask AXON anything…")
        self.global_search.grid(row=0,column=1,sticky="ew",ipady=8)
        self.global_search.bind("<FocusIn>",lambda e:self._clear_placeholder(self.global_search,"Ask AXON anything…"))
        self.global_search.bind("<Return>",lambda e:self._quick_prompt(self.global_search.get()))
        self.button(search_shell,"MIC",self.toggle_voice,compact=True,outline=True).grid(row=0,column=2,padx=8)

        telemetry=tk.Frame(self.topbar,bg="#120E0A")
        telemetry.grid(row=0,column=2,sticky="e",padx=(4,20))
        self.cpu_label=self._telemetry_chip(telemetry,"CPU","--")
        self.ram_label=self._telemetry_chip(telemetry,"RAM","--")
        self.gpu_label=self._telemetry_chip(telemetry,"GPU","--")
        self.online=self.label(telemetry,"● Cloud connected",9,GREEN,True,"#120E0A")
        self.online.pack(side="left",padx=10)
        self.label(telemetry,"♢",18,GOLD,True,"#120E0A").pack(side="left",padx=8)
        self.label(telemetry,"●",28,GOLD,True,"#120E0A").pack(side="left",padx=6)

        # Workspace row
        self.sidebar = tk.Frame(self, bg=SIDEBAR, width=220, highlightthickness=1, highlightbackground=GOLD_SOFT)
        self.sidebar.grid(row=1,column=0,sticky="nsew")
        self.sidebar.grid_propagate(False)
        brand2=tk.Frame(self.sidebar,bg=SIDEBAR); brand2.pack(fill="x",padx=18,pady=(16,10))
        self.label(brand2,"✦  WORKSPACE",9,GOLD,True,SIDEBAR).pack(anchor="w")

        # The navigation keeps the original appearance but becomes vertically
        # scrollable when the display is too short to show all entries.  The
        # scrollbar itself is intentionally hidden so the gold/glass UI is not
        # visually altered; mouse-wheel/touchpad scrolling is the interaction.
        self.sidebar_nav_host=tk.Frame(self.sidebar,bg=SIDEBAR)
        self.sidebar_nav_host.pack(fill="both",expand=True)
        self.sidebar_nav_host.pack_propagate(False)
        self.sidebar_nav_canvas=tk.Canvas(self.sidebar_nav_host,bg=SIDEBAR,highlightthickness=0,bd=0)
        self.sidebar_nav_canvas.pack(fill="both",expand=True)
        self.sidebar_nav=tk.Frame(self.sidebar_nav_canvas,bg=SIDEBAR)
        self.sidebar_nav_window=self.sidebar_nav_canvas.create_window((0,0),window=self.sidebar_nav,anchor="nw")
        self.sidebar_nav.bind("<Configure>",self._sidebar_nav_changed)
        self.sidebar_nav_canvas.bind("<Configure>",self._sidebar_nav_viewport_changed)

        self.nav_buttons={}
        for icon,name in NAV:
            item=tk.Frame(self.sidebar_nav,bg=SIDEBAR,height=38)
            item.pack(fill="x",padx=10,pady=2); item.pack_propagate(False)
            accent=tk.Frame(item,bg=SIDEBAR,width=3); accent.pack(side="left",fill="y")
            b=tk.Button(item,text=f"{icon}    {name}",anchor="w",relief="flat",bd=0,bg=SIDEBAR,fg=MUTED,
                        activebackground=PANEL2,activeforeground=TEXT,highlightthickness=0,
                        font=("DejaVu Sans",10),padx=14,pady=0,cursor="hand2",command=lambda n=name:self.show_page(n))
            b.pack(side="left",fill="both",expand=True)
            self.nav_buttons[name]=(item,b,accent)

        self.sidebar_bottom=tk.Frame(self.sidebar,bg=SIDEBAR); self.sidebar_bottom.pack(side="bottom",fill="x",padx=16,pady=14)
        tk.Frame(self.sidebar_bottom,bg=GOLD_SOFT,height=1).pack(fill="x",pady=(0,10))
        self.nav_status=self.label(self.sidebar_bottom,"● Cloud Connected\nϟ Voice Ready",8,MUTED,True,SIDEBAR,justify="left")
        self.nav_status.pack(anchor="w")

        self.main=tk.Frame(self,bg=BG)
        self.main.grid(row=1,column=1,sticky="nsew")
        self.main.grid_rowconfigure(0,weight=1); self.main.grid_columnconfigure(0,weight=1)
        self.content_host=tk.Frame(self.main,bg=BG)
        self.content_host.grid(row=0,column=0,sticky="nsew")
        self.content_host.grid_rowconfigure(0,weight=1); self.content_host.grid_columnconfigure(0,weight=1)
        self.content_canvas=tk.Canvas(self.content_host,bg=BG,highlightthickness=0,bd=0)
        self.content_canvas.grid(row=0,column=0,sticky="nsew")
        style=ttk.Style(self)
        try: style.theme_use("clam")
        except tk.TclError: pass
        style.configure("Axon.Vertical.TScrollbar",background="#2A2116",troughcolor=BG,bordercolor=BG,arrowcolor=GOLD,lightcolor="#2A2116",darkcolor="#2A2116")
        self.content_scroll=ttk.Scrollbar(self.content_host,orient="vertical",command=self.content_canvas.yview,style="Axon.Vertical.TScrollbar")
        self.content_scroll.grid(row=0,column=1,sticky="ns",padx=(0,4),pady=8)
        self.content_canvas.configure(yscrollcommand=self.content_scroll.set)
        self.content=tk.Frame(self.content_canvas,bg=BG)
        self.content_window=self.content_canvas.create_window((0,0),window=self.content,anchor="nw")
        self.content.bind("<Configure>",self._content_changed)
        self.content_canvas.bind("<Configure>",self._content_viewport_changed)

        # Use one application-level wheel dispatcher so scrolling also works
        # when the pointer is over labels, buttons, entries, cards, or other
        # child widgets instead of only when it is directly over the canvas.
        # This is important for Linux touchpads, which commonly deliver
        # high-resolution <MouseWheel> events to the widget under the pointer.
        self.bind_all("<MouseWheel>",self._global_mousewheel,add="+")
        self.bind_all("<Button-4>",self._global_mousewheel,add="+")
        self.bind_all("<Button-5>",self._global_mousewheel,add="+")

    def _telemetry_chip(self,parent,title,value):
        f=tk.Frame(parent,bg="#120E0A",highlightthickness=1,highlightbackground=GOLD_SOFT)
        f.pack(side="left",padx=3)
        tk.Label(f,text=title,bg="#120E0A",fg=MUTED,font=("DejaVu Sans",7,"bold")).pack(side="left",padx=(7,3),pady=5)
        v=tk.Label(f,text=value,bg="#120E0A",fg=GREEN,font=("DejaVu Sans",9,"bold"))
        v.pack(side="left",padx=(0,7),pady=5)
        return v

    def _clear_placeholder(self,entry,placeholder):
        if entry.get()==placeholder:
            entry.delete(0,"end")

    def card(self,parent,bg=PANEL,**kw):
        return tk.Frame(parent,bg=bg,highlightthickness=1,highlightbackground=GOLD_SOFT,**kw)

    def label(self,parent,text,size=10,fg=TEXT,bold=False,bg=PANEL,**kw):
        return tk.Label(parent,text=text,bg=bg,fg=fg,font=("DejaVu Sans",size,"bold" if bold else "normal"),**kw)

    def button(self,parent,text,command,accent=False,compact=False,outline=False,**kw):
        bg=GOLD if accent else (INPUT if outline else PANEL2)
        fg="#17110A" if accent else (TEXT if outline else MUTED)
        return tk.Button(parent,text=text,command=command,relief="flat",bd=0,bg=bg,fg=fg,
                         activebackground="#FFD57A" if accent else HOVER_BORDER,activeforeground="#17110A" if accent else TEXT,
                         cursor="hand2",highlightthickness=1,highlightbackground=GOLD_SOFT,highlightcolor=GOLD,
                         font=("DejaVu Sans",9 if compact else 10,"bold" if accent else "normal"),
                         padx=11 if compact else 16,pady=6 if compact else 9,**kw)

    def _content_changed(self, _event=None):
        # Preserve the original page layout while allowing long pages (notably
        # Settings, Providers, Memory, Knowledge, and Security) to extend past
        # the viewport.  Home remains locked to the viewport as before.
        try:
            self.content.update_idletasks()
            if self.current_page != "Home":
                required_height = max(self.content_canvas.winfo_height(), self.content.winfo_reqheight())
                self.content_canvas.itemconfigure(self.content_window, height=required_height)
            self.content_canvas.configure(scrollregion=self.content_canvas.bbox("all"))
        except Exception:
            pass

    def _content_viewport_changed(self, event):
        self.content_canvas.itemconfigure(self.content_window, width=event.width)
        if self.current_page == "Home":
            self.content_canvas.itemconfigure(self.content_window, height=event.height)
        else:
            self.after_idle(self._refresh_content_scroll)

    def _refresh_content_scroll(self):
        """Recompute long-page height after Tk finishes child geometry."""
        if not hasattr(self, "content_canvas") or not self.content_canvas.winfo_exists():
            return
        try:
            self.content.update_idletasks()
            required_height = max(self.content_canvas.winfo_height(), self.content.winfo_reqheight())
            self.content_canvas.itemconfigure(self.content_window, height=required_height)
            self.content_canvas.configure(scrollregion=self.content_canvas.bbox("all"))
        except Exception:
            pass

    def _content_mousewheel(self, event):
        """Scroll the main content with wheel/touchpad input."""
        try:
            delta = getattr(event, "delta", 0)
            if delta:
                # Tk reports +/-120 for a traditional wheel, while many
                # touchpads report smaller high-resolution deltas.  Treat a
                # small non-zero delta as one logical unit.
                steps = int(-delta / 120) if abs(delta) >= 120 else (-1 if delta > 0 else 1)
            elif getattr(event, "num", None) == 4:
                steps = -3
            elif getattr(event, "num", None) == 5:
                steps = 3
            else:
                return
            self.content_canvas.yview_scroll(steps, "units")
        except Exception:
            pass

    def _sidebar_nav_changed(self, _event=None):
        if hasattr(self, "sidebar_nav_canvas"):
            self.sidebar_nav_canvas.configure(scrollregion=self.sidebar_nav_canvas.bbox("all"))

    def _sidebar_nav_viewport_changed(self, event):
        if hasattr(self, "sidebar_nav_canvas"):
            self.sidebar_nav_canvas.itemconfigure(self.sidebar_nav_window, width=event.width)
            self.sidebar_nav_canvas.configure(scrollregion=self.sidebar_nav_canvas.bbox("all"))

    def _pointer_inside(self, widget, root_x, root_y):
        try:
            x0, y0 = widget.winfo_rootx(), widget.winfo_rooty()
            x1, y1 = x0 + widget.winfo_width(), y0 + widget.winfo_height()
            return x0 <= root_x < x1 and y0 <= root_y < y1
        except Exception:
            return False

    def _global_mousewheel(self, event):
        """Route wheel/touchpad scrolling to the region under the pointer."""
        try:
            root_x, root_y = event.x_root, event.y_root
            if hasattr(self, "sidebar_nav_canvas") and self._pointer_inside(self.sidebar_nav_host, root_x, root_y):
                if getattr(event, "delta", 0):
                    delta = event.delta
                    steps = int(-delta / 120) if abs(delta) >= 120 else (-1 if delta > 0 else 1)
                elif getattr(event, "num", None) == 4:
                    steps = -3
                elif getattr(event, "num", None) == 5:
                    steps = 3
                else:
                    return "break"
                self.sidebar_nav_canvas.yview_scroll(steps, "units")
                return "break"

            if hasattr(self, "content_host") and self._pointer_inside(self.content_host, root_x, root_y):
                self._content_mousewheel(event)
                return "break"
        except Exception:
            pass
        return None

    def _voice_widget_alive(self, name):
        """Return True only when a Voice-page widget is still alive."""
        try:
            widget = getattr(self, name, None)
            return widget is not None and bool(widget.winfo_exists())
        except (tk.TclError, RuntimeError, AttributeError):
            return False

    def _cancel_voice_output_job(self):
        job = getattr(self, "_voice_output_job", None)
        if job is not None:
            try:
                self.after_cancel(job)
            except (tk.TclError, RuntimeError):
                pass
        self._voice_output_job = None

    def _voice_after(self, delay, callback):
        """Schedule a Voice-only Tk callback that is safe across navigation."""
        holder = {}
        def guarded():
            job = holder.get("job")
            jobs = getattr(self, "_voice_ui_jobs", set())
            if job is not None:
                jobs.discard(job)
            if getattr(self, "_shutdown_started", False) or getattr(self, "current_page", None) != "Voice":
                return
            try:
                callback()
            except (tk.TclError, RuntimeError):
                pass
        try:
            holder["job"] = self.after(delay, guarded)
            self._voice_ui_jobs.add(holder["job"])
            return holder["job"]
        except (tk.TclError, RuntimeError):
            return None

    def _cancel_voice_jobs(self):
        self._cancel_voice_output_job()
        for job in list(getattr(self, "_voice_ui_jobs", set())):
            try:
                self.after_cancel(job)
            except (tk.TclError, RuntimeError):
                pass
        getattr(self, "_voice_ui_jobs", set()).clear()

    def clear_content(self, leaving_page=None):
        # Voice output transcription is delivered asynchronously. Cancel any
        # pending UI flush before destroying the Voice page widgets.
        if leaving_page == "Voice":
            self._cancel_voice_jobs()
        for w in self.content.winfo_children():
            w.destroy()
        # Drop references to page-local Voice widgets so late callbacks cannot
        # accidentally target stale Tk commands.
        if leaving_page == "Voice":
            for name in ("voice_diag", "voice_state_label", "voice_status",
                         "voice_connection_label", "voice_transcript"):
                if hasattr(self, name):
                    setattr(self, name, None)

    def show_page(self,page):
        leaving_page = getattr(self, "current_page", None)
        self.clear_content(leaving_page)
        self.current_page=page
        self.content_canvas.yview_moveto(0)
        for name,(item,button,accent) in self.nav_buttons.items():
            active=name==page
            item.configure(bg=PANEL2 if active else SIDEBAR)
            accent.configure(bg=GOLD if active else SIDEBAR)
            button.configure(bg=PANEL2 if active else SIDEBAR,fg=TEXT if active else MUTED,
                             font=("DejaVu Sans",10,"bold" if active else "normal"))
        builders={
            "Home":self.page_home,"Brain":self.page_brain,"Goals":self.page_goals,
            "Missions":self.page_missions,"Models":self.page_models,"World":self.page_world,
            "Knowledge":self.page_knowledge,"Security":self.page_security,"Observe":self.page_observe,
            "Voice":self.page_voice,"Images":self.page_images,"Files & PDFs":self.page_files,
            "Memory":self.page_memory,"Sentinel":self.page_security,"UI Studio":self.page_ui,"Settings":self.page_settings}
        builders.get(page,self.page_home)()
        # Child widgets often settle their requested height one idle cycle
        # after the page builder returns. Recompute then so long pages are
        # genuinely scrollable on short displays.
        if page != "Home":
            self.after_idle(self._refresh_content_scroll)

    def time_greeting(self):
        from datetime import datetime
        h=datetime.now().hour
        if 5 <= h < 12: word="Good morning"
        elif 12 <= h < 17: word="Good afternoon"
        else: word="Good evening"
        return f"{word}, Lessan"

    # ---------- home ----------
    def page_home(self):
        """Compact command center: preserve AXON identity while giving chat most of the viewport."""
        self.content.grid_rowconfigure(0, weight=1); self.content.grid_columnconfigure(0, weight=1)
        home=tk.Frame(self.content,bg=BG); home.grid(row=0,column=0,sticky="nsew",padx=18,pady=12)
        home.grid_columnconfigure(0,weight=1); home.grid_columnconfigure(1,minsize=270); home.grid_rowconfigure(1,weight=1)

        # Compact hero — deliberately shorter so the conversation is visible immediately.
        hero=tk.Frame(home,bg="#15100B",highlightthickness=1,highlightbackground=GOLD_SOFT,height=132)
        hero.grid(row=0,column=0,columnspan=2,sticky="ew",pady=(0,10)); hero.grid_propagate(False); hero.grid_columnconfigure(0,weight=1)
        left=tk.Frame(hero,bg="#15100B"); left.grid(row=0,column=0,sticky="nsew",padx=22,pady=12)
        self.label(left,"COMMAND CENTER  /  HOME",9,GOLD,True,"#15100B").pack(anchor="w")
        self.greeting_label=self.label(left,self.time_greeting()+"  👋",17,TEXT,True,"#15100B"); self.greeting_label.pack(anchor="w",pady=(2,0))
        self.label(left,"Ask, plan, create, automate — AXON keeps the work organized.",9,MUTED,bg="#15100B").pack(anchor="w")
        quick=tk.Frame(left,bg="#15100B"); quick.pack(anchor="w",pady=(8,0))
        for title,cmd,accent in [
            ("🔗 Analyze Link",lambda:self._quick_prompt("Analyze this URL for phishing risk: "),True),
            ("</> Write Code",lambda:self._quick_prompt("Help me write or debug this code: "),False),
            ("✦ Check System",lambda:self._quick_prompt("Show my current system status"),False),
            ("🚀 New Mission",lambda:self._quick_prompt("Start mission: "),False)]:
            self.button(quick,title,cmd,accent=accent,compact=True).pack(side="left",padx=(0,7))
        visual=tk.Canvas(hero,width=250,height=100,bg="#15100B",highlightthickness=0); visual.grid(row=0,column=1,sticky="e",padx=14)
        for x,h in [(12,25),(36,42),(60,34),(84,57),(108,39),(132,67),(156,46),(180,56),(204,34)]:
            visual.create_rectangle(x,80-h,x+14,80,fill="#21170D",outline=GOLD_SOFT)
        visual.create_oval(170,5,216,51,fill=GOLD,outline="")
        visual.create_text(125,91,text="AXON COMMAND CENTER",fill=GOLD,font=("DejaVu Sans",8,"bold"))

        # Main workspace: chat dominates; right pulse remains compact.
        chat=self.card(home,bg=PANEL3); chat.grid(row=1,column=0,sticky="nsew",padx=(0,10)); chat.grid_columnconfigure(0,weight=1); chat.grid_rowconfigure(1,weight=1)
        head=tk.Frame(chat,bg=PANEL3); head.grid(row=0,column=0,sticky="ew",padx=18,pady=(12,7)); head.grid_columnconfigure(0,weight=1)
        self.label(head,"◈  ACTIVE THREAD",9,GOLD,True,PANEL3).grid(row=0,column=0,sticky="w")
        self.label(head,"Conversation",15,TEXT,True,PANEL3).grid(row=1,column=0,sticky="w")
        self.label(head,"Ask naturally. AXON will keep the work organized.",8,MUTED,bg=PANEL3).grid(row=2,column=0,sticky="w")
        self.copy_conversation_button=tk.Button(head,text="⧉",command=self._copy_conversation,relief="flat",bd=0,bg=PANEL3,fg=MUTED,activebackground=PANEL3,activeforeground=GOLD,cursor="hand2",font=("DejaVu Sans",8),padx=2,pady=0,width=2,highlightthickness=0)
        self.copy_conversation_button.grid(row=0,column=1,rowspan=3,sticky="ne")
        feed=tk.Frame(chat,bg=PANEL3); feed.grid(row=1,column=0,sticky="nsew",padx=8); feed.grid_rowconfigure(0,weight=1); feed.grid_columnconfigure(0,weight=1)
        self.conversation_canvas=tk.Canvas(feed,bg=PANEL3,highlightthickness=0,bd=0); self.conversation_canvas.grid(row=0,column=0,sticky="nsew")
        self.conversation_scroll=ttk.Scrollbar(feed,orient="vertical",command=self.conversation_canvas.yview,style="Axon.Vertical.TScrollbar"); self.conversation_scroll.grid(row=0,column=1,sticky="ns",padx=(3,0))
        self.conversation_canvas.configure(yscrollcommand=self.conversation_scroll.set)
        self.message_feed=tk.Frame(self.conversation_canvas,bg=PANEL3); self.message_feed_window=self.conversation_canvas.create_window((0,0),window=self.message_feed,anchor="nw")
        self.message_feed.bind("<Configure>",self._conversation_changed); self.conversation_canvas.bind("<Configure>",self._conversation_viewport_changed); self.conversation_canvas.bind("<MouseWheel>",self._conversation_mousewheel)
        self.conversation_canvas.bind("<Button-4>",self._conversation_linux_scroll_up); self.conversation_canvas.bind("<Button-5>",self._conversation_linux_scroll_down)
        self._message_bodies=[]; self._conversation_records=[]; self._conversation_scroll_remainder=0.0; self._stream_message=None; self._stream_text=""; self._add_message("assistant","What would you like to work on?")

        composer=tk.Frame(chat,bg=PANEL3); composer.grid(row=2,column=0,sticky="ew",padx=14,pady=10); composer.grid_columnconfigure(1,weight=1)
        self.button(composer,"📎",lambda:None,compact=True,outline=True).grid(row=0,column=0,padx=(0,5))
        self.input_card=self.card(composer,bg=INPUT); self.input_card.grid(row=0,column=1,sticky="ew",padx=(0,5)); self.input_card.grid_columnconfigure(0,weight=1)
        self.input=tk.Entry(self.input_card,bg=INPUT,fg=TEXT,insertbackground=GOLD,relief="flat",bd=0,font=("DejaVu Sans",10)); self.input.grid(row=0,column=0,sticky="ew",ipady=9,padx=11,pady=1); self.input.bind("<Return>",lambda _e:self.submit()); self.input.bind("<FocusIn>",lambda _e:self._set_composer_focus(True)); self.input.bind("<FocusOut>",lambda _e:self._set_composer_focus(False))
        self.button(composer,"REFINE",lambda:self._quick_prompt("Refine: "+self.input.get()),compact=True,outline=True).grid(row=0,column=2,padx=2)
        self.button(composer,"AUTO",lambda:self._quick_prompt("Enable autonomous planning for: "+self.input.get()),compact=True,outline=True).grid(row=0,column=3,padx=2)
        self.button(composer,"🎙",self.toggle_voice,compact=True,outline=True).grid(row=0,column=4,padx=2)
        self.button(composer,"SEND ➤",self.submit,accent=True,compact=True).grid(row=0,column=5,padx=(2,0))

        right=tk.Frame(home,bg=BG); right.grid(row=1,column=1,sticky="nsew")
        voice=self.card(right,bg=PANEL); voice.pack(fill="x",pady=(0,8)); voice.configure(height=98); voice.pack_propagate(False)
        self.label(voice,"ϟ  AXON VOICE",9,TEXT,True,PANEL).pack(anchor="w",padx=14,pady=(12,4))
        self.voice_chip=self.label(voice,"●  Listening" if self.gemini_voice.running else "●  Ready",9,GREEN if self.gemini_voice.running else MUTED,True,PANEL); self.voice_chip.pack(anchor="w",padx=14)
        self.label(voice,"Hands-free command input is ready.",8,MUTED,bg=PANEL).pack(anchor="w",padx=14,pady=(5,0))
        pulse=self.card(right,bg=PANEL); pulse.pack(fill="x",pady=(0,8)); pulse.configure(height=140); pulse.pack_propagate(False)
        self.label(pulse,"✦  WORKSPACE PULSE",9,TEXT,True,PANEL).pack(anchor="w",padx=14,pady=(12,6))
        self.home_status=self.mini_card(pulse,"SYSTEM STATUS","Cloud Connected\nϟ Voice Ready",height=82); self.home_status.pack(fill="both",expand=True,padx=7,pady=(0,7))
        self.home_goal=self.mini_card(right,"◎  ACTIVE GOALS","No active goals.",height=105); self.home_goal.pack(fill="x",pady=(0,8))
        self.home_mission=self.mini_card(right,"🚀  ACTIVE MISSIONS","No active missions.",height=105); self.home_mission.pack(fill="x")

    def mini_card(self,parent,title,text,height=120):
        f=self.card(parent,bg=PANEL); f.configure(height=height); f.pack_propagate(False)
        self.label(f,title,9,GOLD,True,PANEL).pack(anchor="w",padx=14,pady=(12,5))
        l=self.label(f,text,10,TEXT,bg=PANEL,justify="left",anchor="nw",wraplength=240); l.pack(fill="both",expand=True,padx=14,pady=(0,12)); f.label=l
        return f
    def _quick_prompt(self,prompt):
        if hasattr(self,"input"):
            self.input.delete(0,"end"); self.input.insert(0,prompt); self.input.focus_set()

    def mini_card(self,parent,title,text,height=120):
        f=self.card(parent); f.configure(height=height); f.pack_propagate(False)
        self.label(f,title,9,MUTED,True,PANEL).pack(anchor="w",padx=14,pady=(12,5))
        l=self.label(f,text,10,TEXT,bg=PANEL,justify="left",anchor="nw",wraplength=216)
        l.pack(fill="both",expand=True,padx=14,pady=(0,12)); f.label=l
        return f

    def _set_composer_focus(self, focused):
        if hasattr(self, "input_card") and self.input_card.winfo_exists():
            self.input_card.configure(highlightbackground=CYAN if focused else BORDER)

    def _conversation_changed(self, _event=None):
        if hasattr(self, "conversation_canvas") and self.conversation_canvas.winfo_exists():
            self.conversation_canvas.configure(scrollregion=self.conversation_canvas.bbox("all"))

    def _conversation_viewport_changed(self, event):
        self.conversation_canvas.itemconfigure(self.message_feed_window, width=event.width)
        wrap = max(260, min(620, event.width - 118))
        for body in getattr(self, "_message_bodies", []):
            if body.winfo_exists():
                body.configure(wraplength=wrap)

    def _conversation_mousewheel(self, event):
        """Scroll the chat at half the previous speed, including touchpads."""
        try:
            delta = float(getattr(event, "delta", 0) or 0)
            # Tk reports traditional wheels around +/-120; touchpads can emit
            # much smaller deltas. Accumulate fractional movement so small
            # touchpad gestures remain smooth instead of being ignored.
            self._conversation_scroll_remainder += (-delta / 240.0)
            steps = int(self._conversation_scroll_remainder)
            if steps:
                self._conversation_scroll_remainder -= steps
                self.conversation_canvas.yview_scroll(steps, "units")
        except Exception:
            pass

    def _conversation_linux_scroll_up(self, _event=None):
        # Half the old 3-unit jump while keeping legacy Linux wheel support.
        self.conversation_canvas.yview_scroll(-1, "units")
        return "break"

    def _conversation_linux_scroll_down(self, _event=None):
        self.conversation_canvas.yview_scroll(1, "units")
        return "break"

    def _bind_conversation_wheel(self, widget):
        """Let the single feed scrollbar work while hovering over a bubble."""
        widget.bind("<MouseWheel>", self._conversation_mousewheel)
        widget.bind("<Button-4>", self._conversation_linux_scroll_up)
        widget.bind("<Button-5>", self._conversation_linux_scroll_down)

    def _scroll_conversation_to_end(self):
        if hasattr(self, "conversation_canvas") and self.conversation_canvas.winfo_exists():
            self.conversation_canvas.update_idletasks()
            self.conversation_canvas.yview_moveto(1.0)

    def _add_message(self, role, text, links=None):
        """Render one message group; labels and message bodies never share a line."""
        if not hasattr(self, "message_feed") or not self.message_feed.winfo_exists():
            return None
        is_user = role == "user"
        row = tk.Frame(self.message_feed, bg=PANEL3)
        row.pack(fill="x", padx=16, pady=(0, 14))
        shell = tk.Frame(row, bg=PANEL3)
        shell.pack(anchor="e" if is_user else "w")
        if is_user:
            self.label(shell, "You", 9, MUTED, True, PANEL3).pack(anchor="e", pady=(0, 5))
        bubble = tk.Frame(
            shell, bg=USER_BUBBLE if is_user else ASSISTANT_BUBBLE,
            highlightthickness=1, highlightbackground=CYAN_SOFT if is_user else BORDER
        )
        bubble.pack(anchor="e" if is_user else "w")
        value = tk.StringVar(value=text)
        if not is_user:
            tiny = tk.Frame(bubble, bg=ASSISTANT_BUBBLE)
            tiny.pack(fill="x", padx=8, pady=(4,0))
            copy_btn = tk.Button(tiny, text="⧉", command=lambda v=value:self._copy_message(v), relief="flat", bd=0, bg=ASSISTANT_BUBBLE, fg=MUTED_QUIET, activebackground=ASSISTANT_BUBBLE, activeforeground=GOLD, font=("DejaVu Sans",8), padx=2, pady=0, width=2, highlightthickness=0, cursor="hand2")
            copy_btn.pack(side="right")
        body = tk.Label(
            bubble, textvariable=value, bg=USER_BUBBLE if is_user else ASSISTANT_BUBBLE,
            fg=TEXT, justify="left", anchor="w", wraplength=540,
            font=("DejaVu Sans", 11), padx=14, pady=8
        )
        body.pack()
        for link in links or []:
            title, url = str(link.get("title", "Open result")), str(link.get("url", ""))
            if not url:
                continue
            label = tk.Label(
                bubble, text=title, bg=ASSISTANT_BUBBLE, fg=CYAN, cursor="hand2",
                justify="left", anchor="w", wraplength=540, font=("DejaVu Sans", 10, "underline"), padx=14
            )
            label.pack(anchor="w", pady=(0, 6))
            label.bind("<Button-1>", lambda _event, t=title, u=url: self._open_chat_link(t, u))
            self._bind_conversation_wheel(label)
        for widget in (row, shell, bubble, body):
            self._bind_conversation_wheel(widget)
        self._message_bodies.append(body)
        if not hasattr(self, "_conversation_records"):
            self._conversation_records = []
        record = {"role": "You" if is_user else "AXON", "value": value}
        self._conversation_records.append(record)
        self.after_idle(self._scroll_conversation_to_end)
        return {"value": value, "body": body, "record": record}

    def _copy_message(self, value):
        try:
            text = str(value.get() or "").strip()
            if not text: return
            self.clipboard_clear(); self.clipboard_append(text); self.update_idletasks()
        except Exception:
            pass

    def _copy_conversation(self):
        """Copy the complete visible chat transcript to the system clipboard."""
        try:
            lines = []
            for record in getattr(self, "_conversation_records", []):
                text = str(record["value"].get() or "").strip()
                if text:
                    lines.append(f'{record["role"]}:\n{text}')
            transcript = "\n\n".join(lines)
            if not transcript:
                return
            self.clipboard_clear()
            self.clipboard_append(transcript)
            self.update_idletasks()
            # Briefly acknowledge the copy without changing the layout.
            if hasattr(self, "copy_conversation_button") and self.copy_conversation_button.winfo_exists():
                self.copy_conversation_button.configure(text="✓", fg=GREEN)
                self.after(900, lambda: self.copy_conversation_button.winfo_exists() and self.copy_conversation_button.configure(text="⧉", fg=MUTED))
        except Exception:
            pass

    def _open_chat_link(self, title, url):
        plan = ActionPlan("Open web result", f"Open: {title}", url)
        if not self.confirm_action(plan):
            self.respond("Cancelled. No action was performed.")
            return
        result = open_external_url(url)
        self.respond(result.message)

    def confirm_action(self, plan):
        """Show the user-visible action plan on Tk's main thread and wait for approval."""
        answer, ready = {"approved": False}, threading.Event()

        def ask():
            try:
                if self.current_page == "Home":
                    self._add_message("assistant", f"Planned action: {plan.summary}\n\n{plan.details}")
                answer["approved"] = messagebox.askyesno(
                    plan.title, f"{plan.summary}\n\n{plan.details}\n\nContinue?", parent=self
                )
            finally:
                ready.set()

        if threading.current_thread() is threading.main_thread():
            ask()
        else:
            try:
                self.after(0, ask)
            except (RuntimeError, tk.TclError):
                return False
            ready.wait(120)
        return bool(answer["approved"])

    # ---------- other pages ----------
    def page_brain(self):
        self.two_col_header("LOCAL BRAIN", "Fast interaction with your configured Ollama model.")
        box=self.card(self.content); box.pack(fill="both",expand=True,pady=16)
        self.label(box,"MODEL INTERFACE",12,TEXT,True,PANEL).pack(anchor="w",padx=20,pady=(18,3))
        self.label(box,f"Provider: Ollama    Model: {OLLAMA_MODEL}",9,MUTED,bg=PANEL).pack(anchor="w",padx=20)
        self.brain_input=tk.Text(box,bg=PANEL3,fg=TEXT,insertbackground=TEXT,relief="flat",font=("DejaVu Sans",11),height=7); self.brain_input.pack(fill="x",padx=20,pady=18)
        self.button(box,"ASK LOCAL MODEL",lambda:self.ask_brain(),accent=True).pack(anchor="w",padx=20)
        self.brain_out=self.label(box,"",10,TEXT,bg=PANEL,justify="left",anchor="nw",wraplength=900); self.brain_out.pack(fill="both",expand=True,padx=20,pady=20)

    def page_goals(self):
        self.two_col_header("GOALS", "Persistent objectives that survive restarts and feed the mission layer.")
        panel=self.card(self.content); panel.pack(fill="both",expand=True,pady=16)
        bar=tk.Frame(panel,bg=PANEL); bar.pack(fill="x",padx=18,pady=18); bar.grid_columnconfigure(0,weight=1)
        e=tk.Entry(bar,bg=PANEL2,fg=TEXT,insertbackground=TEXT,relief="flat",font=("DejaVu Sans",10)); e.grid(row=0,column=0,sticky="ew",ipady=10,padx=(0,8))
        self.button(bar,"CREATE GOAL",lambda:(self.memory.add_goal(e.get().strip()),e.delete(0,"end"),self.show_page("Goals")),accent=True,compact=True).grid(row=0,column=1)
        self.goal_list=self.label(panel,"",10,TEXT,bg=PANEL,justify="left",anchor="nw"); self.goal_list.pack(fill="both",expand=True,padx=20,pady=8); self.render_goals()

    def render_goals(self):
        if self._widget_alive(getattr(self, "goal_list", None)):
            goals=self.memory.active_goals(); self.goal_list.configure(text="\n\n".join(f"●  {g['text']}\n    ACTIVE · {g['created']}" for g in goals) or "No active goals.")

    def page_missions(self):
        self.two_col_header("MISSIONS", "Executable objectives with visible state and results.")
        panel=self.card(self.content); panel.pack(fill="both",expand=True,pady=16)
        bar=tk.Frame(panel,bg=PANEL); bar.pack(fill="x",padx=18,pady=18); bar.grid_columnconfigure(0,weight=1)
        e=tk.Entry(bar,bg=PANEL2,fg=TEXT,insertbackground=TEXT,relief="flat",font=("DejaVu Sans",10)); e.grid(row=0,column=0,sticky="ew",ipady=10,padx=(0,8))
        self.button(bar,"START MISSION",lambda:(self.memory.add_mission(e.get().strip()),e.delete(0,"end"),self.show_page("Missions")),accent=True,compact=True).grid(row=0,column=1)
        self.mission_list=self.label(panel,"",10,TEXT,bg=PANEL,justify="left",anchor="nw"); self.mission_list.pack(fill="both",expand=True,padx=20,pady=8); self.render_missions()

    def render_missions(self):
        if self._widget_alive(getattr(self, "mission_list", None)):
            ms=self.memory.active_missions(); self.mission_list.configure(text="\n\n".join(f"ϟ  {m['text']}\n    RUNNING · {m['created']}" for m in ms) or "No active missions.")

    def page_models(self):
        self.two_col_header("MODEL CONTROL CENTER", "Every imported model has a connectivity state, capability profile and runtime metrics.")
        grid=tk.Frame(self.content,bg=BG); grid.pack(fill="both",expand=True,pady=16); grid.grid_columnconfigure(0,weight=1); grid.grid_columnconfigure(1,weight=1); grid.grid_rowconfigure(1,weight=1)
        summary=self.card(grid); summary.grid(row=0,column=0,columnspan=2,sticky="ew",pady=(0,10));
        self.models_summary=self.label(summary,"Checking provider health…",10,TEXT,bg=PANEL,justify="left",anchor="w"); self.models_summary.pack(fill="x",padx=18,pady=16)
        left=self.card(grid); left.grid(row=2,column=0,sticky="nsew",padx=(0,6));
        self.label(left,"PROVIDERS",11,TEXT,True,PANEL).pack(anchor="w",padx=18,pady=(16,6))
        self.provider_models_box=self.label(left,"",9,TEXT,bg=PANEL,justify="left",anchor="nw",wraplength=520); self.provider_models_box.pack(fill="both",expand=True,padx=18,pady=10)
        self.button(left,"TEST ALL CONNECTIONS",self.test_all_connections,accent=True,compact=True).pack(anchor="w",padx=18,pady=(4,6))
        self.button(left,"VERIFY ALL CHAT MODELS",self.verify_all_models,compact=True).pack(anchor="w",padx=18,pady=(0,16))
        right=self.card(grid); right.grid(row=1,column=1,sticky="nsew",padx=(6,0));
        self.label(right,"ROUTING PREVIEW",11,TEXT,True,PANEL).pack(anchor="w",padx=18,pady=(16,6))
        self.label(right,"Top candidates are selected from capability, latency, availability, profile and learned performance.",8,MUTED,bg=PANEL,wraplength=520,justify="left").pack(anchor="w",padx=18,pady=(0,10))
        self.routing_preview=tk.Text(right,bg=PANEL3,fg=TEXT,relief="flat",bd=0,font=("DejaVu Sans",9),wrap="word",height=10); self.routing_preview.pack(fill="both",expand=True,padx=18,pady=10); self.routing_preview.configure(state="disabled")
        self.render_provider_models()

    def render_provider_models(self):
        lines = []
        total = routable = ready = failed = 0
        catalog_online = chat_ready = 0
        for provider in PROVIDERS:
            ms = self.provider_store.models(provider)
            total += len(ms)
            routable += sum(1 for m in ms if m.get("routable"))
            ready += sum(1 for m in ms if m.get("health") == "READY")
            failed += sum(1 for m in ms if m.get("health") in {
                "FAILED", "AUTH ERROR", "RATE LIMITED", "PAYMENT REQUIRED",
                "HTTP 404", "UNAVAILABLE"
            })
            h = self.provider_store.health(provider)
            status = h.get("status", "NOT IMPORTED" if not ms else "CATALOG ONLINE")
            if status in {"CATALOG ONLINE", "CHAT READY"}:
                catalog_online += 1
            if status == "CHAT READY":
                chat_ready += 1
            lines.append(
                f"{provider}  ·  {status}  ·  "
                f"{len(ms)} discovered  ·  {sum(1 for m in ms if m.get('routable'))} chat  ·  "
                f"{sum(1 for m in ms if m.get('health') == 'READY')} ready"
            )
            if h.get("last_error"):
                lines.append(f"    Last error: {str(h.get('last_error'))[:180]}")
            if ms:
                healthy = [m.get("id") for m in ms if m.get("health") == "READY"][:5]
                preview = ", ".join(healthy) if healthy else ", ".join(m.get("id", "") for m in ms[:5])
                lines.append(f"    {preview}{' …' if len(ms) > 5 else ''}")

        if hasattr(self, "models_summary"):
            self.models_summary.configure(
                text=(
                    f"{catalog_online}/{len(PROVIDERS)} provider catalogs reachable  ·  "
                    f"{chat_ready} chat-ready providers  ·  "
                    f"{total} discovered  ·  {routable} routable  ·  {ready} verified healthy  ·  "
                    f"{failed} failed/quarantined  ·  profile: {self.provider_store.profile()}"
                )
            )
        if hasattr(self, "provider_models_box"):
            self.provider_models_box.configure(
                text="\n".join(lines) or "No provider catalogs connected yet."
            )
        if hasattr(self, "routing_preview"):
            self.routing_preview.configure(state="normal")
            self.routing_preview.delete("1.0", "end")
            for task in ("Write Python code", "Explain a complex architecture", "Answer quickly"):
                candidates = choose_candidates(self.provider_store, task, 5)
                self.routing_preview.insert(
                    "end",
                    f"{task}\n" +
                    ("  " + "\n  ".join(f"{p} / {m}" for p, m in candidates)
                     if candidates else "  No eligible candidates — test a chat model first.") +
                    "\n\n"
                )
            self.routing_preview.configure(state="disabled")

    def test_provider_chat(self, provider):
        key = self.provider_store.get_key(provider)
        if provider != "Ollama" and not key:
            if hasattr(self, "provider_status") and provider in self.provider_status:
                self.provider_status[provider].configure(text="No API key", fg=AMBER)
            return

        if hasattr(self, "provider_status") and provider in self.provider_status:
            self.provider_status[provider].configure(text="Testing catalog + chat…", fg=AMBER)

        def worker():
            try:
                result = validate_provider(self.provider_store, provider, key, timeout=20, max_models=3)
                status = result.get("status", "OFFLINE")
                tests = result.get("tests", [])
                if status == "CHAT READY":
                    text = f"✓ CHAT READY · {result.get('ready', 1)} verified · {result.get('latency_ms', '—')} ms"
                    fg = GREEN
                elif status == "CATALOG ONLINE":
                    err = tests[-1].get("error", "") if tests else result.get("error", "")
                    text = f"⚠ CATALOG ONLY · chat test failed: {str(err)[:120]}"
                    fg = AMBER
                else:
                    text = f"✗ {status} · {str(result.get('error', ''))[:120]}"
                    fg = RED
                self.after(0, lambda t=text, c=fg, p=provider: self.provider_status[p].configure(text=t, fg=c))
                self.after(0, self.render_provider_models)
                self.after(0, self.refresh)
            except Exception as exc:
                err = str(exc)[:160]
                self.provider_store.set_health(provider, "OFFLINE", error=err)
                self.after(0, lambda p=provider, e=err: self.provider_status[p].configure(text=f"✗ {e}", fg=RED))
        threading.Thread(target=worker, daemon=True).start()

    def import_provider_models(self, provider):
        key = self.provider_store.get_key(provider) if provider == "Ollama" else self.provider_vars[provider].get().strip()
        if provider != "Ollama":
            self.provider_store.set_key(provider, key)
        if hasattr(self, "provider_status"):
            self.provider_status[provider].configure(text="Importing catalog…", fg=AMBER)

        def worker():
            try:
                models = fetch_models(provider, key)
                self.provider_store.set_models(provider, models)
                self.provider_store.set_health(
                    provider, "CATALOG ONLINE",
                    models=len(models),
                    routable=sum(1 for m in models if m.get("routable"))
                )
                routable = sum(1 for m in models if m.get("routable"))
                text = f"✓ CATALOG ONLINE · {routable}/{len(models)} chat candidates"
                self.after(0, lambda p=provider, t=text: self.provider_status[p].configure(text=t, fg=GREEN))
                self.after(0, self.refresh_catalog)
                self.after(0, self.render_provider_models if hasattr(self, "render_provider_models") else self.refresh)
            except Exception as exc:
                err = str(exc)[:160]
                self.provider_store.set_health(provider, "OFFLINE", error=err)
                self.after(0, lambda p=provider, e=err: self.provider_status[p].configure(text=f"✗ {e}", fg=RED))

        threading.Thread(target=worker, daemon=True).start()

    def import_all_models(self):
        self.save_provider_keys()
        for provider in PROVIDERS:
            if provider == "Ollama" or self.provider_store.get_key(provider):
                self.import_provider_models(provider)

    def refresh_catalog(self):
        if hasattr(self, "catalog_box"):
            self.catalog_box.configure(text=self.catalog_text())

    def toggle_gemini_key(self):
        self.gemini_key_entry.configure(show="" if self.gemini_key_entry.cget("show") else "•")

    def verify_all_models(self):
        """Explicitly probe every routable catalog model.

        This is intentionally opt-in because each successful probe is a real
        provider request and may consume quota. Results are persisted.
        """
        if not messagebox.askyesno(
            "Verify all chat models",
            "AXON will send a small AXON_OK request to every routable chat model "
            "in the imported catalogs. This may consume provider quota or credits. Continue?"
        ):
            return
        if hasattr(self, "models_summary"):
            self.models_summary.configure(text="Verifying every routable chat model…")
        def worker():
            targets=[
                (p,m["id"]) for p in PROVIDERS
                for m in self.provider_store.models(p)
                if m.get("routable")
            ]
            # Parallelism keeps the verification operation fast without
            # opening an unbounded number of provider connections.
            def probe(pair):
                p,mid=pair
                return p,mid,validate_model(self.provider_store,p,mid,timeout=20)
            with ThreadPoolExecutor(max_workers=6,thread_name_prefix="axon-probe") as pool:
                futures=[pool.submit(probe,t) for t in targets]
                for future in as_completed(futures):
                    try:
                        future.result()
                    except Exception:
                        pass
            self.after(0,self.render_provider_models)
            self.after(0,self.refresh)
        from concurrent.futures import ThreadPoolExecutor, as_completed
        threading.Thread(target=worker,daemon=True).start()

    def test_all_connections(self):
        if hasattr(self, "models_summary"):
            self.models_summary.configure(text="Testing provider catalogs and one representative chat model per provider…")

        def worker():
            providers = [
                p for p in PROVIDERS
                if p == "Ollama" or self.provider_store.get_key(p)
            ]
            for provider in providers:
                key = self.provider_store.get_key(provider)
                try:
                    validate_provider(self.provider_store, provider, key, timeout=20, max_models=3)
                except Exception as exc:
                    self.provider_store.set_health(provider, "OFFLINE", error=str(exc))
            self.after(0, self.render_provider_models)
            self.after(0, self.refresh)

        threading.Thread(target=worker, daemon=True).start()

    def page_world(self):
        self.two_col_header("WORLD", "A situational view of AXON's local environment.")
        grid=tk.Frame(self.content,bg=BG); grid.pack(fill="both",expand=True,pady=16)
        for i in range(3): grid.grid_columnconfigure(i,weight=1)
        for i,(title,text) in enumerate([("HOST","Kali Linux"),("NETWORK","Local environment"),("TIME","Live")]):
            f=self.card(grid); f.grid(row=0,column=i,sticky="nsew",padx=5); self.label(f,title,8,MUTED,True,PANEL).pack(anchor="w",padx=18,pady=(18,4)); l=self.label(f,text,16,TEXT,True,PANEL); l.pack(anchor="w",padx=18,pady=(0,18))
        f=self.card(grid); f.grid(row=1,column=0,columnspan=3,sticky="nsew",padx=5,pady=10); grid.grid_rowconfigure(1,weight=1)
        self.label(f,"LIVE ENVIRONMENT",10,TEXT,True,PANEL).pack(anchor="w",padx=18,pady=(16,4)); self.world_text=self.label(f,"",10,MUTED,bg=PANEL,justify="left",anchor="nw"); self.world_text.pack(fill="both",expand=True,padx=18,pady=8)

    def page_knowledge(self):
        self.two_col_header("KNOWLEDGE", "Persistent reusable experience — not pretend memory.")
        p=self.card(self.content); p.pack(fill="both",expand=True,pady=16)
        self.knowledge_text=self.label(p,"",10,TEXT,bg=PANEL,justify="left",anchor="nw"); self.knowledge_text.pack(fill="both",expand=True,padx=22,pady=20); self.render_experience()

    def _choose_workspace_file(self, variable, types=None):
        path = filedialog.askopenfilename(
            parent=self, initialdir=str(AXON_OUTPUT_DIR), filetypes=types or [("All files", "*.*")]
        )
        if path:
            variable.set(path)

    def _workspace_job(self, plan, action, status_widget, preview=False):
        if not self.confirm_action(plan):
            status_widget.configure(text="Cancelled. No action was performed.", fg=AMBER)
            return
        status_widget.configure(text="Working…", fg=AMBER)

        def worker():
            try:
                result = action()
            except Exception as exc:
                result = ActionResult.failure("AXON could not complete that action.", str(exc))

            def complete():
                status_widget.configure(text=result.message, fg=GREEN if result.ok else RED)
                if result.ok and preview and result.data.get("path"):
                    self._preview_workspace_image(result.data["path"])
                self.refresh()
            self.after(0, complete)

        threading.Thread(target=worker, daemon=True).start()

    def _preview_workspace_image(self, path):
        if not self._widget_alive(getattr(self, "image_preview", None)):
            return
        try:
            from PIL import Image, ImageTk
            with Image.open(path) as source:
                image = source.copy()
            image.thumbnail((520, 420))
            photo = ImageTk.PhotoImage(image)
            self.image_preview.configure(image=photo, text="")
            self.image_preview.image = photo
        except Exception:
            self.image_preview.configure(image="", text=f"Created: {path}")

    def page_images(self):
        self.two_col_header("IMAGES", "Generate, edit, resize, and export images without overwriting originals.")
        grid = tk.Frame(self.content, bg=BG); grid.pack(fill="both", expand=True, pady=16)
        grid.grid_columnconfigure(0, weight=1); grid.grid_columnconfigure(1, weight=1)
        creator = self.card(grid); creator.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self.label(creator, "IMAGE CREATOR", 12, TEXT, True, PANEL).pack(anchor="w", padx=18, pady=(18, 4))
        self.label(creator, "Generation uses the OpenAI Images API and may use your API credits.", 9, MUTED, bg=PANEL, wraplength=500, justify="left").pack(anchor="w", padx=18, pady=(0, 12))
        self.image_prompt = tk.Entry(creator, bg=PANEL2, fg=TEXT, insertbackground=TEXT, relief="flat", font=("DejaVu Sans", 10))
        self.image_prompt.pack(fill="x", padx=18, ipady=9)
        self.button(creator, "GENERATE IMAGE", self._generate_image, accent=True, compact=True).pack(anchor="w", padx=18, pady=10)
        tk.Frame(creator, bg=BORDER, height=1).pack(fill="x", padx=18, pady=8)
        self.label(creator, "POSTER", 10, TEXT, True, PANEL).pack(anchor="w", padx=18, pady=(4, 5))
        self.poster_title = tk.Entry(creator, bg=PANEL2, fg=TEXT, insertbackground=TEXT, relief="flat", font=("DejaVu Sans", 10))
        self.poster_title.insert(0, "Poster title")
        self.poster_title.pack(fill="x", padx=18, ipady=8)
        self.poster_subtitle = tk.Entry(creator, bg=PANEL2, fg=TEXT, insertbackground=TEXT, relief="flat", font=("DejaVu Sans", 10))
        self.poster_subtitle.insert(0, "Optional subtitle")
        self.poster_subtitle.pack(fill="x", padx=18, pady=(7, 0), ipady=8)
        self.button(creator, "CREATE POSTER", self._create_poster, compact=True).pack(anchor="w", padx=18, pady=10)

        editor = self.card(grid); editor.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        self.label(editor, "IMAGE EDITOR", 12, TEXT, True, PANEL).pack(anchor="w", padx=18, pady=(18, 4))
        self.label(editor, "Choose an image, then request an edit. AXON saves a new file and preserves the source.", 9, MUTED, bg=PANEL, wraplength=500, justify="left").pack(anchor="w", padx=18, pady=(0, 12))
        self.image_source_var = tk.StringVar()
        source = tk.Frame(editor, bg=PANEL); source.pack(fill="x", padx=18)
        source.grid_columnconfigure(0, weight=1)
        tk.Entry(source, textvariable=self.image_source_var, bg=PANEL2, fg=TEXT, insertbackground=TEXT, relief="flat", font=("DejaVu Sans", 9)).grid(row=0, column=0, sticky="ew", ipady=8)
        self.button(source, "CHOOSE", lambda: self._choose_workspace_file(self.image_source_var, [("Images", "*.png *.jpg *.jpeg *.webp"), ("All files", "*.*")]), compact=True).grid(row=0, column=1, padx=(7, 0))
        self.image_edit_prompt = tk.Entry(editor, bg=PANEL2, fg=TEXT, insertbackground=TEXT, relief="flat", font=("DejaVu Sans", 10))
        self.image_edit_prompt.insert(0, "Example: remove the background and add a blue studio backdrop")
        self.image_edit_prompt.pack(fill="x", padx=18, pady=(10, 0), ipady=8)
        row = tk.Frame(editor, bg=PANEL); row.pack(fill="x", padx=18, pady=10)
        self.button(row, "EDIT IMAGE", self._edit_image, accent=True, compact=True).pack(side="left")
        self.button(row, "OPEN OUTPUT FOLDER", self._open_output_folder, compact=True).pack(side="left", padx=7)
        self.image_status = self.label(grid, "Images are saved in the AXON output folder.", 9, MUTED, bg=BG, justify="left", anchor="nw", wraplength=1030)
        self.image_status.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(12, 4))
        self.image_preview = self.label(grid, "A generated or edited image preview appears here.", 10, MUTED, bg=BG, justify="center")
        self.image_preview.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(8, 0))

    def _generate_image(self):
        prompt = self.image_prompt.get().strip()
        self._workspace_job(
            ActionPlan("Generate image", f"Generate image: {prompt or '(empty prompt)'}", "External service: OpenAI Images API. A request may use API credits."),
            lambda: self.router._image_service().generate(prompt), self.image_status, preview=True
        )

    def _create_poster(self):
        title, subtitle = self.poster_title.get().strip(), self.poster_subtitle.get().strip()
        self._workspace_job(
            ActionPlan("Create poster", f"Create poster titled: {title}", f"Output: {AXON_OUTPUT_DIR}. No existing file will be overwritten."),
            lambda: self.router._image_service().poster(title, subtitle), self.image_status, preview=True
        )

    def _edit_image(self):
        source, prompt = self.image_source_var.get().strip(), self.image_edit_prompt.get().strip()
        valid = self.router.files.policy.validate(source, "read") if source else ActionResult.failure("Choose an image first.")
        if not valid.ok:
            self.image_status.configure(text=valid.message, fg=RED)
            return
        self._workspace_job(
            ActionPlan("Edit image", f"Edit: {source}", f"Requested change: {prompt}\nExternal service: OpenAI Images API. AXON will save a new image."),
            lambda: self.router._image_service().edit(source, prompt), self.image_status, preview=True
        )

    def _open_output_folder(self):
        self._workspace_job(
            ActionPlan("Open output folder", "Open the AXON output folder with your desktop file manager.", str(AXON_OUTPUT_DIR)),
            lambda: self.router.files.open_folder(AXON_OUTPUT_DIR), self.image_status
        )

    def page_files(self):
        self.two_col_header("FILES & PDFS", "Read, analyze, export, and safely edit files within approved folders.")
        grid = tk.Frame(self.content, bg=BG); grid.pack(fill="both", expand=True, pady=16)
        grid.grid_columnconfigure(0, weight=1); grid.grid_columnconfigure(1, weight=1)
        files = self.card(grid); files.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self.label(files, "FILE WORKSPACE", 12, TEXT, True, PANEL).pack(anchor="w", padx=18, pady=(18, 5))
        self.label(files, "Choose a file from Documents, Downloads, Desktop, or the AXON output folder. AXON displays its plan before reading or opening it.", 9, MUTED, bg=PANEL, wraplength=500, justify="left").pack(anchor="w", padx=18, pady=(0, 12))
        self.file_source_var = tk.StringVar()
        source = tk.Frame(files, bg=PANEL); source.pack(fill="x", padx=18)
        source.grid_columnconfigure(0, weight=1)
        tk.Entry(source, textvariable=self.file_source_var, bg=PANEL2, fg=TEXT, insertbackground=TEXT, relief="flat", font=("DejaVu Sans", 9)).grid(row=0, column=0, sticky="ew", ipady=8)
        self.button(source, "CHOOSE", lambda: self._choose_workspace_file(self.file_source_var), compact=True).grid(row=0, column=1, padx=(7, 0))
        actions = tk.Frame(files, bg=PANEL); actions.pack(fill="x", padx=18, pady=12)
        self.button(actions, "ANALYZE", self._analyze_file, accent=True, compact=True).pack(side="left")
        self.button(actions, "READ TEXT", self._read_file, compact=True).pack(side="left", padx=7)
        self.button(actions, "OPEN", self._open_file, compact=True).pack(side="left")
        self.button(actions, "FULL SCREEN", self._open_file_fullscreen, compact=True).pack(side="left", padx=7)
        self.file_status = self.label(files, "Choose a file to begin.", 9, MUTED, bg=PANEL, justify="left", anchor="nw", wraplength=500)
        self.file_status.pack(fill="both", expand=True, padx=18, pady=(6, 18))

        pdf = self.card(grid); pdf.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        self.label(pdf, "PDF TOOLS", 12, TEXT, True, PANEL).pack(anchor="w", padx=18, pady=(18, 5))
        self.label(pdf, "PDF edits always write a new output file. Merge, split, rotation, page preview, and text annotation are available when PDF dependencies are installed.", 9, MUTED, bg=PANEL, wraplength=500, justify="left").pack(anchor="w", padx=18, pady=(0, 12))
        self.pdf_output_var = tk.StringVar(value=str(AXON_OUTPUT_DIR / "edited.pdf"))
        tk.Entry(pdf, textvariable=self.pdf_output_var, bg=PANEL2, fg=TEXT, insertbackground=TEXT, relief="flat", font=("DejaVu Sans", 9)).pack(fill="x", padx=18, ipady=8)
        self.pdf_note = tk.Entry(pdf, bg=PANEL2, fg=TEXT, insertbackground=TEXT, relief="flat", font=("DejaVu Sans", 9))
        self.pdf_note.insert(0, "Annotation text for page 1")
        self.pdf_note.pack(fill="x", padx=18, pady=(8, 0), ipady=8)
        tools = tk.Frame(pdf, bg=PANEL); tools.pack(fill="x", padx=18, pady=12)
        self.button(tools, "EXTRACT TEXT", self._extract_pdf, accent=True, compact=True).pack(side="left")
        self.button(tools, "ROTATE 90°", self._rotate_pdf, compact=True).pack(side="left", padx=7)
        self.button(tools, "ANNOTATE", self._annotate_pdf, compact=True).pack(side="left")
        self.pdf_status = self.label(pdf, "Select a PDF in File Workspace, then choose an operation.", 9, MUTED, bg=PANEL, justify="left", anchor="nw", wraplength=500)
        self.pdf_status.pack(fill="both", expand=True, padx=18, pady=(6, 18))

    def _selected_file(self):
        return self.file_source_var.get().strip() if hasattr(self, "file_source_var") else ""

    def _analyze_file(self):
        path = self._selected_file()
        self._workspace_job(ActionPlan("Analyze file", f"Read and analyze: {path}", "Read-only access; AXON will not change the file."), lambda: self.router.files.analyze(path), self.file_status)

    def _read_file(self):
        path = self._selected_file()
        self._workspace_job(ActionPlan("Read file", f"Read text file: {path}", "Read-only access."), lambda: self.router.files.read_text(path), self.file_status)

    def _open_file_fullscreen(self):
        """Open the selected workspace file in AXON's own full-screen viewer.

        This preserves the existing page layout and keeps the file inside the
        approved-folder policy. Text/CSV/DOCX/PDF files are rendered as a
        readable document view; images are fitted to the screen. Unsupported
        binary formats fall back to the normal desktop opener.
        """
        path = self._selected_file()
        valid = self.router.files.policy.validate(path, "read") if path else ActionResult.failure("Choose a file first.")
        if not valid.ok:
            self.file_status.configure(text=valid.message, fg=RED)
            return
        source = valid.data.get("path")
        if not source or not Path(source).is_file():
            self.file_status.configure(text="That file is not available.", fg=RED)
            return
        try:
            size = Path(source).stat().st_size
        except OSError as exc:
            self.file_status.configure(text=f"Could not inspect file: {exc}", fg=RED)
            return
        if size > 25 * 1024 * 1024:
            self.file_status.configure(text="AXON only previews files up to 25 MB.", fg=RED)
            return

        viewer = tk.Toplevel(self)
        viewer.title(f"AXON — {Path(source).name}")
        viewer.configure(bg=BG)
        viewer.attributes("-fullscreen", True)
        viewer.bind("<Escape>", lambda _event: viewer.destroy())
        viewer.bind("<F11>", lambda _event: viewer.attributes("-fullscreen", not bool(viewer.attributes("-fullscreen"))))
        viewer.protocol("WM_DELETE_WINDOW", viewer.destroy)

        top = tk.Frame(viewer, bg=SIDEBAR, height=54)
        top.pack(fill="x")
        top.pack_propagate(False)
        tk.Label(top, text=f"  {Path(source).name}", bg=SIDEBAR, fg=TEXT, font=("DejaVu Sans", 12, "bold"), anchor="w").pack(side="left", fill="both", expand=True)
        tk.Button(top, text="EXIT FULL SCREEN", command=viewer.destroy, bg=PANEL2, fg=TEXT, relief="flat", activebackground=PANEL3, activeforeground=TEXT, font=("DejaVu Sans", 9, "bold"), padx=14, pady=7).pack(side="right", padx=12, pady=8)

        body = tk.Frame(viewer, bg=BG)
        body.pack(fill="both", expand=True, padx=14, pady=14)
        suffix = Path(source).suffix.lower()
        kind = __import__("mimetypes").guess_type(source)[0] or ""

        if kind.startswith("image/"):
            try:
                from PIL import Image, ImageTk
                image = Image.open(source).convert("RGB")
                max_w = max(640, viewer.winfo_screenwidth() - 80)
                max_h = max(480, viewer.winfo_screenheight() - 120)
                image.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
                photo = ImageTk.PhotoImage(image)
                label = tk.Label(body, image=photo, bg=BG)
                label.image = photo
                label.pack(expand=True)
                return
            except Exception as exc:
                tk.Label(body, text=f"Image preview failed: {exc}", bg=BG, fg=RED, font=("DejaVu Sans", 11)).pack(expand=True)
                return

        text = None
        try:
            if suffix in {".txt", ".md", ".py", ".json", ".yaml", ".yml", ".ini", ".cfg", ".conf", ".sh", ".bash", ".js", ".ts", ".tsx", ".jsx", ".html", ".css", ".xml", ".sql", ".log", ".csv"}:
                text = Path(source).read_text(encoding="utf-8", errors="replace")
            elif suffix == ".docx":
                import zipfile
                with zipfile.ZipFile(source) as archive:
                    xml = archive.read("word/document.xml").decode("utf-8", errors="replace")
                text = re.sub(r"<[^>]+>", " ", xml)
                text = re.sub(r"\s+", " ", text).strip()
            elif suffix == ".pdf":
                extracted = PdfService(self.router.files.policy).extract_text(source, limit=200000)
                if extracted.ok:
                    text = extracted.data.get("text") or extracted.message
                else:
                    text = extracted.message
        except Exception as exc:
            text = f"AXON could not preview this file.\n\n{exc}"

        if text is not None:
            frame = tk.Frame(body, bg=PANEL)
            frame.pack(fill="both", expand=True)
            scrollbar = tk.Scrollbar(frame)
            scrollbar.pack(side="right", fill="y")
            widget = tk.Text(frame, bg=PANEL3, fg=TEXT, insertbackground=TEXT, relief="flat", wrap="word", font=("DejaVu Sans Mono", 11), yscrollcommand=scrollbar.set)
            widget.pack(side="left", fill="both", expand=True, padx=1, pady=1)
            scrollbar.config(command=widget.yview)
            widget.insert("1.0", text)
            widget.configure(state="disabled")
            return

        # Binary/unsupported formats: keep the existing desktop behavior, but
        # make the action explicit instead of silently failing inside the viewer.
        viewer.destroy()
        self._open_file()

    def _pdf_service(self):
        return PdfService(self.router.files.policy)

    def _extract_pdf(self):
        path = self._selected_file()
        self._workspace_job(ActionPlan("Extract PDF text", f"Read PDF: {path}", "Read-only PDF text extraction."), lambda: self._pdf_service().extract_text(path), self.pdf_status)

    def _rotate_pdf(self):
        path, output = self._selected_file(), self.pdf_output_var.get().strip()
        self._workspace_job(ActionPlan("Rotate PDF", f"Rotate {path} by 90 degrees.", f"New output: {output}"), lambda: self._pdf_service().rotate(path, output), self.pdf_status)

    def _annotate_pdf(self):
        path, output, note = self._selected_file(), self.pdf_output_var.get().strip(), self.pdf_note.get().strip()
        self._workspace_job(ActionPlan("Annotate PDF", f"Add text to page 1 of {path}.", f"Text: {note}\nNew output: {output}"), lambda: self._pdf_service().overlay_text(path, output, note), self.pdf_status)

    def page_memory(self):
        self.two_col_header("MEMORY", "Local, opt-in working memory for facts, places, aliases, and preferences.")
        panel = self.card(self.content); panel.pack(fill="both", expand=True, pady=16)
        self.label(panel, "PERSONAL WORKING MEMORY", 12, TEXT, True, PANEL).pack(anchor="w", padx=20, pady=(20, 4))
        self.label(panel, "Only information you explicitly ask AXON to remember is stored. Secrets, API keys, passwords, and tokens are rejected.", 9, MUTED, bg=PANEL, wraplength=980, justify="left").pack(anchor="w", padx=20, pady=(0, 14))
        self.memory_enabled_var = tk.BooleanVar(value=self.memory.personal_enabled())
        tk.Checkbutton(panel, text="Enable persistent personal memory", variable=self.memory_enabled_var, command=self._toggle_personal_memory, bg=PANEL, fg=TEXT, selectcolor=PANEL2, activebackground=PANEL, activeforeground=TEXT).pack(anchor="w", padx=20)
        form = tk.Frame(panel, bg=PANEL); form.pack(fill="x", padx=20, pady=16); form.grid_columnconfigure(1, weight=1)
        self.label(form, "Fact label", 9, MUTED, bg=PANEL).grid(row=0, column=0, sticky="w", padx=(0, 8), pady=4)
        self.memory_key = tk.Entry(form, bg=PANEL2, fg=TEXT, insertbackground=TEXT, relief="flat"); self.memory_key.grid(row=0, column=1, sticky="ew", ipady=7, pady=4)
        self.label(form, "Value", 9, MUTED, bg=PANEL).grid(row=1, column=0, sticky="w", padx=(0, 8), pady=4)
        self.memory_value = tk.Entry(form, bg=PANEL2, fg=TEXT, insertbackground=TEXT, relief="flat"); self.memory_value.grid(row=1, column=1, sticky="ew", ipady=7, pady=4)
        actions = tk.Frame(panel, bg=PANEL); actions.pack(fill="x", padx=20)
        self.button(actions, "SAVE FACT", self._save_memory_fact, accent=True, compact=True).pack(side="left")
        self.button(actions, "FORGET LABEL", self._forget_memory_fact, compact=True).pack(side="left", padx=7)
        self.button(actions, "EXPORT", self._export_memory, compact=True).pack(side="left")
        self.button(actions, "CLEAR ALL", self._clear_memory, compact=True).pack(side="left", padx=7)
        self.memory_status = self.label(panel, self.memory.personal_summary(), 10, TEXT, bg=PANEL, justify="left", anchor="nw", wraplength=980)
        self.memory_status.pack(fill="both", expand=True, padx=20, pady=20)

    def _toggle_personal_memory(self):
        self.memory.enable_personal_memory(self.memory_enabled_var.get())
        self.memory_status.configure(text=self.memory.personal_summary(), fg=GREEN)

    def _save_memory_fact(self):
        ok, message = self.memory.remember_fact(self.memory_key.get(), self.memory_value.get())
        self.memory_enabled_var.set(self.memory.personal_enabled())
        self.memory_status.configure(text=message + "\n\n" + self.memory.personal_summary(), fg=GREEN if ok else RED)

    def _forget_memory_fact(self):
        ok, message = self.memory.forget(self.memory_key.get())
        self.memory_status.configure(text=message + "\n\n" + self.memory.personal_summary(), fg=GREEN if ok else AMBER)

    def _export_memory(self):
        path = filedialog.asksaveasfilename(parent=self, initialdir=str(AXON_OUTPUT_DIR), initialfile="axon-memory.json", defaultextension=".json", filetypes=[("JSON", "*.json")])
        if not path:
            return
        plan = ActionPlan("Export memory", "Export AXON personal working memory.", f"Write JSON to: {path}")
        if not self.confirm_action(plan):
            return
        result = self.router.files.write_text(path, json.dumps(self.memory.personal, indent=2), backup=False)
        self.memory_status.configure(text=result.message, fg=GREEN if result.ok else RED)

    def _clear_memory(self):
        plan = ActionPlan("Clear personal memory", "Erase saved facts, places, aliases, and preferences.", "This cannot be undone. Goals and conversation experience are not affected.")
        if not self.confirm_action(plan):
            return
        self.memory.clear_personal_memory()
        self.memory_enabled_var.set(False)
        self.memory_status.configure(text="Cleared personal working memory.", fg=GREEN)

    def page_observe(self):
        self.two_col_header("OBSERVE", "System telemetry and activity.")
        p=self.card(self.content); p.pack(fill="both",expand=True,pady=16)
        self.observe_text=self.label(p,"",10,TEXT,bg=PANEL,justify="left",anchor="nw"); self.observe_text.pack(fill="both",expand=True,padx=22,pady=20)

    def page_security(self):
        self.two_col_header("SENTINEL", "Defensive URL intelligence and explicitly authorized network discovery.")
        grid=tk.Frame(self.content,bg=BG); grid.pack(fill="both",expand=True,pady=12)
        grid.grid_columnconfigure(0,weight=1); grid.grid_columnconfigure(1,weight=1)
        grid.grid_rowconfigure(1,weight=1)
        for i,(title,value) in enumerate([("SECURITY STATUS","READY"),("FINDINGS","0"),("MODE","AUTHORIZED ONLY")]):
            f=self.card(grid); f.grid(row=0,column=i,sticky="ew",padx=4); self.label(f,title,7,MUTED,True,PANEL).pack(anchor="w",padx=12,pady=(10,2)); self.label(f,value,11,GREEN if i==0 else TEXT,True,PANEL).pack(anchor="w",padx=12,pady=(0,10))

        # URL analyzer and Nmap are deliberately parallel: no unused top row.
        left=self.card(grid); left.grid(row=1,column=0,sticky="nsew",padx=(4,6),pady=8)
        self.label(left,"URL THREAT ANALYZER",12,TEXT,True,PANEL).pack(anchor="w",padx=16,pady=(14,2))
        self.label(left,"Multi-source threat intelligence + local heuristics. A clean result never means guaranteed safe.",8,MUTED,bg=PANEL,wraplength=540,justify="left").pack(anchor="w",padx=16)
        e=tk.Entry(left,bg=PANEL2,fg=TEXT,insertbackground=TEXT,relief="flat",font=("DejaVu Sans",10)); e.pack(fill="x",padx=16,pady=12,ipady=9)
        self.button(left,"DEEP SCAN URL",lambda:self.analyze_domain(e.get().strip()),accent=True,compact=True).pack(anchor="w",padx=16)
        self.security_out=self.label(left,"Enter a domain or URL to begin.",9,MUTED,bg=PANEL,justify="left",anchor="nw",wraplength=560); self.security_out.pack(fill="both",expand=True,padx=16,pady=14)

        right=self.card(grid); right.grid(row=1,column=1,sticky="nsew",padx=(6,4),pady=8)
        self.label(right,"AUTHORIZED NMAP DISCOVERY",12,TEXT,True,PANEL).pack(anchor="w",padx=16,pady=(14,2))
        self.label(right,"Only explicit, user-authorized targets are accepted. AXON controls the command arguments and does not expose arbitrary flags.",8,MUTED,bg=PANEL,wraplength=540,justify="left").pack(anchor="w",padx=16)
        self.label(right,"Target",8,MUTED,bg=PANEL).pack(anchor="w",padx=16,pady=(12,3)); target=tk.Entry(right,bg=PANEL2,fg=TEXT,insertbackground=TEXT,relief="flat"); target.pack(fill="x",padx=16,ipady=8)
        self.label(right,"Ports (optional: 22,80,443 or 1-1024)",8,MUTED,bg=PANEL).pack(anchor="w",padx=16,pady=(9,3)); ports=tk.Entry(right,bg=PANEL2,fg=TEXT,insertbackground=TEXT,relief="flat"); ports.pack(fill="x",padx=16,ipady=8)
        self.auth=tk.BooleanVar(value=False); tk.Checkbutton(right,text="I have authorization to test this target",variable=self.auth,bg=PANEL,fg=MUTED,selectcolor=PANEL2,activebackground=PANEL,activeforeground=TEXT).pack(anchor="w",padx=16,pady=9)
        self.button(right,"RUN DISCOVERY",lambda:self.authorized_scan(target.get(),ports.get()),accent=True,compact=True).pack(anchor="w",padx=16)
        self.nmap_out=self.label(right,"No scan run.",8,MUTED,bg=PANEL,justify="left",anchor="nw",wraplength=540); self.nmap_out.pack(fill="both",expand=True,padx=16,pady=12)

    def page_voice(self):
        """Voice-only command console, styled after the reference control room."""
        self.two_col_header("AXON VOICE", "Speak naturally. AXON transcribes the completed turn, routes it, then speaks the verified result.")

        shell=tk.Frame(self.content,bg=BG)
        shell.pack(fill="both",expand=True,pady=(10,0))
        shell.grid_columnconfigure(0,weight=1,minsize=650)
        shell.grid_columnconfigure(1,weight=0,minsize=300)
        shell.grid_rowconfigure(0,weight=1)

        # Main command-center surface — intentionally uses the same gold/purple
        # language as Home instead of the blue diagnostic surface from V15.7.1.
        main=self.card(shell,bg="#0B0D10")
        main.grid(row=0,column=0,sticky="nsew",padx=(0,8))
        main.grid_rowconfigure(2,weight=1); main.grid_columnconfigure(0,weight=1)

        head=tk.Frame(main,bg="#0B0D10")
        head.grid(row=0,column=0,sticky="ew",padx=18,pady=(14,7)); head.grid_columnconfigure(1,weight=1)
        self.label(head,"〰  AXON VOICE",16,TEXT,True,"#0B0D10").grid(row=0,column=0,sticky="w")
        self.voice_state_label=self.label(head,"● LIVE SESSION" if self.gemini_voice.running else "○ SESSION OFFLINE",9,GREEN if self.gemini_voice.running else MUTED,True,"#0B0D10")
        self.voice_state_label.grid(row=0,column=1,sticky="e")
        self.label(head,"Speak naturally. AXON hears your microphone, transcribes the turn, then routes governed commands.",8,MUTED,bg="#0B0D10").grid(row=1,column=0,columnspan=2,sticky="w",pady=(3,0))

        controls=tk.Frame(main,bg="#0B0D10"); controls.grid(row=1,column=0,sticky="ew",padx=18,pady=(10,12))
        self.button(controls,"●  STOP VOICE" if self.gemini_voice.running else "◉  START VOICE",self.toggle_voice,accent=self.gemini_voice.running,compact=True).pack(side="left",padx=(0,6))
        self.button(controls,"MIC TEST",self.voice_mic_test,compact=True,outline=True).pack(side="left",padx=3)
        self.button(controls,"TEST RESPONSE",self.test_live_response,compact=True,outline=True).pack(side="left",padx=3)
        self.button(controls,"VOICE SETTINGS",lambda:self.show_page("Settings"),compact=True,outline=True).pack(side="left",padx=3)
        self.voice_connection_label=self.label(controls,"  ● LIVE SESSION" if self.gemini_voice.running else "  ○ SESSION OFFLINE",8,GREEN if self.gemini_voice.running else MUTED,True,PANEL3)
        self.voice_connection_label.pack(side="right")

        # Center visual + transcript. The meter is functional: it reflects actual
        # PCM energy received from the selected microphone backend.
        stage=self.card(main,bg="#0A0C10")
        stage.grid(row=2,column=0,sticky="nsew",padx=18,pady=(0,12))
        stage.grid_rowconfigure(1,weight=1); stage.grid_columnconfigure(0,weight=1)
        top=tk.Frame(stage,bg="#0A0C10"); top.grid(row=0,column=0,sticky="ew",padx=16,pady=(14,7)); top.grid_columnconfigure(1,weight=1)
        self.label(top,"LIVE TRANSCRIPT",10,PURPLE2,True,"#0A0C10").grid(row=0,column=0,sticky="w")
        self.voice_signal_label=self.label(top,"MIC SIGNAL  0%",8,MUTED,True,"#0D0A10").grid(row=0,column=1,sticky="e")
        self.voice_transcript=tk.Text(stage,bg="#0A0C10",fg=TEXT,insertbackground=TEXT,relief="flat",bd=0,font=("DejaVu Sans",10),wrap="word",state="disabled",height=10,highlightthickness=0)
        self.voice_transcript.grid(row=1,column=0,sticky="nsew",padx=16,pady=(0,4))
        self.voice_transcript.tag_configure("you",foreground=PURPLE2,font=("DejaVu Sans",10,"bold"))
        self.voice_transcript.tag_configure("axon",foreground=GOLD,font=("DejaVu Sans",10,"bold"))
        self.voice_transcript.tag_configure("system",foreground=MUTED,font=("DejaVu Sans",9))
        # This waveform intentionally has no timer/sine animation: every bar is
        # drawn from recent microphone RMS/peak measurements.
        self._voice_wave_samples=[]
        self.voice_wave=tk.Canvas(stage,height=138,bg="#0A0C10",highlightthickness=0,bd=0)
        self.voice_wave.grid(row=2,column=0,sticky="ew",padx=16,pady=(0,2))
        self.voice_wave.bind("<Configure>",lambda _event:self._render_voice_wave())
        footer=tk.Frame(stage,bg="#0A0C10"); footer.grid(row=3,column=0,sticky="ew",padx=16,pady=(0,12)); footer.grid_columnconfigure(1,weight=1)
        self.label(footer,"●  Listening…" if self.gemini_voice.running else "○  Standby",8,GREEN if self.gemini_voice.running else MUTED,True,"#0A0C10").grid(row=0,column=0,sticky="w")
        self.label(footer,"Waveform follows microphone input",8,MUTED,bg="#0A0C10").grid(row=0,column=1,sticky="e")

        # Right rail: connection, microphone, and governed quick actions.
        rail=tk.Frame(shell,bg=BG); rail.grid(row=0,column=1,sticky="nsew"); rail.grid_columnconfigure(0,weight=1)

        engine=self.card(rail); engine.grid(row=0,column=0,sticky="ew",pady=(0,7))
        self.label(engine,"VOICE ENGINE",10,PURPLE2,True,PANEL).pack(anchor="w",padx=14,pady=(12,4))
        self.label(engine,f"Gemini Live · {GEMINI_LIVE_MODEL}",8,TEXT,bg=PANEL,wraplength=270,justify="left").pack(anchor="w",padx=14)
        self.label(engine,f"Voice · {GEMINI_VOICE or 'Charon'}",8,MUTED,bg=PANEL).pack(anchor="w",padx=14,pady=(3,7))
        self.voice_status=self.label(engine,"LISTENING" if self.gemini_voice.running else "STANDBY",9,GREEN if self.gemini_voice.running else MUTED,True,PANEL)
        self.voice_status.pack(anchor="w",padx=14,pady=(0,10))
        self.voice_engine_wave=tk.Canvas(engine,height=24,bg=PANEL,highlightthickness=0,bd=0)
        self.voice_engine_wave.pack(fill="x",padx=14,pady=(0,12))

        mic=self.card(rail); mic.grid(row=1,column=0,sticky="ew",pady=7)
        self.label(mic,"MICROPHONE",10,PURPLE2,True,PANEL).pack(anchor="w",padx=14,pady=(12,5))
        self.voice_backend_label=self.label(mic,"Backend: checking…",8,MUTED,bg=PANEL); self.voice_backend_label.pack(anchor="w",padx=14)
        self.voice_source_label=self.label(mic,"Source: system default",8,MUTED,bg=PANEL,wraplength=270,justify="left"); self.voice_source_label.pack(anchor="w",padx=14,pady=(3,5))
        self.voice_meter=tk.Canvas(mic,height=18,bg=PANEL,highlightthickness=0); self.voice_meter.pack(fill="x",padx=14,pady=(0,4))
        self.voice_meter.create_rectangle(0,3,260,15,outline=GOLD_SOFT)
        self.voice_level_bar=self.voice_meter.create_rectangle(1,4,1,14,fill=PURPLE,outline="")
        self.voice_mic_hint=self.label(mic,"Start Voice, then speak. The meter should move when AXON receives microphone audio.",8,MUTED,bg=PANEL,wraplength=270,justify="left")
        self.voice_mic_hint.pack(anchor="w",padx=14,pady=(3,12))

        diag=self.card(rail); diag.grid(row=2,column=0,sticky="ew",pady=7)
        self.label(diag,"DIAGNOSTICS",10,PURPLE2,True,PANEL).pack(anchor="w",padx=14,pady=(12,6))
        self.voice_diag=self.label(diag,self.voice_diagnostic_text(),8,MUTED,bg=PANEL,justify="left",anchor="nw",wraplength=270)
        self.voice_diag.pack(fill="x",padx=14,pady=(0,12))

        quick=self.card(rail); quick.grid(row=3,column=0,sticky="ew",pady=7)
        self.label(quick,"QUICK COMMANDS",10,PURPLE2,True,PANEL).pack(anchor="w",padx=14,pady=(12,6))
        for label,cmd in [("Open Terminal","open kitty"),("Open Browser","open browser"),("Open VS Code","open vscode"),("Check System","check system")]:
            self.button(quick,label,lambda c=cmd:self._gemini_command(c),compact=True,outline=True).pack(fill="x",padx=14,pady=3)
        self.button(quick,"Clear Transcript",self.clear_voice_transcript,compact=True).pack(fill="x",padx=14,pady=(3,12))

        self._voice_append_transcript("SYSTEM", "Voice console ready. Start Voice and speak normally.", "system")
        self._render_voice_wave()
        self._voice_after(120,self._refresh_voice_audio_ui)

    def voice_diagnostic_text(self):
        v=self.gemini_voice
        d=v.audio_diagnostics() if hasattr(v,"audio_diagnostics") else {}
        return (
            f"Microphone: {'READY' if v.microphone_ready else 'MISSING'}\n"
            f"Backend: {d.get('backend','unknown')}\n"
            f"Speaker: {d.get('speaker','unknown')}\n"
            f"API key: {'CONFIGURED' if v.api_key else 'MISSING'}\n"
            f"Audio chunks: {getattr(v,'audio_chunks_sent',0)}\n"
            f"Reconnects: {d.get('reconnect_attempts',0)}\n"
            f"Echo guard: {d.get('capture_suppressed_for_tts',0)} frames held · {d.get('duplicate_turns_ignored',0)} duplicate turns ignored\n"
            f"Acoustic echo cancellation: {'ON' if d.get('aec_enabled') else 'fallback gate'}\n"
            f"Mic RMS: {d.get('rms',0.0)*100:.1f}%  Peak: {d.get('peak',0.0)*100:.1f}%\n"
            f"Last heard: {getattr(v,'last_input_transcript','') or '—'}\n"
            f"Language: {getattr(v,'last_input_language','') or 'detecting'}\n"
            f"Last response: {getattr(v,'last_output_transcript','') or '—'}\n"
            f"Live error: {d.get('last_error','') or '—'}"
        )

    def voice_audio_level(self, rms, peak):
        # Worker-thread callback; all Tk work is marshalled back to the main loop.
        try:
            if self.winfo_exists():
                self.after(0, lambda r=rms,p=peak: self._voice_audio_level_ui(r,p))
        except (RuntimeError, tk.TclError):
            pass

    def _voice_audio_level_ui(self, rms, peak):
        if not self._widget_alive(getattr(self,"voice_meter",None)):
            return
        width=max(1, self.voice_meter.winfo_width()-2)
        # Square-root scaling makes quiet speech visible without making the meter jump.
        import math as _math
        frac=min(1.0, _math.sqrt(max(0.0,rms))*2.2)
        self.voice_meter.coords(self.voice_level_bar,1,4,max(1,1+width*frac),14)
        pct=int(min(100,frac*100))
        # Keep a short real signal history. RMS gives sustained speech energy;
        # peak keeps consonants and short transients visible in the waveform.
        energy=min(1.0, max(float(rms), float(peak)*0.58))
        samples=getattr(self,"_voice_wave_samples",None)
        if samples is not None:
            samples.append(energy)
            if len(samples)>180:
                del samples[:-180]
            self._render_voice_wave()
        if self._widget_alive(getattr(self,"voice_signal_label",None)):
            self.voice_signal_label.configure(text=f"MIC SIGNAL  {pct}%",fg=GREEN if pct>=8 else MUTED)
        if self._widget_alive(getattr(self,"voice_backend_label",None)):
            d=self.gemini_voice.audio_diagnostics()
            self.voice_backend_label.configure(text=f"Backend: {d.get('backend','unknown')}")
            self.voice_source_label.configure(text=f"Source: {d.get('source','system default')}")
        if self._widget_alive(getattr(self,"voice_diag",None)):
            try:self.voice_diag.configure(text=self.voice_diagnostic_text())
            except (tk.TclError,RuntimeError):pass

    def _refresh_voice_audio_ui(self):
        if not self._widget_alive(getattr(self,"voice_meter",None)):
            return
        try:
            d=self.gemini_voice.audio_diagnostics()
            if self._widget_alive(getattr(self,"voice_backend_label",None)):
                self.voice_backend_label.configure(text=f"Backend: {d.get('backend','unknown')}")
            if self._widget_alive(getattr(self,"voice_source_label",None)):
                self.voice_source_label.configure(text=f"Source: {d.get('source','system default')}")
            if self._widget_alive(getattr(self,"voice_diag",None)):
                self.voice_diag.configure(text=self.voice_diagnostic_text())
        except Exception:
            pass
        self._voice_after(700,self._refresh_voice_audio_ui)

    def voice_mic_test(self):
        if not self.gemini_voice.running:
            if not self.start_selected_voice():
                return
        self._voice_append_transcript("SYSTEM", "Microphone test active — speak for 3 seconds. Watch MIC SIGNAL.", "system")
        def finish():
            try:
                d=self.gemini_voice.audio_diagnostics()
                rms=d.get("rms",0.0); peak=d.get("peak",0.0)
                if rms < 0.002 and peak < 0.01:
                    msg="MIC TEST: No meaningful microphone signal detected. Check the selected system input device and microphone permissions."
                    tag="system"
                else:
                    msg=f"MIC TEST: Signal detected (RMS {rms*100:.1f}%, peak {peak*100:.1f}%). Microphone input is reaching AXON."
                    tag="system"
                self._voice_append_transcript("SYSTEM",msg,tag)
            except Exception as exc:
                self._voice_append_transcript("SYSTEM",f"MIC TEST failed: {exc}","system")
        self._voice_after(3000,finish)

    def _voice_append_transcript(self, speaker, text, tag):
        if not self._voice_widget_alive("voice_transcript"):
            return
        try:
            self.voice_transcript.configure(state="normal")
            self.voice_transcript.insert("end",f"{speaker}  ",tag)
            self.voice_transcript.insert("end",f"{text}\n\n")
            self.voice_transcript.see("end")
            self.voice_transcript.configure(state="disabled")
        except Exception:
            pass

    def clear_voice_transcript(self):
        if self._voice_widget_alive("voice_transcript"):
            try:
                self.voice_transcript.configure(state="normal"); self.voice_transcript.delete("1.0","end"); self.voice_transcript.configure(state="disabled")
            except (tk.TclError, RuntimeError):
                pass

    def test_live_response(self):
        if not self.gemini_voice.running:
            if not self.start_selected_voice(): return
            self.after(900,lambda:self.gemini_voice.send_text("Say exactly: AXON voice response test successful."))
        else:
            self.gemini_voice.send_text("Say exactly: AXON voice response test successful.")

    def _render_voice_wave(self):
        """Render microphone history only; no synthetic decorative animation."""
        canvas=getattr(self,"voice_wave",None)
        if not self._widget_alive(canvas):
            return
        try:
            width=max(1,canvas.winfo_width()); height=max(1,canvas.winfo_height())
            values=list(getattr(self,"_voice_wave_samples",[]))
            bars=max(24,min(120,width//6))
            values=([0.0]*max(0,bars-len(values))+values)[-bars:]
            canvas.delete("all")
            mid=height/2
            canvas.create_line(0,mid,width,mid,fill="#252035")
            step=width/max(1,bars-1)
            for i,value in enumerate(values):
                amplitude=2+(max(0.0,min(1.0,value))**0.55)*(height*.42)
                color=PURPLE2 if value>=0.08 else "#49376B"
                x=i*step
                canvas.create_line(x,mid-amplitude,x,mid+amplitude,fill=color,width=1)
            mini=getattr(self,"voice_engine_wave",None)
            if self._widget_alive(mini):
                mw=max(1,mini.winfo_width()); mh=max(1,mini.winfo_height()); mini.delete("all")
                step=mw/max(1,bars-1); mid2=mh/2
                for i,value in enumerate(values):
                    amp=1+(max(0.0,min(1.0,value))**0.55)*(mh*.40)
                    mini.create_line(i*step,mid2-amp,i*step,mid2+amp,fill=GREEN if value>=0.08 else "#1E6D4C")
        except (tk.TclError, RuntimeError):
            pass

    def page_settings(self):
        self.two_col_header("SETTINGS", "Providers, models, routing, voice and real account integrations — all governed from one workspace.")
        wrap=tk.Frame(self.content,bg=BG); wrap.pack(fill="both",expand=True,pady=12)

        # Provider management: compact table, horizontally dense, vertically bounded.
        providers=self.card(wrap); providers.pack(fill="x",pady=(0,10))
        self.label(providers,"AI PROVIDERS",15,TEXT,True,PANEL).pack(anchor="w",padx=18,pady=(16,2))
        self.label(providers,"Connect providers once, import their live catalogs, and test the exact account available to AXON.",8,MUTED,bg=PANEL).pack(anchor="w",padx=18,pady=(0,10))
        table=tk.Frame(providers,bg=PANEL); table.pack(fill="x",padx=12,pady=(0,8)); table.grid_columnconfigure(1,weight=1)
        for col,text,w in [(0,"PROVIDER",120),(1,"API KEY / LOCAL",0),(2,"STATUS",220),(3,"ACTIONS",155)]:
            self.label(table,text,8,MUTED,True,PANEL).grid(row=0,column=col,sticky="w",padx=6,pady=(2,5))
        self.provider_vars={}; self.provider_entries={}; self.provider_status={}
        for i,(provider,info) in enumerate(PROVIDERS.items(),start=1):
            bg="#1A140F" if i%2==0 else PANEL
            tk.Frame(table,bg=GOLD_SOFT,height=1).grid(row=i,column=0,columnspan=4,sticky="ew")
            self.label(table,provider,9,TEXT,True,bg=bg).grid(row=i,column=0,sticky="w",padx=6,pady=5)
            var=tk.StringVar(value=self.provider_store.get_key(provider)); self.provider_vars[provider]=var
            ent=tk.Entry(table,textvariable=var,show="•" if provider!="Ollama" else "",bg=PANEL2,fg=TEXT,insertbackground=TEXT,relief="flat",font=("DejaVu Sans",8))
            ent.grid(row=i,column=1,sticky="ew",padx=5,ipady=5); self.provider_entries[provider]=ent
            if provider=="Ollama": ent.configure(state="disabled")
            health=self.provider_store.health(provider) if hasattr(self.provider_store,"health") else {}
            status=(health or {}).get("status", "NOT CONFIGURED")
            fg=GREEN if status in {"ONLINE","CATALOG ONLINE"} else (RED if "ERROR" in status or status=="OFFLINE" else MUTED)
            st=self.label(table,status,8,fg,True,bg); st.grid(row=i,column=2,sticky="w",padx=6); self.provider_status[provider]=st
            actions=tk.Frame(table,bg=bg); actions.grid(row=i,column=3,sticky="e",padx=4)
            self.button(actions,"IMPORT",lambda p=provider:self.import_provider_models(p),compact=True).pack(side="left",padx=2)
            self.button(actions,"TEST",lambda p=provider:self.test_provider_chat(p),compact=True,outline=True).pack(side="left",padx=2)
        bar=tk.Frame(providers,bg=PANEL); bar.pack(fill="x",padx=18,pady=(3,14))
        self.button(bar,"SAVE KEYS",self.save_provider_keys,accent=True,compact=True).pack(side="left")
        self.button(bar,"IMPORT ALL",self.import_all_models,compact=True).pack(side="left",padx=6)
        self.button(bar,"REFRESH CATALOG",self.refresh_catalog,compact=True,outline=True).pack(side="left",padx=2)

        # Routing + model catalog.
        modelrow=tk.Frame(wrap,bg=BG); modelrow.pack(fill="x",pady=(0,10)); modelrow.grid_columnconfigure(0,weight=1); modelrow.grid_columnconfigure(1,weight=1)
        routing=self.card(modelrow); routing.grid(row=0,column=0,sticky="nsew",padx=(0,5))
        self.label(routing,"AXON ROUTING",13,TEXT,True,PANEL).pack(anchor="w",padx=18,pady=(15,2))
        self.label(routing,"Choose how AXON balances capability, speed, cost and privacy.",8,MUTED,bg=PANEL).pack(anchor="w",padx=18,pady=(0,8))
        self.profile_var=tk.StringVar(value=self.provider_store.profile())
        combo=ttk.Combobox(routing,textvariable=self.profile_var,values=list(PROFILES),state="readonly"); combo.pack(fill="x",padx=18,ipady=5); combo.bind("<<ComboboxSelected>>",lambda e:self.save_profile())
        self.routing_status=self.label(routing,PROFILES.get(self.provider_store.profile(),""),8,MUTED,bg=PANEL,wraplength=520,justify="left"); self.routing_status.pack(anchor="w",padx=18,pady=(8,15))

        catalog=self.card(modelrow); catalog.grid(row=0,column=1,sticky="nsew",padx=(5,0))
        head=tk.Frame(catalog,bg=PANEL); head.pack(fill="x",padx=18,pady=(15,6)); head.grid_columnconfigure(0,weight=1)
        self.label(head,"CONNECTED MODELS",13,TEXT,True,PANEL).grid(row=0,column=0,sticky="w")
        self.button(head,"REFRESH",self.refresh_catalog,compact=True,outline=True).grid(row=0,column=1)
        self.catalog_box=tk.Text(catalog,bg=PANEL2,fg=TEXT,insertbackground=TEXT,relief="flat",font=("DejaVu Sans",8),height=13,wrap="none",state="disabled")
        self.catalog_box.pack(fill="both",expand=True,padx=14,pady=(0,14))
        self.catalog_box.configure(xscrollcommand=lambda *a:None)
        self.catalog_text_widget=self.catalog_box
        self.refresh_catalog()

        # Voice cards.
        voice_row=tk.Frame(wrap,bg=BG); voice_row.pack(fill="x",pady=(0,10)); voice_row.grid_columnconfigure(0,weight=1); voice_row.grid_columnconfigure(1,weight=1)
        gem=self.card(voice_row); gem.grid(row=0,column=0,sticky="nsew",padx=(0,5))
        self.label(gem,"GEMINI LIVE VOICE",13,TEXT,True,PANEL).pack(anchor="w",padx=18,pady=(15,2))
        self.label(gem,"Dedicated hands-free voice engine. Uses the same governed AXON router for commands.",8,MUTED,bg=PANEL).pack(anchor="w",padx=18,pady=(0,8))
        row=tk.Frame(gem,bg=PANEL); row.pack(fill="x",padx=18); row.grid_columnconfigure(0,weight=1)
        self.gemini_key_var=tk.StringVar(value=GEMINI_API_KEY or self.provider_store.get_key("Google Gemini"))
        self.gemini_key_entry=tk.Entry(row,textvariable=self.gemini_key_var,show="•",bg=PANEL2,fg=TEXT,insertbackground=TEXT,relief="flat",font=("DejaVu Sans",9)); self.gemini_key_entry.grid(row=0,column=0,sticky="ew",ipady=7)
        self.button(row,"SHOW",self.toggle_gemini_key,compact=True).grid(row=0,column=1,padx=(6,0))
        buttons=tk.Frame(gem,bg=PANEL); buttons.pack(fill="x",padx=18,pady=8)
        self.button(buttons,"SAVE & CONNECT",self.save_gemini_settings,accent=True,compact=True).pack(side="left")
        self.button(buttons,"TEST VOICE",self.test_gemini_voice,compact=True).pack(side="left",padx=6)
        self.gemini_settings_status=self.label(gem,"",8,MUTED,bg=PANEL,justify="left",anchor="nw",wraplength=520); self.gemini_settings_status.pack(fill="x",padx=18,pady=(0,12))

        voice=self.card(voice_row); voice.grid(row=0,column=1,sticky="nsew",padx=(5,0))
        self.label(voice,"VOICE PROFILE",13,TEXT,True,PANEL).pack(anchor="w",padx=18,pady=(15,2))
        self.label(voice,"Voice, activation and automatic-start preferences.",8,MUTED,bg=PANEL).pack(anchor="w",padx=18,pady=(0,8))
        grid=tk.Frame(voice,bg=PANEL); grid.pack(fill="x",padx=18); grid.grid_columnconfigure(1,weight=1)
        self.label(grid,"VOICE",8,MUTED,True,PANEL).grid(row=0,column=0,sticky="w",pady=4); self.gemini_voice_var=tk.StringVar(value=GEMINI_VOICE or "Charon")
        voice_values=["Charon","Kore","Puck","Aoede","Fenrir","Zephyr","Leda","Orus","Callirrhoe","Autonoe","Enceladus","Iapetus","Umbriel","Algieba","Despina","Erinome","Algenib","Rasalgethi","Laomedeia","Achernar","Alnilam","Schedar","Gacrux","Pulcherrima","Achird","Zubenelgenubi","Vindemiatrix","Sadachbia","Sadaltager","Sulafat"]
        ttk.Combobox(grid,textvariable=self.gemini_voice_var,values=voice_values,state="readonly").grid(row=0,column=1,sticky="ew",ipady=4,padx=(10,0))
        self.label(grid,"LIVE MODEL",8,MUTED,True,PANEL).grid(row=1,column=0,sticky="w",pady=4); self.gemini_model_var=tk.StringVar(value=GEMINI_LIVE_MODEL)
        tk.Entry(grid,textvariable=self.gemini_model_var,bg=PANEL2,fg=TEXT,insertbackground=TEXT,relief="flat",font=("DejaVu Sans",8)).grid(row=1,column=1,sticky="ew",ipady=6,padx=(10,0))
        self.label(grid,"MODE",8,MUTED,True,PANEL).grid(row=2,column=0,sticky="w",pady=4); self.voice_mode_var=tk.StringVar(value=self.provider_store.voice().get("mode","smart"))
        ttk.Combobox(grid,textvariable=self.voice_mode_var,values=["smart","wake","manual"],state="readonly").grid(row=2,column=1,sticky="ew",ipady=4,padx=(10,0))
        self.label(grid,"WAKE WORD",8,MUTED,True,PANEL).grid(row=3,column=0,sticky="w",pady=4); self.voice_wake_var=tk.StringVar(value=self.provider_store.voice().get("wake_word",WAKE_WORD))
        tk.Entry(grid,textvariable=self.voice_wake_var,bg=PANEL2,fg=TEXT,insertbackground=TEXT,relief="flat",font=("DejaVu Sans",8)).grid(row=3,column=1,sticky="ew",ipady=6,padx=(10,0))
        self.voice_autostart_var=tk.BooleanVar(value=bool(self.provider_store.voice().get("auto_start",True)))
        tk.Checkbutton(voice,text="Start voice automatically when Gemini is connected",variable=self.voice_autostart_var,bg=PANEL,fg=MUTED,selectcolor=PANEL2,activebackground=PANEL,activeforeground=TEXT).pack(anchor="w",padx=18,pady=(7,10))
        self.button(voice,"SAVE VOICE",self.save_voice_preferences,compact=True,outline=True).pack(anchor="w",padx=18,pady=(0,12))

        # Real integrations: compact cards while retaining every existing action.
        integ=self.card(wrap); integ.pack(fill="x",pady=(0,10))
        self.label(integ,"REAL ACCOUNT INTEGRATIONS",15,TEXT,True,PANEL).pack(anchor="w",padx=18,pady=(16,2))
        self.label(integ,"Official Gmail/Calendar OAuth, WhatsApp linked-device, WhatsApp Business Cloud and Meta Messenger. Credentials stay outside AXON memory.",8,MUTED,bg=PANEL).pack(anchor="w",padx=18,pady=(0,10))
        cards=tk.Frame(integ,bg=PANEL); cards.pack(fill="x",padx=12,pady=(0,10)); cards.grid_columnconfigure(0,weight=1); cards.grid_columnconfigure(1,weight=1)

        google=self.card(cards,bg=PANEL2); google.grid(row=0,column=0,sticky="nsew",padx=5,pady=5)
        self.label(google,"GOOGLE · GMAIL + CALENDAR",10,TEXT,True,PANEL2).pack(anchor="w",padx=14,pady=(12,2))
        self.google_credentials_var=tk.StringVar(value=self.integrations.settings.section("google").get("credentials_file", ""))
        gr=tk.Frame(google,bg=PANEL2); gr.pack(fill="x",padx=14,pady=6); gr.grid_columnconfigure(0,weight=1)
        tk.Entry(gr,textvariable=self.google_credentials_var,bg=INPUT,fg=TEXT,insertbackground=TEXT,relief="flat",font=("DejaVu Sans",8)).grid(row=0,column=0,sticky="ew",ipady=6)
        self.button(gr,"BROWSE",self.choose_google_credentials,compact=True,outline=True).grid(row=0,column=1,padx=5)
        self.button(gr,"SAVE",self.save_google_config,compact=True).grid(row=0,column=2)
        self.google_status=self.label(google,"Google: not configured",8,MUTED,bg=PANEL2); self.google_status.pack(anchor="w",padx=14)
        ab=tk.Frame(google,bg=PANEL2); ab.pack(fill="x",padx=14,pady=(7,12))
        self.gmail_integration_status=self.label(ab,"Gmail: not connected",8,MUTED,bg=PANEL2); self.gmail_integration_status.pack(side="left",expand=True,fill="x")
        self.button(ab,"CONNECT GMAIL",self.connect_gmail_real,compact=True,accent=True).pack(side="left",padx=2); self.button(ab,"INBOX",self.read_gmail_integration,compact=True).pack(side="left",padx=2)
        cb=tk.Frame(google,bg=PANEL2); cb.pack(fill="x",padx=14,pady=(0,12))
        self.calendar_integration_status=self.label(cb,"Calendar: not connected",8,MUTED,bg=PANEL2); self.calendar_integration_status.pack(side="left",expand=True,fill="x")
        self.button(cb,"CONNECT",self.connect_calendar_real,compact=True).pack(side="left",padx=2); self.button(cb,"TODAY",self.read_calendar_real,compact=True).pack(side="left",padx=2)

        wa=self.card(cards,bg=PANEL2); wa.grid(row=0,column=1,sticky="nsew",padx=5,pady=5)
        self.label(wa,"WHATSAPP",10,TEXT,True,PANEL2).pack(anchor="w",padx=14,pady=(12,2))
        self.whatsapp_integration_status=self.label(wa,"Linked device: not connected",8,MUTED,bg=PANEL2); self.whatsapp_integration_status.pack(anchor="w",padx=14,pady=(2,5))
        wb=tk.Frame(wa,bg=PANEL2); wb.pack(fill="x",padx=14,pady=(0,10))
        self.button(wb,"LINK DEVICE",self.connect_whatsapp_linked,compact=True,accent=True).pack(side="left"); self.button(wb,"READ CHATS",self.read_whatsapp_chats,compact=True).pack(side="left",padx=6)
        self.label(wa,"WHATSAPP BUSINESS CLOUD",9,GOLD,True,PANEL2).pack(anchor="w",padx=14,pady=(3,2))
        wg=tk.Frame(wa,bg=PANEL2); wg.pack(fill="x",padx=14); wg.grid_columnconfigure(0,weight=1); wg.grid_columnconfigure(1,weight=1); wg.grid_columnconfigure(2,weight=1)
        self.wa_token_var=tk.StringVar(value=self.integrations.settings.section("whatsapp_cloud").get("token", "")); self.wa_phone_var=tk.StringVar(value=self.integrations.settings.section("whatsapp_cloud").get("phone_number_id", "")); self.wa_waba_var=tk.StringVar(value=self.integrations.settings.section("whatsapp_cloud").get("waba_id", ""))
        tk.Entry(wg,textvariable=self.wa_token_var,show="•",bg=INPUT,fg=TEXT,relief="flat",font=("DejaVu Sans",8)).grid(row=0,column=0,sticky="ew",ipady=6,padx=(0,3)); tk.Entry(wg,textvariable=self.wa_phone_var,bg=INPUT,fg=TEXT,relief="flat",font=("DejaVu Sans",8)).grid(row=0,column=1,sticky="ew",ipady=6,padx=3); tk.Entry(wg,textvariable=self.wa_waba_var,bg=INPUT,fg=TEXT,relief="flat",font=("DejaVu Sans",8)).grid(row=0,column=2,sticky="ew",ipady=6,padx=(3,0))
        self.whatsapp_cloud_status=self.label(wa,"Cloud API: not connected",8,MUTED,bg=PANEL2); self.whatsapp_cloud_status.pack(anchor="w",padx=14,pady=(4,4))
        self.button(wa,"SAVE CLOUD",self.save_whatsapp_cloud,compact=True,outline=True).pack(anchor="w",padx=14,pady=(0,12))

        meta=self.card(cards,bg=PANEL2); meta.grid(row=1,column=0,sticky="nsew",padx=5,pady=5)
        self.label(meta,"META MESSENGER",10,TEXT,True,PANEL2).pack(anchor="w",padx=14,pady=(12,2))
        mg=tk.Frame(meta,bg=PANEL2); mg.pack(fill="x",padx=14); mg.grid_columnconfigure(0,weight=1); mg.grid_columnconfigure(1,weight=1)
        self.meta_token_var=tk.StringVar(value=self.integrations.settings.section("meta_messenger").get("token", "")); self.meta_page_var=tk.StringVar(value=self.integrations.settings.section("meta_messenger").get("page_id", ""))
        tk.Entry(mg,textvariable=self.meta_token_var,show="•",bg=INPUT,fg=TEXT,relief="flat",font=("DejaVu Sans",8)).grid(row=0,column=0,sticky="ew",ipady=6,padx=(0,3)); tk.Entry(mg,textvariable=self.meta_page_var,bg=INPUT,fg=TEXT,relief="flat",font=("DejaVu Sans",8)).grid(row=0,column=1,sticky="ew",ipady=6,padx=(3,0))
        self.meta_status=self.label(meta,"Messenger: not connected",8,MUTED,bg=PANEL2); self.meta_status.pack(anchor="w",padx=14,pady=(4,5))
        self.button(meta,"SAVE MESSENGER",self.save_meta_config,compact=True,outline=True).pack(anchor="w",padx=14,pady=(0,12))

        status=self.card(cards,bg=PANEL2); status.grid(row=1,column=1,sticky="nsew",padx=5,pady=5)
        self.label(status,"INTEGRATION ACTIVITY",10,TEXT,True,PANEL2).pack(anchor="w",padx=14,pady=(12,4))
        self.integration_result=self.label(status,"Ready. Configure an account, then connect or read from it.",8,MUTED,bg=PANEL2,justify="left",anchor="nw",wraplength=520); self.integration_result.pack(fill="both",expand=True,padx=14,pady=(0,12))
        self.refresh_integration_status()

        # Sentinel threat-intelligence providers. Secrets use the same owner-only
        # integration settings store and never enter AXON memory.
        intel=self.card(wrap); intel.pack(fill="x",pady=(0,10))
        self.label(intel,"SENTINEL THREAT INTELLIGENCE",13,TEXT,True,PANEL).pack(anchor="w",padx=18,pady=(14,2))
        self.label(intel,"Optional API keys improve coverage. PhishTank remains available without a key but is rate-limited.",8,MUTED,bg=PANEL,wraplength=1000,justify="left").pack(anchor="w",padx=18,pady=(0,8))
        cfg=self.integrations.settings.section("security_intel")
        it=tk.Frame(intel,bg=PANEL); it.pack(fill="x",padx=18,pady=(0,10)); it.grid_columnconfigure(1,weight=1); it.grid_columnconfigure(3,weight=1)
        self.security_intel_vars={}
        for row,(label,key) in enumerate([("Google Safe Browsing","google_safe_browsing"),("VirusTotal","virustotal"),("urlscan.io","urlscan"),("PhishTank app key","phishtank")]):
            r=row//2; c=(row%2)*2
            self.label(it,label,8,MUTED,True,PANEL).grid(row=r,column=c,sticky="w",padx=(0,7),pady=5)
            var=tk.StringVar(value=cfg.get(key,"")); self.security_intel_vars[key]=var
            tk.Entry(it,textvariable=var,show="•",bg=INPUT,fg=TEXT,insertbackground=TEXT,relief="flat",font=("DejaVu Sans",8)).grid(row=r,column=c+1,sticky="ew",padx=(0,12),ipady=5)
        self.button(intel,"SAVE THREAT INTELLIGENCE KEYS",self.save_security_intel,accent=True,compact=True).pack(anchor="w",padx=18,pady=(0,12))

        workspace=self.card(wrap); workspace.pack(fill="x",pady=(0,10))
        self.label(workspace,"WORKSPACE INTEGRATIONS",13,TEXT,True,PANEL).pack(anchor="w",padx=18,pady=(14,2))
        self.label(workspace,"Web search, image generation and other workspace services remain available through their existing governed configuration.",8,MUTED,bg=PANEL).pack(anchor="w",padx=18,pady=(0,14))

    def save_security_intel(self):
        values={key:var.get().strip() for key,var in self.security_intel_vars.items()}
        self.integrations.settings.save("security_intel", values)
        self._integration_done("Sentinel threat-intelligence configuration saved. Clean results will remain explicitly non-definitive.")

    def choose_google_credentials(self):
        path=filedialog.askopenfilename(title="Select Google OAuth credentials.json",filetypes=[("JSON files","*.json"),("All files","*")])
        if path: self.google_credentials_var.set(path)

    def save_google_config(self):
        path=self.google_credentials_var.get().strip()
        if not path:
            self._integration_done("Select the Google OAuth credentials.json file first.", True); return
        self.integrations.configure_google(path)
        self._integration_done("Google OAuth configuration saved. Gmail and Calendar are ready to authenticate when you press Connect.")

    def connect_calendar_real(self):
        self._integration_done("Opening Google authorization for Calendar…", False)
        def worker():
            try:
                profile=self.integrations.calendar._api().calendarList().list(maxResults=1).execute()
                self.after(0,lambda:self._integration_done(f"✓ Google Calendar connected ({len(profile.get('items',[]))} calendar visible)."))
            except Exception as e:
                self.after(0,lambda:self._integration_done(f"Calendar connection failed: {e}", True))
        threading.Thread(target=worker,daemon=True).start()

    def read_calendar_real(self):
        from datetime import datetime, timedelta, timezone
        def worker():
            try:
                start=datetime.now(timezone.utc); end=start+timedelta(days=1)
                events=self.integrations.calendar.list_events(start,end)
                text="Today’s calendar:\n"+"\n".join(f"{e.start.isoformat()} — {e.title}" for e in events) if events else "Today’s calendar is empty."
                self.after(0,lambda:self._integration_done(text))
            except Exception as e:
                self.after(0,lambda:self._integration_done(f"Cannot read Calendar: {e}", True))
        threading.Thread(target=worker,daemon=True).start()

    def save_whatsapp_cloud(self):
        token=self.wa_token_var.get().strip(); phone=self.wa_phone_var.get().strip(); waba=self.wa_waba_var.get().strip()
        if not token or not phone:
            self._integration_done("WhatsApp Cloud requires an access token and phone number ID.", True); return
        self.integrations.configure_whatsapp_cloud(token,phone,waba)
        self._integration_done("WhatsApp Cloud credentials saved locally. Use a webhook for incoming messages and a governed confirmation for sending.")
        self.refresh_integration_status()

    def save_meta_config(self):
        token=self.meta_token_var.get().strip(); page=self.meta_page_var.get().strip()
        if not token or not page:
            self._integration_done("Meta Messenger requires a Page access token and Page ID.", True); return
        self.integrations.configure_meta(token,page)
        self._integration_done("Meta Messenger credentials saved locally. Webhook subscription can now be tested.")
        self.refresh_integration_status()

    def refresh_integration_status(self):
        def worker():
            try:
                gmail=self.integrations.gmail.is_connected()
            except Exception:
                gmail=False
            try:
                wa=self.integrations.whatsapp_linked.status()
            except Exception as e:
                wa={"connected":False,"state":f"error: {e}"}
            try: cal=self.integrations.calendar.is_connected()
            except Exception: cal=False
            try: cloud=self.integrations.whatsapp.is_connected()
            except Exception: cloud=False
            try: meta=self.integrations.messenger.is_connected()
            except Exception: meta=False
            self.after(0,lambda: self._set_integration_status(gmail,wa,cal,cloud,meta))
        threading.Thread(target=worker,daemon=True).start()

    def _set_integration_status(self,gmail,wa,cal=False,cloud=False,meta=False):
        if hasattr(self,"gmail_integration_status"):
            self.gmail_integration_status.configure(text="Gmail: connected ✓" if gmail else "Gmail: not connected",fg=GREEN if gmail else MUTED)
        if hasattr(self,"whatsapp_integration_status"):
            state=wa.get("state","unknown") if isinstance(wa,dict) else "unknown"
            connected=bool(wa.get("connected")) if isinstance(wa,dict) else False
            text="WhatsApp linked device: connected ✓" if connected else f"WhatsApp linked device: {state}"
            self.whatsapp_integration_status.configure(text=text,fg=GREEN if connected else MUTED)
        if hasattr(self,"calendar_integration_status"):
            self.calendar_integration_status.configure(text="Calendar: connected ✓" if cal else "Calendar: not connected",fg=GREEN if cal else MUTED)
        if hasattr(self,"whatsapp_cloud_status"):
            self.whatsapp_cloud_status.configure(text="Cloud API: connected ✓" if cloud else "Cloud API: not connected",fg=GREEN if cloud else MUTED)
        if hasattr(self,"meta_status"):
            self.meta_status.configure(text="Messenger: connected ✓" if meta else "Messenger: not connected",fg=GREEN if meta else MUTED)

    def connect_gmail_real(self):
        if hasattr(self,"integration_result"):
            self.integration_result.configure(text="Opening Google authorization in your browser…",fg=AMBER)
        def worker():
            try:
                profile=self.integrations.gmail.profile()
                email=profile.get("emailAddress","connected account")
                self.after(0,lambda:self._integration_done(f"✓ Gmail connected: {email}"))
            except Exception as e:
                self.after(0,lambda:self._integration_done(f"Gmail connection failed: {e}",True))
        threading.Thread(target=worker,daemon=True).start()

    def read_gmail_integration(self):
        def worker():
            try:
                msgs=self.integrations.gmail.list_inbox(10)
                lines=[f"{m.sender or 'unknown'} — {m.subject or '(no subject)'}\n{(m.snippet or m.body[:160]).replace(chr(10),' ')[:180]}" for m in msgs]
                text="\n\n".join(lines) if lines else "Inbox is empty or no messages matched."
                self.after(0,lambda:self._integration_done("Gmail inbox:\n"+text))
            except Exception as e:
                self.after(0,lambda:self._integration_done(f"Cannot read Gmail: {e}",True))
        threading.Thread(target=worker,daemon=True).start()

    def connect_whatsapp_linked(self):
        if hasattr(self,"integration_result"):
            self.integration_result.configure(text="Opening WhatsApp Web. Scan the QR code using WhatsApp → Linked devices on your phone…",fg=AMBER)
        def worker():
            try:
                state=self.integrations.whatsapp_linked.connect()
                self.after(0,lambda:self._integration_done(f"WhatsApp Web state: {state.get('state','unknown')}. Keep the browser window open while linking."))
            except Exception as e:
                self.after(0,lambda:self._integration_done(f"WhatsApp connection failed: {e}",True))
            finally:
                self.after(0,self.refresh_integration_status)
        threading.Thread(target=worker,daemon=True).start()

    def read_whatsapp_chats(self):
        def worker():
            try:
                chats=self.integrations.whatsapp_linked.chats(15)
                text="WhatsApp chats:\n"+"\n".join(x.get("text","")[:220] for x in chats)
                self.after(0,lambda:self._integration_done(text))
            except Exception as e:
                self.after(0,lambda:self._integration_done(f"Cannot read WhatsApp: {e}",True))
        threading.Thread(target=worker,daemon=True).start()

    def _integration_done(self,text,error=False):
        if hasattr(self,"integration_result"):
            self.integration_result.configure(text=text,fg=RED if error else GREEN)
        self.refresh_integration_status()

    def catalog_text(self):
        lines=["PROVIDER / MODEL                                      TYPE        FLAGS"]
        lines.append("─"*76)
        count=0
        for provider in PROVIDERS:
            ms=self.provider_store.models(provider)
            for m in ms[:80]:
                flags=[]
                if m.get("reasoning"): flags.append("reason")
                if m.get("coding"): flags.append("code")
                if m.get("vision"): flags.append("vision")
                if m.get("fast"): flags.append("fast")
                if m.get("free"): flags.append("free")
                model_id=str(m.get("id",""))[:48]
                lines.append(f"{provider[:18]:18} / {model_id:<48} {m.get('kind','chat'):<10} {','.join(flags)}")
                count+=1
        return "\n".join(lines) if count else "No imported catalogs yet. Add provider keys and click IMPORT MODELS."

    def save_provider_keys(self):
        for provider,var in self.provider_vars.items():
            if provider != "Ollama": self.provider_store.set_key(provider,var.get())
        self.gemini_key_var.set(self.provider_store.get_key("Google Gemini") or self.gemini_key_var.get())
        self.gemini_settings_status.configure(text="✓ Provider keys saved locally. Import models to refresh each catalog.",fg=GREEN)
        self.after(3000,self._clear_voice_settings_status)

    def save_profile(self):
        profile=self.profile_var.get(); self.provider_store.set_profile(profile)
        self.routing_status.configure(text=PROFILES.get(profile,"")); self.refresh_catalog()

    def import_provider_models(self, provider):
        key=self.provider_store.get_key(provider) if provider=="Ollama" else self.provider_vars[provider].get().strip()
        if provider!="Ollama": self.provider_store.set_key(provider,key)
        if hasattr(self,"provider_status"): self.provider_status[provider].configure(text="Connecting…",fg=AMBER)
        def worker():
            try:
                h=provider_health(provider,key)
                self.provider_store.set_health(provider,h.get("status","OFFLINE"),latency_ms=h.get("latency_ms"),error=h.get("error"),models=h.get("models",0))
                if not h.get("ok"): raise RuntimeError(h.get("error") or h.get("status"))
                models=fetch_models(provider,key)
                self.provider_store.set_models(provider,models)
                routable=sum(1 for m in models if m.get("routable", True))
                self.after(0,lambda routable=routable:self.provider_status[provider].configure(text=f"✓ ONLINE · {routable}/{len(models)} routable · {h.get('latency_ms','—')} ms",fg=GREEN))
                self.after(0,self.refresh_catalog); self.after(0,self.render_provider_models if hasattr(self,"render_provider_models") else self.refresh)
            except Exception as e:
                self.provider_store.set_health(provider,"OFFLINE",error=str(e))
                err_text = str(e)[:140]
                self.after(0,lambda err_text=err_text:self.provider_status[provider].configure(text=f"✗ {err_text}",fg=RED))
        threading.Thread(target=worker,daemon=True).start()

    def import_all_models(self):
        self.save_provider_keys()
        for provider in PROVIDERS:
            if provider=="Ollama" or self.provider_store.get_key(provider):
                self.import_provider_models(provider)

    def refresh_catalog(self):
        text=self.catalog_text()
        if hasattr(self,"catalog_box"):
            try:
                if isinstance(self.catalog_box, tk.Text):
                    self.catalog_box.configure(state="normal"); self.catalog_box.delete("1.0","end"); self.catalog_box.insert("1.0",text); self.catalog_box.configure(state="disabled")
                else:
                    self.catalog_box.configure(text=text)
            except Exception:
                pass

    def toggle_gemini_key(self):
        self.gemini_key_entry.configure(show="" if self.gemini_key_entry.cget("show") else "•")

    def save_voice_preferences(self):
        mode=self.voice_mode_var.get().strip() if hasattr(self,"voice_mode_var") else self.provider_store.voice().get("mode","smart")
        wake=self.voice_wake_var.get().strip() if hasattr(self,"voice_wake_var") else WAKE_WORD
        auto=bool(self.voice_autostart_var.get()) if hasattr(self,"voice_autostart_var") else True
        if mode not in {"smart","wake","manual"}:
            mode="smart"
        self.provider_store.set_voice(mode=mode, wake_word=wake or WAKE_WORD, auto_start=auto)
        if hasattr(self,"voice_prompt"):
            self.voice_prompt.configure(text=self.voice_prompt_text())
        self.gemini_settings_status.configure(text=f"✓ Voice preferences saved · {mode} mode",fg=GREEN)
        if mode == "manual" and self.gemini_voice.running:
            self.gemini_voice.stop()

    def save_gemini_settings(self):
        self.save_voice_preferences()
        from dotenv import set_key
        from . import config
        key=self.gemini_key_var.get().strip()
        model=self.gemini_model_var.get().strip() or GEMINI_LIVE_MODEL
        voice=self.gemini_voice_var.get().strip() or "Charon"
        try:
            self.provider_store.set_key("Google Gemini", key)
            if hasattr(self,"provider_vars") and "Google Gemini" in self.provider_vars: self.provider_vars["Google Gemini"].set(key)
            set_key(str(config.BASE / ".env"), "GEMINI_API_KEY", key)
            set_key(str(config.BASE / ".env"), "GEMINI_LIVE_MODEL", model)
            set_key(str(config.BASE / ".env"), "GEMINI_VOICE", voice)
            self.gemini_voice.stop()
            self.gemini_voice=GeminiLiveVoice(key,self.gemini_voice_text,self.voice_state,model,voice,on_audio_level=self.voice_audio_level)
            self.gemini_voice.set_output_transcript_callback(self.gemini_voice_output_text)
            self.gemini_voice.set_input_transcript_callbacks(self.gemini_voice_partial_text, self.gemini_voice_error)
            if not key:
                self.gemini_settings_status.configure(text="Enter a Gemini API key first.",fg=AMBER)
                return
            import requests
            try:
                r=requests.get("https://generativelanguage.googleapis.com/v1beta/models",headers={"x-goog-api-key":key},timeout=8)
                if r.ok:
                    self.gemini_settings_status.configure(text="✓ API key verified · Gemini Live connecting…",fg=GREEN)
                    self.after(250,self.start_selected_voice)
                    self.after(3000,self._clear_voice_settings_status)
                else:
                    self.gemini_settings_status.configure(text=f"API verification failed (HTTP {r.status_code}). Check the key and API restrictions.",fg=RED)
            except Exception as e:
                self.gemini_settings_status.configure(text=f"Key saved locally, but verification could not reach Gemini: {e}",fg=AMBER)
        except Exception as e:
            self.gemini_settings_status.configure(text=f"Could not save Gemini settings: {e}",fg=RED)

    def _clear_voice_settings_status(self):
        if hasattr(self,"gemini_settings_status"):
            try: self.gemini_settings_status.configure(text="")
            except Exception: pass

    def test_gemini_voice(self):
        if not self.gemini_key_var.get().strip():
            self.gemini_settings_status.configure(text="Enter your Gemini API key first.",fg=AMBER)
            return
        self.save_gemini_settings()

    def set_voice_provider(self,provider):
        self.voice_provider="gemini"

    def start_selected_voice(self):
        if not self.gemini_voice.available:
            if hasattr(self,"gemini_settings_status"):
                self.gemini_settings_status.configure(text="Gemini Live is not ready. Check the API key and microphone.",fg=RED)
            return False
        return self.gemini_voice.start()

    def stop_selected_voice(self):
        self.gemini_voice.stop()

    def test_selected_voice(self):
        return self.test_gemini_voice()

    def page_ui(self):
        self.two_col_header("UI STUDIO", "Customize AXON without changing its command engine.")
        p=self.card(self.content); p.pack(fill="both",expand=True,pady=16)
        self.label(p,"APPEARANCE",13,TEXT,True,PANEL).pack(anchor="w",padx=22,pady=(22,12))
        for title,var in [("Compact navigation",tk.BooleanVar(value=False)),("Reduce motion",tk.BooleanVar(value=False)),("High contrast",tk.BooleanVar(value=False))]:
            tk.Checkbutton(p,text=title,variable=var,bg=PANEL,fg=MUTED,selectcolor=PANEL2,activebackground=PANEL,activeforeground=TEXT).pack(anchor="w",padx=24,pady=6)
        self.label(p,"V15 gold-glass command-center design system",9,MUTED,bg=PANEL).pack(anchor="w",padx=24,pady=(22,3)); self.label(p,"Gold glass workspace · amber action layer · green telemetry · governed AI actions",10,TEXT,bg=PANEL).pack(anchor="w",padx=24)

    def two_col_header(self,title,subtitle):
        self.label(self.content,title,24,TEXT,True,BG).pack(anchor="w")
        self.label(self.content,subtitle,9,MUTED,bg=BG).pack(anchor="w",pady=(3,0))

    # ---------- commands ----------
    def submit(self):
        if not hasattr(self,"input"): return
        text=self.input.get().strip()
        if not text or self.busy: return
        self.input.delete(0,"end")
        self._add_message("user", text)
        self._stream_message = None
        self._stream_text = ""
        self.busy=True
        threading.Thread(target=self.process,args=(text,),daemon=True).start()

    def process(self,text):
        try:
            result=self.router.route(text,self)
            if result:
                if isinstance(result, ActionResult):
                    self.after(0,lambda r=result:self.respond(r.message, links=r.data.get("links")))
                else:
                    self.after(0,lambda r=result:self.respond(r))
                return
            def token(chunk):
                self.after(0,lambda c=chunk:self.append_stream(c))
            answer,provider,model=self.router.stream_answer(text,token)
            self.after(0,lambda:self.finish_stream(answer, provider, model))
        except Exception as e:
            err_text = str(e)
            self.after(0,lambda err_text=err_text:self.respond(f"I couldn't complete that request: {err_text}"))
        finally:
            self.after(0,lambda:self._done())

    def _done(self): self.busy=False

    def append_stream(self,text):
        if self.current_page != "Home" or not text:
            return
        if self._stream_message is None:
            self._stream_message = self._add_message("assistant", "")
        if self._stream_message is None:
            return
        self._stream_text += str(text)
        self._stream_message["value"].set(self._plain_chat_text(self._stream_text))
        self.after_idle(self._scroll_conversation_to_end)

    def finish_stream(self,text,provider,model):
        if hasattr(self,"online"):
            self.online.configure(text="● Connected", fg=GREEN)
        clean = self._clean_assistant_reply(text)
        if self.current_page == "Home":
            if self._stream_message is None:
                self._add_message("assistant", clean)
            elif clean and clean != self._stream_text:
                # Providers occasionally return a normalized final answer after
                # token delivery. Replace the in-progress content once, rather
                # than duplicating it in the transcript.
                self._stream_message["value"].set(clean)
        self._stream_message = None
        self._stream_text = ""
        self.memory.record("conversation", "AXON response", text, True)
        self.refresh()

    def respond(self,text, provider=None, model=None, links=None):
        if self.current_page == "Home":
            self._add_message("assistant", self._clean_assistant_reply(text), links=links)
        self.memory.record("conversation", "AXON response", text, True)
        self.refresh()

    def append(self,speaker,text,tag="body"):
        # Preserve the legacy call shape for router actions while rendering
        # through the modern message surface.
        if self.current_page == "Home":
            self._add_message("user" if speaker.upper() == "YOU" else "assistant", text)

    def _clean_assistant_reply(self, text):
        """Keep transport identity and model chatter out of the user transcript."""
        clean = str(text or "").strip()
        clean = re.sub(r"^(?:AXON|assistant)\s*:\s*", "", clean, flags=re.IGNORECASE)
        clean = self._plain_chat_text(clean)
        return clean or "I couldn't generate a response. Please try again."

    @staticmethod
    def _plain_chat_text(text):
        """Display assistant output as plain chat text, without Markdown asterisks."""
        return str(text or "").replace("*", "")

    def voice_prompt_text(self):
        mode = self.provider_store.voice().get("mode", "smart")
        if mode == "wake":
            wake = self.provider_store.voice().get("wake_word", WAKE_WORD)
            return f"Wake word mode · say “{wake}” followed by your command"
        if mode == "manual":
            return "Manual voice mode · press MIC to start listening"
        return "Smart voice mode · speak naturally — no wake word required"

    def gemini_voice_text(self,text):
        # GeminiLiveVoice calls this only at a completed user turn.  Partial
        # transcription has a separate callback and is never routed.
        raw=(text or "").strip()
        if not raw: return
        cleaned=re.sub(r"\s+"," ",raw).strip()
        settings=self.provider_store.voice()
        mode=settings.get("mode","smart")
        wake=re.sub(r"[^a-zA-Z0-9\s]","",settings.get("wake_word",WAKE_WORD).lower()).strip()
        low=cleaned.lower()
        if mode == "wake":
            normalized=re.sub(r"[^a-zA-Z0-9\s]","",low).strip()
            if not wake or not normalized.startswith(wake):
                return
            cleaned=cleaned[len(settings.get("wake_word",WAKE_WORD)):].strip(" ,.!?-")
        elif wake and low.startswith(wake):
            cleaned=cleaned[len(settings.get("wake_word",WAKE_WORD)):].strip(" ,.!?-")
        if not cleaned: return
        routed=self._normalise_voice_command(cleaned)
        LOG.info("Voice command submitted: %s", cleaned)
        if routed != cleaned:
            LOG.info("Voice Kiswahili command normalized for AXON router: %s", routed)
        try:
            self.after(0,lambda c=cleaned:self._record_voice_user(c))
        except (tk.TclError, RuntimeError):
            return
        threading.Thread(target=self._govern_voice_command,args=(routed,),daemon=True).start()

    @staticmethod
    def _normalise_voice_command(text):
        """Map common Kiswahili task phrasing to existing governed intents.

        The visible transcript is never translated or replaced. This conversion
        exists only because the deterministic router's task grammar is English;
        every resulting action still uses its normal approval flow.
        """
        raw=str(text or "").strip()
        low=raw.lower()
        match=re.match(r"^(?:tafuta kwenye wavuti|tafuta mtandaoni|tafuta)\s+(.+)$", raw, re.I)
        if match:
            return f"search the web for {match.group(1).strip()}"
        match=re.match(r"^(?:cheza|sikiliza)\s+(.+)$", raw, re.I)
        if match:
            return f"play {match.group(1).strip()}"
        if low in {"fungua terminal", "fungua terminali"}:
            return "open terminal"
        if low in {"fungua kivinjari", "fungua browser"}:
            return "open browser"
        if low in {"angalia hali ya mfumo", "hali ya mfumo", "kagua hali ya mfumo"}:
            return "check system status"
        if low in {"saa ngapi", "ni saa ngapi", "muda gani sasa"}:
            return "What is the current time?"
        if low in {"eleza axon ni nini", "axon ni nini"}:
            return "Explain what AXON is."
        return raw

    def gemini_voice_partial_text(self, text):
        """Display non-final recognition progress without submitting it."""
        clean = re.sub(r"\s+", " ", str(text or "")).strip()
        if not clean:
            return
        LOG.info("Voice partial transcript received: %s", clean)
        try:
            self.after(0, lambda t=clean: self._voice_append_transcript("HEARING", t, "system"))
        except (tk.TclError, RuntimeError):
            pass

    def gemini_voice_error(self, message):
        LOG.error("Voice Gemini Live error: %s", message)
        try:
            self.after(0, lambda m=str(message): self._voice_append_transcript("SYSTEM", f"VOICE ERROR: {m}", "system"))
        except (tk.TclError, RuntimeError):
            pass

    def _record_voice_user(self,text):
        self._voice_append_transcript("YOU",text,"you")
        if self.current_page == "Home":
            self._add_message("user",text)
        if self._voice_widget_alive("voice_diag"):
            try:
                self.voice_diag.configure(text=self.voice_diagnostic_text())
            except (tk.TclError, RuntimeError):
                pass

    def _govern_voice_command(self,text):
        # A completed Live turn is one command. Serialize execution so a new
        # utterance cannot race an in-progress web search, music launch, or
        # other task from the same router used by typed chat.
        with self._voice_command_lock:
            self._run_voice_command(text)

    def _run_voice_command(self,text):
        try:
            # The user explicitly requested automatic Voice playback. Keep this
            # narrow: only a recognized music command skips the router's normal
            # external-open confirmation; all other governed actions retain it.
            intent = parse_intent(text)
            if intent and intent.name == "youtube_music":
                message = self._play_youtube_from_voice(intent.args.get("query", ""))
                self.memory.record("voice youtube playback", text, message, "Could not" not in message)
                self._deliver_voice_response(message)
                return
            result=self.router.route(text,self)
            if result:
                message=result.message if isinstance(result,ActionResult) else str(result)
                ok=not isinstance(result,ActionResult) or result.ok
                self.memory.record("gemini voice action",text,message,ok)
            else:
                # Use the same provider/router path as typed chat for every
                # non-action command.  Live is responsible only for STT/TTS.
                language = self._voice_reply_language(text)
                language_prompt = f"{text}\n\nReply only in {language}. Do not add a translation or a second language."
                message, _provider, _model = self.router.stream_answer(language_prompt, lambda _chunk: None)
                self.memory.record("gemini voice answer", text, message, True)
            message = str(message or "").strip()
            if not message:
                raise RuntimeError("AXON produced an empty response for the recognized voice command")
            self._deliver_voice_response(message)
        except Exception as e:
            err_text=str(e)
            self.memory.record("gemini voice error",text,err_text,False)
            LOG.exception("Voice command failed: %s", text)
            try:
                self.after(0,lambda e=err_text:self._record_voice_assistant(f"Voice request failed: {e}"))
            except (tk.TclError, RuntimeError):
                pass

    @staticmethod
    def _youtube_search_url(query):
        return "https://www.youtube.com/results?search_query=" + quote_plus(str(query or "music").strip() or "music")

    @staticmethod
    def _voice_reply_language(text):
        """Choose one supported reply language; English is the safe default."""
        words=set(re.findall(r"[a-z]+", str(text or "").lower()))
        kiswahili={"habari", "mimi", "nina", "naweza", "vipi", "tafuta", "cheza", "sikiliza", "fungua", "kivinjari", "hali", "mfumo", "saa", "ngapi", "ni", "nini", "asante"}
        return "Kiswahili" if words & kiswahili else "English"

    def _play_youtube_from_voice(self, query):
        """Open standard YouTube, then activate the first video result.

        This is deliberately Voice-only and is entered only from a recognized
        play/listen command, which is the user's explicit authorization for
        automatic playback. Browser consent, sign-in, ads, and restricted media
        remain controlled by YouTube/the browser and are reported honestly.
        """
        url = self._youtube_search_url(query)
        opened = browser_control({"action": "go_to", "url": url, "browser": "brave"})
        if not str(opened).startswith("Opened"):
            return f"Could not open YouTube for {query or 'music'}: {opened}"
        played = browser_control({
            "action": "youtube_play", "query": query or "music", "browser": "brave"
        })
        if str(played).startswith("Playing"):
            return str(played)
        return f"Opened YouTube search for {query or 'music'}, but AXON could not start playback automatically: {played}"

    def _deliver_voice_response(self, message):
        message = str(message or "").strip()
        if not message:
            raise RuntimeError("AXON produced an empty response for the recognized voice command")
        LOG.info("Voice AXON response received: %s", message)
        try:
            self.after(0, lambda m=message: self._record_voice_assistant(m))
        except (tk.TclError, RuntimeError):
            return
        # The Gemini Live speaker remains the configured voice engine. TTS is
        # durable across a transient Live disconnect: the voice engine queues
        # the verified result and automatically recovers its session. A browser
        # or network hiccup must never turn a completed AXON command into a
        # false "voice command failed" result.
        queued = self.gemini_voice.send_text(
            f"Speak this AXON response naturally and exactly: {message}"
        )
        if queued:
            LOG.info("Voice TTS queued (Live session may reconnect before playback)")
        else:
            LOG.warning("Voice TTS could not be queued; verified response remains visible in AXON UI")

    def gemini_voice_output_text(self,text):
        if not text: return
        # The verified router response is inserted above before requesting TTS.
        # Retaining this callback only for diagnostics prevents a second,
        # model-rephrased transcript from replacing or duplicating it.
        LOG.info("Voice TTS output transcript: %s", str(text).strip())
        return
        # Output transcription can arrive in several small server events.
        # Coalesce them so one spoken answer becomes one AXON chat bubble.
        def collect():
            self._voice_output_buffer = (self._voice_output_buffer + " " + str(text)).strip()
            self._cancel_voice_output_job()
            try:
                self._voice_output_job = self.after(220,self._flush_voice_output)
            except (tk.TclError, RuntimeError):
                self._voice_output_job = None
        self.after(0,collect)

    def _flush_voice_output(self):
        self._voice_output_job = None
        if getattr(self, "_shutdown_started", False):
            self._voice_output_buffer = ""
            return
        text=self._voice_output_buffer.strip()
        self._voice_output_buffer=""
        if text:
            self._record_voice_assistant(text)

    def _record_voice_assistant(self,text):
        self._voice_append_transcript("AXON",text,"axon")
        if self.current_page == "Home":
            self._add_message("assistant",text)
        if self._voice_widget_alive("voice_diag"):
            try:
                self.voice_diag.configure(text=self.voice_diagnostic_text())
            except (tk.TclError, RuntimeError):
                pass

    def _gemini_command(self,text):
        # Manual quick-action buttons use the same governed execution path.
        self._record_voice_user(text)
        self._govern_voice_command(text)
        threading.Thread(target=worker,daemon=True).start()

    def voice_state(self,state):
        # Voice callbacks arrive from a worker thread.  Ignore a final state
        # notification when the window has already begun closing.
        try:
            if self.winfo_exists():
                self.after(0, lambda: self._voice_state_ui(state))
        except (RuntimeError, tk.TclError):
            pass
    def _voice_state_ui(self,state):
        if hasattr(self,"voice_state_label"):
            try: self.voice_state_label.configure(text=state)
            except Exception: pass
        if hasattr(self,"voice_status"):
            try: self.voice_status.configure(text=state)
            except Exception: pass
        if hasattr(self,"voice_chip"):
            try:
                friendly = "Voice listening" if state in {"LISTENING", "CONNECTED", "UNDERSTANDING"} else ("Voice speaking" if state == "SPEAKING" else "Voice ready")
                self.voice_chip.configure(text=f"●  {friendly}", fg=GREEN if state in {"LISTENING", "CONNECTED", "UNDERSTANDING", "SPEAKING"} else MUTED)
            except Exception: pass
        if hasattr(self,"voice_connection_label"):
            try:
                live = state not in {"OFFLINE", "NOT READY"} and self.gemini_voice.running
                self.voice_connection_label.configure(text="  ● LIVE SESSION" if live else "  ○ SESSION OFFLINE", fg=GREEN if live else MUTED)
            except Exception: pass
        if hasattr(self,"voice_diag"):
            try: self.voice_diag.configure(text=self.voice_diagnostic_text())
            except Exception: pass

    def toggle_voice(self):
        if self.gemini_voice.running:
            self.gemini_voice.stop()
        else:
            self.start_selected_voice()
        if hasattr(self,"voice_prompt"):
            self.voice_prompt.configure(text=self.voice_prompt_text())

    def auto_voice_start(self):
        settings=self.provider_store.voice()
        if settings.get("auto_start",True) and settings.get("mode","smart") != "manual":
            if GEMINI_API_KEY or self.provider_store.get_key("Google Gemini"):
                self.start_selected_voice()

    def ask_brain(self):
        text=self.brain_input.get("1.0","end").strip()
        if not text: return
        self.brain_out.configure(text="Thinking…")
        def worker():
            try: ans=self.ollama.chat(text,system="You are AXON Brain. Be concise and useful.")
            except Exception as e: ans=f"Ollama error: {e}"
            self.after(0,lambda:self.brain_out.configure(text=ans))
        threading.Thread(target=worker,daemon=True).start()

    def analyze_domain(self,url):
        if not url: return
        self.security_out.configure(text="Running multi-source URL intelligence…", fg=AMBER)
        def worker():
            try:
                from .security_intel import deep_analyze_url
                cfg=self.integrations.settings.section("security_intel")
                result=deep_analyze_url(url, cfg)
            except Exception as exc:
                result=f"URL analysis failed: {exc}"
            self.after(0,lambda:self.security_out.configure(text=result, fg=RED if "MALICIOUS / PHISHING" in result else TEXT))
        threading.Thread(target=worker,daemon=True).start()

    def authorized_scan(self,target,ports):
        target=target.strip(); ports=ports.strip()
        if not self.auth.get():
            messagebox.showwarning("Authorization required","Confirm that you own or are explicitly authorized to test this target."); return
        if not target or any(ch.isspace() for ch in target) or any(ch in target for ch in ";&|$`<>\""):
            messagebox.showerror("Invalid target","Enter one hostname or IP address only. Shell operators are not accepted."); return
        if ports and not re.fullmatch(r"[0-9,\-]+", ports):
            messagebox.showerror("Invalid ports","Use only numeric ports, comma-separated lists, or ranges such as 1-1024."); return
        plan=ActionPlan("Authorized Nmap discovery", f"Run a controlled Nmap discovery against {target}", f"Ports: {ports or 'Nmap fast scan (-F)'}\nAuthorization checkbox: confirmed")
        if not self.confirm_action(plan):
            self.nmap_out.configure(text="Cancelled. No scan was performed.", fg=AMBER); return
        self.nmap_out.configure(text="Running authorized Nmap discovery…", fg=AMBER)
        def worker():
            try:
                import shutil as _shutil
                nmap=_shutil.which("nmap")
                if not nmap:
                    raise RuntimeError("nmap is not installed or is not on PATH.")
                cmd=[nmap,"-Pn","-sT","--open","-T3"]
                if ports: cmd += ["-p",ports]
                else: cmd += ["-F"]
                cmd += [target]
                proc=subprocess.run(cmd,capture_output=True,text=True,timeout=180,check=False)
                output=(proc.stdout or proc.stderr or "No Nmap output.").strip()
                status=f"NMAP EXIT CODE: {proc.returncode}\n\n{output}"
                self.after(0,lambda:self.nmap_out.configure(text=status, fg=GREEN if proc.returncode==0 else RED))
            except subprocess.TimeoutExpired:
                self.after(0,lambda:self.nmap_out.configure(text="Nmap timed out after 180 seconds.", fg=RED))
            except Exception as exc:
                self.after(0,lambda:self.nmap_out.configure(text=f"Nmap failed: {exc}", fg=RED))
        threading.Thread(target=worker,daemon=True).start()

    def _widget_alive(self, widget):
        try:
            return widget is not None and bool(widget.winfo_exists())
        except Exception:
            return False

    def refresh(self):
        try:
            s=system_status(); ok,models=self.ollama.status()
            if self._widget_alive(getattr(self, "cpu_label", None)):
                self.cpu_label.configure(text=f"{s['cpu']:.0f}%")
            if self._widget_alive(getattr(self, "ram_label", None)):
                self.ram_label.configure(text=f"{s['ram']:.0f}%")
            if self._widget_alive(getattr(self, "gpu_label", None)):
                try:
                    gpu = s.get('gpu', '--')
                    self.gpu_label.configure(text=str(gpu))
                except Exception:
                    pass
            imported=sum(len(self.provider_store.models(p)) for p in PROVIDERS)
            ready=sum(1 for p in PROVIDERS for m in self.provider_store.models(p) if m.get("health")=="READY")
            chat_ready=sum(1 for p in PROVIDERS if self.provider_store.health(p).get("status")=="CHAT READY")
            providers_with_catalog=sum(1 for p in PROVIDERS if self.provider_store.models(p))
            if chat_ready:
                connection = "Cloud connected"
            elif ready:
                connection = f"{ready} model{'s' if ready != 1 else ''} ready"
            elif ok and models:
                connection = "Local model ready"
            elif providers_with_catalog:
                connection = "Models need a quick check"
            else:
                connection = "Connect a model in Settings"
            voice = "Voice listening" if self.gemini_voice.running else "Voice ready"
            if self._widget_alive(getattr(self, "greeting_label", None)):
                self.greeting_label.configure(text=self.time_greeting())
            self.nav_status.configure(text=f"ASSISTANT STATUS\n{connection}\n{voice}")
            self.online.configure(text=f"● {connection}", fg=GREEN if chat_ready or ready or (ok and models) else AMBER)
            if self._widget_alive(getattr(self, "home_status", None)):
                self.home_status.label.configure(text=f"{connection}\n{voice}")
            if self._widget_alive(getattr(self, "home_goal", None)):
                goals=self.memory.active_goals(); self.home_goal.label.configure(text="\n".join("• "+g["text"] for g in goals) if goals else "No active goals.")
            if self._widget_alive(getattr(self, "home_mission", None)):
                ms=self.memory.active_missions(); self.home_mission.label.configure(text="\n".join("• "+m["text"] for m in ms) if ms else "No active missions.")
            if self._widget_alive(getattr(self, "model_box", None)):
                self.model_box.configure(text="\n".join(f"● {m}" for m in models) if ok and models else "Ollama is offline or no models are installed.")
            if self._widget_alive(getattr(self, "world_text", None)):
                self.world_text.configure(text=f"Host: {s['host']}\nPython: {s['python']}\nCPU: {s['cpu']:.1f}%\nRAM: {s['ram']:.1f}%\nDisk: {s['disk']:.1f}%\nOllama: {'READY' if ok else 'OFFLINE'}")
            if self._widget_alive(getattr(self, "observe_text", None)):
                self.observe_text.configure(text=f"LIVE TELEMETRY\n\nCPU     {s['cpu']:.1f}%\nRAM     {s['ram']:.1f}%\nDISK    {s['disk']:.1f}%\nOLLAMA  {'READY' if ok else 'OFFLINE'}\nVOICE   {'LISTENING' if self.gemini_voice.running else 'OFFLINE'}")
            self.render_goals(); self.render_missions(); self.render_experience()
            if self._widget_alive(getattr(self, "models_summary", None)):
                self.render_provider_models()
        except Exception:
            pass
        if self.winfo_exists(): self.after(1800,self.refresh)

    def render_experience(self):
        if self._widget_alive(getattr(self, "knowledge_text", None)):
            exp=self.memory.experience[-20:]
            self.knowledge_text.configure(text="\n\n".join(f"✓ {x['time']}  ·  {x['kind']}\n  {x['result']}" for x in reversed(exp)) or "No learned experience recorded yet.")

    def animate_voice(self):
        if not hasattr(self,"voice_canvas") or not self.voice_canvas.winfo_exists(): return
        c=self.voice_canvas; c.delete("all")
        w=max(c.winfo_width(),640); h=max(c.winfo_height(),470)
        cx=w*0.50; cy=h*0.51
        t=time.time()

        # Subtle nebula / star field, deterministic so the page feels calm rather than noisy.
        stars=[(0.05,0.15,1),(0.11,0.72,1),(0.18,0.30,2),(0.27,0.78,1),(0.34,0.16,1),
               (0.42,0.68,1),(0.52,0.12,1),(0.61,0.83,2),(0.70,0.26,1),(0.79,0.72,1),
               (0.89,0.16,1),(0.94,0.52,1),(0.08,0.48,1),(0.86,0.45,2),(0.56,0.55,1),
               (0.22,0.55,1),(0.75,0.48,1),(0.38,0.48,1),(0.66,0.60,1)]
        for i,(sx,sy,r) in enumerate(stars):
            tw=1.0+0.7*(0.5+0.5*math.sin(t*1.6+i*1.7))
            x=sx*w; y=sy*h
            c.create_oval(x-tw*r,y-tw*r,x+tw*r,y+tw*r,fill="#aab8e8",outline="")

        base=min(w,h)*0.045
        max_orbit=min(w,h)*0.36
        colors=[CYAN,"#60a5fa",PURPLE2,"#fbbf24","#fb7185","#34d399","#a78bfa","#c084fc","#38bdf8"]
        labels=["1 LISTENING","2 FILTERING","3 UNDERSTANDING","4 ROUTING","5 EXECUTING","6 GOVERNING","7 VERIFYING","8 RESPONDING","9 LEARNING"]
        speeds=[0.56,0.45,0.36,0.30,0.25,0.21,0.18,0.15,0.125]
        sizes=[6,7,7,8,8,7,7,8,7]

        # Nine planets + nine orbital tracks.
        for i in range(9):
            radius=base*2.4+(max_orbit-base*2.4)*(i/8)
            ry=radius*(0.78+0.015*math.sin(i))
            c.create_oval(cx-radius,cy-ry,cx+radius,cy+ry,outline="#252b5d",width=1)
            # Tiny orbital energy node
            node_ang=t*0.22+i*0.55
            nx=cx+radius*math.cos(node_ang); ny=cy+ry*math.sin(node_ang)
            c.create_oval(nx-1,ny-1,nx+1,ny+1,fill="#7c3aed",outline="")
            angle=t*speeds[i]+i*0.91
            x=cx+radius*math.cos(angle); y=cy+ry*math.sin(angle)
            pc=colors[i]
            ps=sizes[i]
            c.create_oval(x-ps*2.4,y-ps*2.4,x+ps*2.4,y+ps*2.4,fill="#07101e",outline=pc,width=1)
            c.create_oval(x-ps,y-ps,x+ps,y+ps,fill=pc,outline="")
            c.create_oval(x-ps*.38,y-ps*.58,x+ps*.22,y+ps*.04,fill="#eef7ff",outline="")
            # Labels stay near the outer half so they never cover the core.
            if i in (0,2,4,6,8):
                lx=x+(18 if math.cos(angle)>=0 else -18); ly=y-14
                anchor="w" if lx>x else "e"
                c.create_text(lx,ly,text=labels[i],anchor=anchor,fill=pc,font=("DejaVu Sans",7,"bold"))

        # Astral core / energy halo.
        pulse=(math.sin(t*2.1)+1)/2
        for mul,col in [(2.30,"#241a54"),(1.90,PURPLE),(1.52,CYAN)]:
            r=base*mul*(1+0.055*pulse)
            c.create_oval(cx-r,cy-r,cx+r,cy+r,outline=col,width=1)
        r=base*(1.02+0.11*pulse)
        c.create_oval(cx-r,cy-r,cx+r,cy+r,fill="#0c1630",outline=CYAN,width=2)
        r*=0.60
        c.create_oval(cx-r,cy-r,cx+r,cy+r,fill="#17244a",outline=PURPLE2,width=2)
        r*=0.48
        c.create_oval(cx-r,cy-r,cx+r,cy+r,fill="#f3f7ff",outline="")
        c.create_text(cx,cy,text="✦",fill="#ffffff",font=("DejaVu Sans",22,"bold"))

        # Small state marker inside the visualization.
        state="LIVE" if self.gemini_voice.running else "STANDBY"
        col=GREEN if self.gemini_voice.running else MUTED
        c.create_text(cx,cy+max(120,base*5.0),text=f"●  {state}",fill=col,font=("DejaVu Sans",8,"bold"))
        self.after(45,self.animate_voice)

    def shutdown(self):
        self._shutdown_started = True
        self._cancel_voice_jobs()
        try:
            self.gemini_voice.stop()
        except Exception:
            pass
        self.destroy()
