"""Explicitly invoked screenshot and camera capture helpers."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import shutil
import subprocess

from .actions import ActionResult
from .config import AXON_OUTPUT_DIR


def _capture_path(kind: str, suffix: str = ".png", output_dir: Path | None = None) -> Path:
    folder = (output_dir or AXON_OUTPUT_DIR).expanduser().resolve()
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{kind}-{datetime.now().strftime('%Y%m%d-%H%M%S')}{suffix}"


def take_screenshot(output_dir: Path | None = None) -> ActionResult:
    target = _capture_path("screenshot", output_dir=output_dir)
    commands = []
    if shutil.which("gnome-screenshot"):
        commands.append(["gnome-screenshot", "-f", str(target)])
    if shutil.which("scrot"):
        commands.append(["scrot", str(target)])
    if shutil.which("import"):
        commands.append(["import", "-window", "root", str(target)])
    for command in commands:
        try:
            completed = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
            if completed.returncode == 0 and target.is_file():
                return ActionResult.success(f"Screenshot saved to {target}.", path=str(target))
        except (OSError, subprocess.SubprocessError):
            continue
    return ActionResult.failure("No supported screenshot tool succeeded. Install gnome-screenshot, scrot, or ImageMagick.")


def take_window_screenshot(x: int, y: int, width: int, height: int, output_dir: Path | None = None) -> ActionResult:
    try:
        from PIL import ImageGrab
        target = _capture_path("window-screenshot", output_dir=output_dir)
        ImageGrab.grab(bbox=(int(x), int(y), int(x + width), int(y + height))).save(target)
        return ActionResult.success(f"Window screenshot saved to {target}.", path=str(target))
    except (ImportError, OSError, ValueError) as exc:
        return ActionResult.failure("AXON could not capture this window.", str(exc))


def take_camera_photo(output_dir: Path | None = None) -> ActionResult:
    try:
        import cv2
    except ImportError:
        return ActionResult.failure("Camera capture needs opencv-python. Install it before using the webcam.")
    target = _capture_path("camera", output_dir=output_dir)
    camera = cv2.VideoCapture(0)
    try:
        if not camera.isOpened():
            return ActionResult.failure("AXON could not open the camera.")
        ok, frame = camera.read()
        if not ok:
            return ActionResult.failure("AXON could not capture a camera frame.")
        if not cv2.imwrite(str(target), frame):
            return ActionResult.failure("AXON could not save the camera photo.")
    finally:
        camera.release()
    return ActionResult.success(f"Camera photo saved to {target}.", path=str(target))
