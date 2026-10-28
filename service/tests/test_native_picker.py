from __future__ import annotations

import subprocess
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

import app.native_picker as native_picker


class NativePickerTests(unittest.TestCase):
    def test_invokes_module_with_base_interpreter_and_parses_paths(self):
        completed = subprocess.CompletedProcess([], 0, '{"paths":["C:/자료"]}', "")
        with mock.patch.object(native_picker.sys, "_base_executable", sys.executable), mock.patch.object(
            native_picker.subprocess, "run", return_value=completed
        ) as run:
            self.assertEqual(native_picker.choose_paths("folder"), ["C:/자료"])
        args = run.call_args.args[0]
        self.assertEqual(args[0], sys.executable)
        self.assertEqual(args[1], str(Path(native_picker.__file__).resolve()))
        self.assertEqual(args[2:], ["--child", "folder"])
        self.assertEqual(run.call_args.kwargs["timeout"], 120)
        self.assertTrue(run.call_args.kwargs["capture_output"])

    def test_timeout_is_reported(self):
        with mock.patch.object(native_picker.subprocess, "run", side_effect=subprocess.TimeoutExpired("picker", 120)):
            with self.assertRaisesRegex(TimeoutError, "시간 초과"):
                native_picker.choose_paths("file")

    def test_nonzero_and_invalid_json_are_reported(self):
        with mock.patch.object(
            native_picker.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 1, "", "picker failed"),
        ):
            with self.assertRaisesRegex(RuntimeError, "picker failed"):
                native_picker.choose_paths("file")
        with mock.patch.object(
            native_picker.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 0, "not json", ""),
        ):
            with self.assertRaisesRegex(ValueError, "올바른 결과"):
                native_picker.choose_paths("folder")

    def test_child_cancel_returns_empty_and_destroys_owner(self):
        root = _FakeRoot()
        fake_tk = types.ModuleType("tkinter")
        fake_tk.Tk = lambda: root
        fake_tk.Label = lambda *args, **kwargs: _FakeLabel()
        dialogs = types.ModuleType("tkinter.filedialog")
        dialogs.askdirectory = mock.Mock(return_value="")
        fake_tk.filedialog = dialogs
        with mock.patch.dict(sys.modules, {"tkinter": fake_tk, "tkinter.filedialog": dialogs}):
            self.assertEqual(native_picker._run_child("folder"), [])
        dialogs.askdirectory.assert_called_once()
        self.assertTrue(root.destroyed)
        self.assertTrue(root.updated)
        self.assertEqual(root.title_text, "공무담 자료 선택")

    def test_child_destroys_owner_when_dialog_raises(self):
        root = _FakeRoot()
        fake_tk = types.ModuleType("tkinter")
        fake_tk.Tk = lambda: root
        fake_tk.Label = lambda *args, **kwargs: _FakeLabel()
        dialogs = types.ModuleType("tkinter.filedialog")
        dialogs.askopenfilenames = mock.Mock(side_effect=OSError("dialog error"))
        fake_tk.filedialog = dialogs
        with mock.patch.dict(sys.modules, {"tkinter": fake_tk, "tkinter.filedialog": dialogs}):
            with self.assertRaisesRegex(OSError, "dialog error"):
                native_picker._run_child("file")
        self.assertTrue(root.destroyed)

    def test_child_file_selection_returns_all_paths_and_destroys_owner(self):
        root = _FakeRoot()
        fake_tk = types.ModuleType("tkinter")
        fake_tk.Tk = lambda: root
        fake_tk.Label = lambda *args, **kwargs: _FakeLabel()
        dialogs = types.ModuleType("tkinter.filedialog")
        dialogs.askopenfilenames = mock.Mock(return_value=("C:/a.pdf", "C:/b.xlsx"))
        fake_tk.filedialog = dialogs
        with mock.patch.dict(sys.modules, {"tkinter": fake_tk, "tkinter.filedialog": dialogs}):
            self.assertEqual(native_picker._run_child("file"), ["C:/a.pdf", "C:/b.xlsx"])
        self.assertTrue(root.destroyed)

    @unittest.skipUnless(native_picker.os.name == "nt", "Windows startup flags only")
    def test_windows_process_has_visible_startup_flags(self):
        completed = subprocess.CompletedProcess([], 0, '{"paths":[]}', "")
        with mock.patch.object(native_picker.subprocess, "run", return_value=completed) as run:
            native_picker.choose_paths("folder")
        startupinfo = run.call_args.kwargs["startupinfo"]
        self.assertTrue(startupinfo.dwFlags & subprocess.STARTF_USESHOWWINDOW)
        self.assertEqual(startupinfo.wShowWindow, 1)


class _FakeLabel:
    def pack(self, **kwargs):
        pass


class _FakeRoot:
    destroyed = False
    updated = False
    title_text = ""

    def title(self, value):
        self.title_text = value

    def geometry(self, value):
        pass

    def resizable(self, *args):
        pass

    def attributes(self, *args):
        pass

    def update_idletasks(self):
        pass

    def winfo_screenwidth(self):
        return 1920

    def winfo_screenheight(self):
        return 1080

    def lift(self):
        pass

    def update(self):
        self.updated = True

    def destroy(self):
        self.destroyed = True


if __name__ == "__main__":
    unittest.main()
