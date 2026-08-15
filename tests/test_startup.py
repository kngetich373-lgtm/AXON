import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]


class StartupTests(unittest.TestCase):
    def test_run_script_falls_back_cleanly_when_venv_is_absent(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            shutil.copy(PROJECT / "run.sh", work / "run.sh")
            (work / "main.py").write_text("print('fallback-python-ok')\n")
            result = subprocess.run(
                ["bash", "run.sh"], cwd=work, text=True,
                capture_output=True, timeout=15,
            )
            output = result.stdout + result.stderr
            self.assertNotIn("venv/bin/activate", output)
            self.assertIn(result.returncode, (0, 1))
            if result.returncode == 0:
                self.assertIn("fallback-python-ok", output)
            else:
                self.assertIn("AXON dependencies are missing", output)

    def test_headless_entry_point_exits_with_instructions(self):
        environment = os.environ.copy()
        environment.pop("DISPLAY", None)
        environment.pop("WAYLAND_DISPLAY", None)
        result = subprocess.run(
            [os.environ.get("PYTHON", "python3"), "main.py"], cwd=PROJECT,
            text=True, capture_output=True, env=environment, timeout=15,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("needs a graphical session", result.stderr)
        self.assertIn("./run.sh", result.stderr)

