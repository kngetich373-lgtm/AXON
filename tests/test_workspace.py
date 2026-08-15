import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from axon.actions import ActionResult
from axon.file_tools import FileAccessPolicy, FileService
from axon.intents import parse_intent
from axon.memory import Memory
from axon.router import CommandRouter
from axon.workspace import TerminalService, build_map_url, build_youtube_music_url


class _DecliningUI:
    def __init__(self):
        self.plans = []

    def confirm_action(self, plan):
        self.plans.append(plan)
        return False


class WorkspaceTests(unittest.TestCase):
    def memory(self, directory):
        root = Path(directory)
        patches = [
            patch("axon.memory.GOALS_FILE", root / "goals.json"),
            patch("axon.memory.MISSIONS_FILE", root / "missions.json"),
            patch("axon.memory.EXPERIENCE_FILE", root / "experience.json"),
            patch("axon.memory.PERSONAL_MEMORY_FILE", root / "personal.json"),
        ]
        for item in patches:
            item.start()
        self.addCleanup(lambda: [item.stop() for item in reversed(patches)])
        return Memory()

    def test_intents_cover_maps_music_aliases_and_capture(self):
        self.assertEqual(parse_intent("open a satellite map of the world").args["place"], "the world")
        self.assertEqual(parse_intent("show Kenya on satellite").args["place"], "Kenya")
        self.assertEqual(parse_intent("open Emurua Dikirr, Narok, Kenya in satellite view").args["place"], "Emurua Dikirr, Narok, Kenya")
        self.assertEqual(parse_intent("play Sauti Sol on YouTube Music").name, "youtube_music")
        self.assertEqual(parse_intent("remember open john means open John the Ripper").name, "remember_alias")
        self.assertEqual(parse_intent("take a screenshot").name, "screenshot")

    def test_url_builders_encode_places_and_music_queries(self):
        map_url = build_map_url("Emurua Dikirr, Narok, Kenya", satellite=True)
        self.assertIn("Emurua+Dikirr%2C+Narok%2C+Kenya", map_url)
        self.assertIn("basemap=satellite", map_url)
        self.assertIn("data=!3m1!1e3", build_map_url("world", satellite=True))
        self.assertEqual(build_youtube_music_url("Sauti Sol"), "https://music.youtube.com/search?q=Sauti+Sol")

    def test_personal_memory_persists_alias_and_rejects_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            memory = self.memory(directory)
            ok, _ = memory.remember_alias("john", "john")
            self.assertTrue(ok)
            self.assertEqual(memory.alias("john"), "john")
            secret_ok, message = memory.remember_fact("api key", "abc")
            self.assertFalse(secret_ok)
            self.assertIn("does not store", message)
            self.assertTrue(memory.forget("john")[0])
            self.assertIsNone(memory.alias("john"))

    def test_file_policy_restricts_paths_and_write_makes_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "approved"
            root.mkdir()
            policy = FileAccessPolicy([root])
            service = FileService(policy)
            outside = Path(directory) / "outside.txt"
            self.assertFalse(policy.validate(outside, "write").ok)
            target = root / "notes.txt"
            self.assertTrue(service.write_text(target, "one").ok)
            result = service.write_text(target, "two")
            self.assertTrue(result.ok)
            self.assertIsNotNone(result.data["backup"])
            self.assertEqual(target.read_text(), "two")

    def test_terminal_rejects_destructive_and_shell_chained_commands(self):
        self.assertFalse(TerminalService.validate("rm -rf /").ok)
        self.assertFalse(TerminalService.validate("echo hello | tee notes.txt").ok)
        self.assertFalse(TerminalService.validate("nmap example.com").ok)
        self.assertTrue(TerminalService.validate("ip a").ok)

    @patch("axon.workspace.shutil.which", return_value="/usr/bin/echo")
    @patch("axon.workspace.subprocess.run")
    def test_terminal_invokes_subprocess_without_a_shell(self, run, _which):
        run.return_value = subprocess.CompletedProcess(["echo", "hello"], 0, "hello\n", "")
        with patch("axon.workspace.os.geteuid", return_value=1000):
            result = TerminalService().run("echo hello")
        self.assertTrue(result.ok)
        self.assertEqual(run.call_args.args[0], ["echo", "hello"])
        self.assertNotIn("shell", run.call_args.kwargs)

    def test_router_requires_confirmation_before_running_command(self):
        with tempfile.TemporaryDirectory() as directory:
            router = CommandRouter(None, self.memory(directory))
            ui = _DecliningUI()
            result = router.route("run ip a", ui)
            self.assertIsInstance(result, ActionResult)
            self.assertFalse(result.ok)
            self.assertEqual(len(ui.plans), 1)
            self.assertIn("ip a", ui.plans[0].summary)

