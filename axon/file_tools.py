"""Approved-path file analysis and non-destructive PDF operations."""
from __future__ import annotations

import csv
from datetime import datetime
import io
import mimetypes
from pathlib import Path
import re
import shutil
import subprocess
import zipfile

from .actions import ActionResult
from .config import AXON_OUTPUT_DIR, BASE


TEXT_SUFFIXES = {".txt", ".md", ".py", ".js", ".ts", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".log", ".csv", ".html", ".css", ".sh"}


class FileAccessPolicy:
    """Allows files below explicitly user-oriented roots and rejects broad targets."""

    def __init__(self, approved_roots: list[Path] | None = None):
        default = [Path.home() / name for name in ("Documents", "Downloads", "Desktop")]
        default.append(AXON_OUTPUT_DIR)
        self.approved_roots = [Path(p).expanduser().resolve() for p in (approved_roots or default)]

    @staticmethod
    def resolve(path: str | Path) -> Path:
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = Path.cwd() / candidate
        return candidate.resolve(strict=False)

    def is_allowed(self, path: str | Path) -> bool:
        candidate = self.resolve(path)
        return any(candidate == root or root in candidate.parents for root in self.approved_roots)

    def validate(self, path: str | Path, operation: str) -> ActionResult:
        candidate = self.resolve(path)
        broad = {Path("/").resolve(), Path.home().resolve(), BASE.resolve()}
        if candidate in broad:
            return ActionResult.failure("AXON will not operate on a broad system, home, or project directory.")
        check = candidate.parent if operation == "write" else candidate
        if not self.is_allowed(check):
            roots = ", ".join(str(root) for root in self.approved_roots)
            return ActionResult.failure(f"That path is outside your approved folders: {roots}", path=str(candidate))
        return ActionResult.success("Approved path.", path=str(candidate))


class FileService:
    def __init__(self, policy: FileAccessPolicy | None = None):
        self.policy = policy or FileAccessPolicy()

    def _approved_existing_file(self, path: str | Path) -> tuple[Path | None, ActionResult | None]:
        valid = self.policy.validate(path, "read")
        if not valid.ok:
            return None, valid
        file_path = Path(valid.data["path"])
        if not file_path.is_file():
            return None, ActionResult.failure("That path is not a readable file.", path=str(file_path))
        if file_path.stat().st_size > 25 * 1024 * 1024:
            return None, ActionResult.failure("AXON only analyzes files up to 25 MB.", path=str(file_path))
        return file_path, None

    def read_text(self, path: str | Path, limit: int = 30000) -> ActionResult:
        file_path, error = self._approved_existing_file(path)
        if error:
            return error
        if file_path.suffix.lower() not in TEXT_SUFFIXES:
            return ActionResult.failure("That is not a supported plain-text file. Use Analyze for a structured summary.")
        try:
            text = file_path.read_text(encoding="utf-8", errors="replace")[:limit]
        except OSError as exc:
            return ActionResult.failure("AXON could not read that file.", str(exc))
        return ActionResult.success(text or "The file is empty.", path=str(file_path), text=text)

    def analyze(self, path: str | Path) -> ActionResult:
        file_path, error = self._approved_existing_file(path)
        if error:
            return error
        stat = file_path.stat()
        kind = mimetypes.guess_type(file_path.name)[0] or "unknown"
        details = [f"File: {file_path.name}", f"Path: {file_path}", f"Type: {kind}", f"Size: {stat.st_size:,} bytes", f"Modified: {datetime.fromtimestamp(stat.st_mtime).isoformat(timespec='seconds')}"]
        suffix = file_path.suffix.lower()
        try:
            if suffix in TEXT_SUFFIXES:
                text = file_path.read_text(encoding="utf-8", errors="replace")
                details.extend([f"Characters: {len(text):,}", "\nPreview:\n" + text[:4000]])
            elif suffix == ".pdf":
                extracted = PdfService(self.policy).extract_text(file_path)
                if not extracted.ok:
                    return extracted
                details.append("\n" + extracted.message)
            elif suffix == ".docx":
                with zipfile.ZipFile(file_path) as archive:
                    xml = archive.read("word/document.xml").decode("utf-8", errors="replace")
                text = re.sub(r"<[^>]+>", " ", xml)
                details.extend(["DOCX text preview:", text[:4000]])
            elif suffix == ".csv":
                with file_path.open(newline="", encoding="utf-8", errors="replace") as handle:
                    rows = list(csv.reader(handle))
                details.extend([f"Rows: {len(rows):,}", f"Columns: {len(rows[0]) if rows else 0}"])
            elif kind.startswith("image/"):
                try:
                    from PIL import Image
                    with Image.open(file_path) as image:
                        details.append(f"Dimensions: {image.width} × {image.height}")
                except ImportError:
                    details.append("Install Pillow for image dimensions and previews.")
        except (OSError, ValueError, zipfile.BadZipFile) as exc:
            return ActionResult.failure("AXON could not analyze that file.", str(exc), path=str(file_path))
        return ActionResult.success("\n".join(details), path=str(file_path), file_type=kind)

    def write_text(self, path: str | Path, content: str, backup: bool = True) -> ActionResult:
        valid = self.policy.validate(path, "write")
        if not valid.ok:
            return valid
        target = Path(valid.data["path"])
        if target.exists() and target.is_dir():
            return ActionResult.failure("A directory cannot be replaced with a text file.")
        backup_path = None
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and backup:
                stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                backup_path = target.with_name(f"{target.name}.{stamp}.bak")
                shutil.copy2(target, backup_path)
            target.write_text(str(content), encoding="utf-8")
        except OSError as exc:
            return ActionResult.failure("AXON could not write that file.", str(exc), path=str(target))
        message = f"Wrote {target}."
        if backup_path:
            message += f" Backup: {backup_path}."
        return ActionResult.success(message, path=str(target), backup=str(backup_path) if backup_path else None)

    def open_file(self, path: str | Path) -> ActionResult:
        file_path, error = self._approved_existing_file(path)
        if error:
            return error
        if shutil.which("xdg-open") is None:
            return ActionResult.failure("xdg-open is not installed, so AXON cannot open files with the desktop.")
        try:
            subprocess.Popen(["xdg-open", str(file_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError as exc:
            return ActionResult.failure("AXON could not open that file.", str(exc))
        return ActionResult.success(f"Opened {file_path.name}.", path=str(file_path))

    def open_folder(self, path: str | Path) -> ActionResult:
        valid = self.policy.validate(path, "read")
        if not valid.ok:
            return valid
        folder = Path(valid.data["path"])
        if not folder.is_dir():
            return ActionResult.failure("That path is not a folder.")
        if shutil.which("xdg-open") is None:
            return ActionResult.failure("xdg-open is not installed, so AXON cannot open folders with the desktop.")
        try:
            subprocess.Popen(["xdg-open", str(folder)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError as exc:
            return ActionResult.failure("AXON could not open that folder.", str(exc))
        return ActionResult.success(f"Opened {folder}.", path=str(folder))


class PdfService:
    def __init__(self, policy: FileAccessPolicy | None = None):
        self.policy = policy or FileAccessPolicy()

    @staticmethod
    def _dependencies():
        try:
            from pypdf import PdfReader, PdfWriter
            return PdfReader, PdfWriter, None
        except ImportError:
            return None, None, "PDF tools need pypdf. Run: python -m pip install -r requirements.txt"

    def _source(self, path: str | Path) -> tuple[Path | None, ActionResult | None]:
        valid = self.policy.validate(path, "read")
        if not valid.ok:
            return None, valid
        source = Path(valid.data["path"])
        if not source.is_file() or source.suffix.lower() != ".pdf":
            return None, ActionResult.failure("Select an existing PDF inside an approved folder.")
        return source, None

    def _new_output(self, output: str | Path) -> tuple[Path | None, ActionResult | None]:
        valid = self.policy.validate(output, "write")
        if not valid.ok:
            return None, valid
        target = Path(valid.data["path"])
        if target.exists():
            return None, ActionResult.failure("Choose a new PDF output path; AXON does not overwrite originals.")
        target.parent.mkdir(parents=True, exist_ok=True)
        return target, None

    def extract_text(self, path: str | Path, limit: int = 12000) -> ActionResult:
        source, error = self._source(path)
        if error:
            return error
        PdfReader, _, dependency_error = self._dependencies()
        if dependency_error:
            return ActionResult.failure(dependency_error)
        try:
            reader = PdfReader(str(source))
            text = "\n".join((page.extract_text() or "") for page in reader.pages)
        except Exception as exc:
            return ActionResult.failure("AXON could not extract text from that PDF.", str(exc))
        return ActionResult.success(f"PDF pages: {len(reader.pages)}\n\n{text[:limit] or 'No extractable text found.'}", pages=len(reader.pages), text=text[:limit], path=str(source))

    def merge(self, paths: list[str | Path], output: str | Path) -> ActionResult:
        _, PdfWriter, dependency_error = self._dependencies()
        if dependency_error:
            return ActionResult.failure(dependency_error)
        target, error = self._new_output(output)
        if error:
            return error
        writer = PdfWriter()
        try:
            for path in paths:
                source, source_error = self._source(path)
                if source_error:
                    return source_error
                writer.append(str(source))
            with target.open("wb") as handle:
                writer.write(handle)
        except Exception as exc:
            return ActionResult.failure("AXON could not merge those PDFs.", str(exc))
        return ActionResult.success(f"Created merged PDF: {target}", path=str(target))

    def split(self, path: str | Path, output_dir: str | Path) -> ActionResult:
        source, error = self._source(path)
        if error:
            return error
        PdfReader, PdfWriter, dependency_error = self._dependencies()
        if dependency_error:
            return ActionResult.failure(dependency_error)
        valid = self.policy.validate(Path(output_dir) / "split-placeholder.pdf", "write")
        if not valid.ok:
            return valid
        folder = Path(output_dir).expanduser().resolve()
        folder.mkdir(parents=True, exist_ok=True)
        created = []
        try:
            reader = PdfReader(str(source))
            for index, page in enumerate(reader.pages, 1):
                target = folder / f"{source.stem}-page-{index}.pdf"
                if target.exists():
                    return ActionResult.failure(f"Refusing to overwrite {target}.")
                writer = PdfWriter(); writer.add_page(page)
                with target.open("wb") as handle:
                    writer.write(handle)
                created.append(str(target))
        except Exception as exc:
            return ActionResult.failure("AXON could not split that PDF.", str(exc))
        return ActionResult.success(f"Created {len(created)} PDF pages in {folder}.", paths=created)

    def rotate(self, path: str | Path, output: str | Path, degrees: int = 90, pages: list[int] | None = None) -> ActionResult:
        source, error = self._source(path)
        if error:
            return error
        PdfReader, PdfWriter, dependency_error = self._dependencies()
        if dependency_error:
            return ActionResult.failure(dependency_error)
        target, error = self._new_output(output)
        if error:
            return error
        if degrees not in {90, 180, 270, -90}:
            return ActionResult.failure("PDF rotation must be 90, 180, or 270 degrees.")
        try:
            reader, writer = PdfReader(str(source)), PdfWriter()
            chosen = set(pages or range(1, len(reader.pages) + 1))
            for index, page in enumerate(reader.pages, 1):
                if index in chosen:
                    page.rotate(degrees)
                writer.add_page(page)
            with target.open("wb") as handle:
                writer.write(handle)
        except Exception as exc:
            return ActionResult.failure("AXON could not rotate that PDF.", str(exc))
        return ActionResult.success(f"Created rotated PDF: {target}", path=str(target))

    def overlay_text(self, path: str | Path, output: str | Path, text: str, page_number: int = 1) -> ActionResult:
        source, error = self._source(path)
        if error:
            return error
        PdfReader, PdfWriter, dependency_error = self._dependencies()
        if dependency_error:
            return ActionResult.failure(dependency_error)
        target, error = self._new_output(output)
        if error:
            return error
        try:
            from reportlab.pdfgen import canvas
            reader, writer = PdfReader(str(source)), PdfWriter()
            if not 1 <= page_number <= len(reader.pages):
                return ActionResult.failure("Choose a valid PDF page number.")
            for index, page in enumerate(reader.pages, 1):
                if index == page_number:
                    packet = io.BytesIO()
                    width, height = float(page.mediabox.width), float(page.mediabox.height)
                    overlay = canvas.Canvas(packet, pagesize=(width, height))
                    overlay.drawString(36, 36, str(text)[:500])
                    overlay.save(); packet.seek(0)
                    page.merge_page(PdfReader(packet).pages[0])
                writer.add_page(page)
            with target.open("wb") as handle:
                writer.write(handle)
        except ImportError:
            return ActionResult.failure("PDF annotation needs reportlab. Run: python -m pip install -r requirements.txt")
        except Exception as exc:
            return ActionResult.failure("AXON could not annotate that PDF.", str(exc))
        return ActionResult.success(f"Created annotated PDF: {target}", path=str(target))

    def render_preview(self, path: str | Path, output_png: str | Path, page: int = 1) -> ActionResult:
        source, error = self._source(path)
        if error:
            return error
        target, error = self._new_output(output_png)
        if error:
            return error
        if shutil.which("pdftoppm") is None:
            return ActionResult.failure("PDF preview needs the pdftoppm utility (install poppler-utils).")
        try:
            subprocess.run(["pdftoppm", "-f", str(page), "-l", str(page), "-png", "-singlefile", str(source), str(target.with_suffix(""))], check=True, capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError) as exc:
            return ActionResult.failure("AXON could not create the PDF preview.", str(exc))
        return ActionResult.success(f"Created PDF preview: {target}", path=str(target))
