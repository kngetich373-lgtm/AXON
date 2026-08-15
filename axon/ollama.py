import requests
from .config import OLLAMA_URL, OLLAMA_MODEL

class OllamaClient:
    def __init__(self):
        self.url = OLLAMA_URL
        self.model = OLLAMA_MODEL

    def status(self):
        try:
            r = requests.get(self.url + "/api/tags", timeout=1.5)
            r.raise_for_status()
            data = r.json()
            models = [m.get("name") for m in data.get("models", [])]
            return True, models
        except Exception as e:
            return False, [str(e)]

    def chat(self, prompt, system=None):
        payload = {
            "model": self.model,
            "prompt": (system + "\n\n" if system else "") + prompt,
            "stream": False,
            "options": {"temperature": 0.2},
        }
        r = requests.post(self.url + "/api/generate", json=payload, timeout=45)
        r.raise_for_status()
        return r.json().get("response", "").strip()
