from pathlib import Path
import os
from dotenv import load_dotenv

BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "axon" / "data"
DATA.mkdir(parents=True, exist_ok=True)
load_dotenv(BASE / ".env")

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:1.5b")
WAKE_WORD = os.getenv("AXON_WAKE_WORD", "hey axon").lower()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_LIVE_MODEL = os.getenv("GEMINI_LIVE_MODEL", "gemini-3.1-flash-live-preview")
GEMINI_VOICE = os.getenv("GEMINI_VOICE", "Charon")
WEB_SEARCH_PROVIDER = os.getenv("WEB_SEARCH_PROVIDER", "brave").strip().lower()
WEB_SEARCH_API_KEY = os.getenv("WEB_SEARCH_API_KEY", "").strip()
OPENAI_IMAGE_MODEL = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-2").strip()
AXON_OUTPUT_DIR = Path(os.getenv("AXON_OUTPUT_DIR", str(DATA / "output"))).expanduser()
AXON_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

GOALS_FILE = DATA / "goals.json"
MISSIONS_FILE = DATA / "missions.json"
EXPERIENCE_FILE = DATA / "experience.json"
PROVIDERS_FILE = DATA / "providers.json"
PERSONAL_MEMORY_FILE = DATA / "personal_memory.json"
SECURITY_INTEL_FILE = Path.home() / ".config" / "axon" / "security_intel.json"

PROJECT_ROOT = Path(__file__).resolve().parents[1]
