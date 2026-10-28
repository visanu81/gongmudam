"""Windows native file and folder pickers with a visible Tk owner window."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Literal


PickerKind = Literal["folder", "file"]
PICKER_TIMEOUT_SECONDS = 120


def choose_paths(kind: PickerKind) -> list[str]:
    """Open a native picker in a dedicated visible process and return paths."""
    if kind not in ("folder", "file"):
        raise ValueError("kind must be 'folder' or 'file'")

    base_executable = getattr(sys, "_base_executable", None)
    executable = base_executable if base_executable and os.path.isfile(base_executable) else sys.executable
    startupinfo = None
    creationflags = 0
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 1
        creationflags = subprocess.CREATE_NO_WINDOW

    try:
        completed = subprocess.run(
            [executable, str(Path(__file__).resolve()), "--child", kind],
            capture_output=True,
            text=True,
            timeout=PICKER_TIMEOUT_SECONDS,
            startupinfo=startupinfo,
            creationflags=creationflags,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError("파일/폴더 선택 창이 시간 초과로 종료되었습니다.") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(f"파일/폴더 선택 창을 열지 못했습니다: {detail}")
    try:
        payload = json.loads(completed.stdout)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("파일/폴더 선택 창이 올바른 결과를 반환하지 않았습니다.") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("paths"), list) or not all(
        isinstance(path, str) for path in payload["paths"]
    ):
        raise ValueError("파일/폴더 선택 창이 올바른 경로 목록을 반환하지 않았습니다.")
    return payload["paths"]


def _run_child(kind: PickerKind) -> list[str]:
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    try:
        root.title("공무담 자료 선택")
        root.geometry("420x120")
        root.resizable(False, False)
        root.attributes("-topmost", True)
        tk.Label(root, text="자료 선택 창을 준비했습니다. 원하는 항목을 선택해 주세요.").pack(
            padx=18, pady=24
        )
        root.update_idletasks()
        width, height = 420, 120
        x = (root.winfo_screenwidth() - width) // 2
        y = (root.winfo_screenheight() - height) // 2
        root.geometry(f"{width}x{height}+{x}+{y}")
        root.lift()
        root.update()
        if kind == "folder":
            selected = filedialog.askdirectory(
                parent=root,
                title="공무담 자료 폴더 선택",
                mustexist=True,
                initialdir=str(Path.home()),
            )
            return [selected] if selected else []
        if kind == "file":
            selected = filedialog.askopenfilenames(
                parent=root,
                title="공무담 자료 파일 선택",
                initialdir=str(Path.home()),
                filetypes=[
                    ("지원 자료", "*.txt *.md *.csv *.pdf *.xlsx *.docx *.hwpx"),
                    ("모든 파일", "*.*"),
                ],
            )
            return list(selected)
        raise ValueError("kind must be 'folder' or 'file'")
    finally:
        root.destroy()


def _main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2 or args[0] != "--child" or args[1] not in ("folder", "file"):
        return 2
    try:
        paths = _run_child(args[1])
        print(json.dumps({"paths": paths}, ensure_ascii=True))
        return 0
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(_main())
