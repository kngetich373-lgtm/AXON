import os
import tkinter as tk
import unittest

from axon.app import AXONApp


class VoiceLifecycleTests(unittest.TestCase):
    def test_voice_callback_after_navigation_does_not_touch_destroyed_widget(self):
        if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
            self.skipTest("Tk lifecycle regression requires a graphical display")
        try:
            root = tk.Tk()
        except tk.TclError:
            self.skipTest("Tk display is unavailable")
        root.withdraw()
        try:
            app = AXONApp.__new__(AXONApp)
            app._shutdown_started = False
            app.current_page = "Home"
            app.voice_diag = tk.Label(root, text="diagnostic")
            app.voice_diag.pack()
            app._voice_append_transcript = lambda *args: None
            app._add_message = lambda *args: None
            app.voice_diagnostic_text = lambda: "diagnostic"

            app.voice_diag.destroy()  # simulate navigating away from Voice

            # This used to raise: TclError: invalid command name ...label2
            app._record_voice_assistant("hello")
        finally:
            root.destroy()
