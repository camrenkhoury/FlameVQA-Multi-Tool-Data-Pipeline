import contextlib
import importlib.util
import io
import os
import queue
import shutil
import subprocess
import sys
import threading
import traceback
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageDraw, ImageOps, ImageTk


SCRIPT_DIR = Path(__file__).resolve().parent
SORTER_PATH = SCRIPT_DIR / "Raw File Sorting.py"


def load_sorter_module():
    spec = importlib.util.spec_from_file_location("raw_file_sorting_module", SORTER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sorter = load_sorter_module()


class QueueWriter(io.TextIOBase):
    def __init__(self, output_queue):
        self.output_queue = output_queue

    def write(self, text):
        if text:
            self.output_queue.put(("log", text))
        return len(text)

    def flush(self):
        return None


class PairPreviewWindow:
    def __init__(self, parent, sorter_module, burn_set, initial_index=0):
        self.sorter = sorter_module
        self.burn_set = burn_set
        self.all_pairs = burn_set["pairs"]
        self.filtered_indices = list(range(len(self.all_pairs)))
        self.current_filtered_pos = 0
        self.images = {}
        self.source_images = {}

        self.window = tk.Toplevel(parent)
        self.window.title(f"Output Viewer - {burn_set['name']}")
        self.window.geometry("1680x920")
        self.window.bind("<Left>", self._show_previous_pair)
        self.window.bind("<Right>", self._show_next_pair)

        outer = ttk.Frame(self.window, padding=12)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.columnconfigure(1, weight=4)
        outer.rowconfigure(2, weight=1)

        ttk.Label(
            outer,
            text=f"Output Viewer: {burn_set['name']}",
            font=("Segoe UI", 13, "bold"),
        ).grid(row=0, column=0, columnspan=2, sticky="w")

        ttk.Label(
            outer,
            text="Search or click a matched pair on the left. Use the arrow buttons or keyboard left/right keys to move through the output.",
            wraplength=1250,
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 10))

        sidebar = ttk.Frame(outer)
        sidebar.grid(row=2, column=0, sticky="nsew", padx=(0, 10))
        sidebar.columnconfigure(0, weight=1)
        sidebar.rowconfigure(2, weight=1)

        preview_area = ttk.Frame(outer)
        preview_area.grid(row=2, column=1, sticky="nsew")
        preview_area.columnconfigure(0, weight=1)
        preview_area.columnconfigure(1, weight=1)
        preview_area.rowconfigure(2, weight=1)
        preview_area.rowconfigure(5, weight=1)

        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", self._apply_filter)
        ttk.Label(sidebar, text="Search Matched Pairs", font=("Segoe UI", 10, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Entry(sidebar, textvariable=self.search_var).grid(row=1, column=0, sticky="ew", pady=(6, 10))

        self.pair_tree = ttk.Treeview(
            sidebar,
            columns=("pair", "rgb", "thermal"),
            show="headings",
            height=24,
        )
        for key, label, width in [
            ("pair", "#", 50),
            ("rgb", "RGB", 120),
            ("thermal", "Thermal", 120),
        ]:
            self.pair_tree.heading(key, text=label)
            self.pair_tree.column(key, width=width, anchor="center")
        self.pair_tree.grid(row=2, column=0, sticky="nsew")
        self.pair_tree.bind("<<TreeviewSelect>>", self._handle_pair_tree_selection)

        nav = ttk.Frame(sidebar)
        nav.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        nav.columnconfigure(0, weight=1)
        nav.columnconfigure(1, weight=1)
        self.prev_button = ttk.Button(nav, text="Previous", command=self._show_previous_pair)
        self.prev_button.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.next_button = ttk.Button(nav, text="Next", command=self._show_next_pair)
        self.next_button.grid(row=0, column=1, sticky="ew", padx=(6, 0))

        self.position_label = ttk.Label(sidebar, text="")
        self.position_label.grid(row=4, column=0, sticky="w", pady=(8, 0))

        self.corrected_canvas = tk.Canvas(preview_area, background="#1f1f1f", highlightthickness=0)
        self.corrected_canvas.grid(row=2, column=0, sticky="nsew", padx=(0, 8), pady=(10, 8))
        self.thermal_canvas = tk.Canvas(preview_area, background="#1f1f1f", highlightthickness=0)
        self.thermal_canvas.grid(row=2, column=1, sticky="nsew", padx=(8, 0), pady=(10, 8))
        self.raw_overlay_canvas = tk.Canvas(preview_area, background="#1f1f1f", highlightthickness=0)
        self.raw_overlay_canvas.grid(row=5, column=0, sticky="nsew", padx=(0, 8), pady=(10, 8))
        self.compare_canvas = tk.Canvas(preview_area, background="#1f1f1f", highlightthickness=0)
        self.compare_canvas.grid(row=5, column=1, sticky="nsew", padx=(8, 0), pady=(10, 8))
        self.corrected_canvas.bind("<Configure>", self._handle_resize)
        self.thermal_canvas.bind("<Configure>", self._handle_resize)
        self.raw_overlay_canvas.bind("<Configure>", self._handle_resize)
        self.compare_canvas.bind("<Configure>", self._handle_resize)

        ttk.Label(preview_area, text="Corrected FOV", font=("Segoe UI", 10, "bold")).grid(row=3, column=0, sticky="w")
        ttk.Label(preview_area, text="Thermal", font=("Segoe UI", 10, "bold")).grid(row=3, column=1, sticky="w")

        actions = ttk.LabelFrame(preview_area, text="Viewer Actions", padding=8)
        actions.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(10, 10))
        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=1)
        self.open_raw_button = ttk.Button(actions, text="Open Matching Raw RGB", command=self._open_matching_raw_rgb)
        self.open_raw_button.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.open_output_button = ttk.Button(actions, text="Open Output Folder", command=self._open_output_folder)
        self.open_output_button.grid(row=0, column=1, sticky="ew", padx=(8, 0))

        ttk.Label(preview_area, text="Raw RGB with Crop Outline", font=("Segoe UI", 10, "bold")).grid(row=6, column=0, sticky="w")
        ttk.Label(preview_area, text="Raw vs Corrected FOV", font=("Segoe UI", 10, "bold")).grid(row=6, column=1, sticky="w")

        self._populate_pair_tree()
        if self.filtered_indices:
            initial_index = max(0, min(initial_index, len(self.filtered_indices) - 1))
            self.current_filtered_pos = initial_index
            self._select_current_pair_in_tree()
            self._show_current_pair()

    def _render_preview_image(self, pil_image, max_size):
        image = pil_image.copy()
        image.thumbnail(max_size)
        return ImageTk.PhotoImage(image)

    def _draw_canvas_image(self, canvas, image_key):
        if image_key not in self.source_images:
            canvas.delete("all")
            return

        width = max(canvas.winfo_width(), 50)
        height = max(canvas.winfo_height(), 50)
        fitted = self._render_preview_image(
            self.source_images[image_key],
            (max(width - 16, 32), max(height - 16, 32)),
        )
        self.images[image_key] = fitted
        canvas.delete("all")
        canvas.create_image(width // 2, height // 2, image=fitted, anchor="center")

    def _refresh_canvases(self):
        self._draw_canvas_image(self.corrected_canvas, "corrected")
        self._draw_canvas_image(self.thermal_canvas, "thermal")
        self._draw_canvas_image(self.raw_overlay_canvas, "raw_overlay")
        self._draw_canvas_image(self.compare_canvas, "compare")

    def _handle_resize(self, event=None):
        if self.source_images:
            self._refresh_canvases()

    def _populate_pair_tree(self):
        self.pair_tree.delete(*self.pair_tree.get_children())
        for filtered_pos, pair_index in enumerate(self.filtered_indices):
            pair = self.all_pairs[pair_index]
            self.pair_tree.insert(
                "",
                "end",
                iid=str(filtered_pos),
                values=(
                    pair_index + 1,
                    Path(pair["rgb"]["filename"]).name,
                    Path(pair["thermal_jpg"]["filename"]).name if pair["thermal_jpg"] else Path(pair["thermal_tiff"]["filename"]).name,
                ),
            )

    def _apply_filter(self, *args):
        query = self.search_var.get().strip().lower()
        self.filtered_indices = []
        for index, pair in enumerate(self.all_pairs):
            rgb_name = Path(pair["rgb"]["filename"]).name.lower()
            thermal_name = (
                Path(pair["thermal_jpg"]["filename"]).name.lower()
                if pair["thermal_jpg"] is not None
                else Path(pair["thermal_tiff"]["filename"]).name.lower()
            )
            pair_label = str(index + 1)
            if not query or query in rgb_name or query in thermal_name or query in pair_label:
                self.filtered_indices.append(index)

        self.current_filtered_pos = 0
        self._populate_pair_tree()
        if self.filtered_indices:
            self._select_current_pair_in_tree()
            self._show_current_pair()
        else:
            self.position_label.configure(text="No matched pairs found for this search.")
            self.corrected_canvas.delete("all")
            self.thermal_canvas.delete("all")
            self.raw_overlay_canvas.delete("all")
            self.compare_canvas.delete("all")

    def _select_current_pair_in_tree(self):
        if not self.filtered_indices:
            return
        iid = str(self.current_filtered_pos)
        self.pair_tree.selection_set(iid)
        self.pair_tree.see(iid)

    def _handle_pair_tree_selection(self, event=None):
        selection = self.pair_tree.selection()
        if not selection:
            return
        self.current_filtered_pos = int(selection[0])
        self._show_current_pair()

    def _show_current_pair(self):
        if not self.filtered_indices:
            return

        pair_index = self.filtered_indices[self.current_filtered_pos]
        pair = self.all_pairs[pair_index]
        self.current_pair = pair

        corrected = self._load_preview_image(pair["rgb"]["filepath"], mode="rgb_corrected")
        thermal_source = (
            pair["thermal_jpg"]["filepath"]
            if pair["thermal_jpg"] is not None
            else pair["cal_tiff"]["filepath"] if pair["cal_tiff"] is not None else pair["thermal_tiff"]["filepath"]
        )
        thermal = self._load_preview_image(thermal_source, mode="thermal")
        raw_overlay = self._build_raw_overlay_image(pair["rgb"]["filepath"])
        compare_image = self._build_compare_image(pair["rgb"]["filepath"])

        self.source_images["corrected"] = corrected
        self.source_images["thermal"] = thermal
        self.source_images["raw_overlay"] = raw_overlay
        self.source_images["compare"] = compare_image
        self._refresh_canvases()

        self.position_label.configure(
            text=f"Viewing pair {pair_index + 1} of {len(self.all_pairs)}"
        )

    def _show_previous_pair(self, event=None):
        if not self.filtered_indices:
            return
        self.current_filtered_pos = (self.current_filtered_pos - 1) % len(self.filtered_indices)
        self._select_current_pair_in_tree()
        self._show_current_pair()

    def _show_next_pair(self, event=None):
        if not self.filtered_indices:
            return
        self.current_filtered_pos = (self.current_filtered_pos + 1) % len(self.filtered_indices)
        self._select_current_pair_in_tree()
        self._show_current_pair()

    def _load_preview_image(self, path, mode="rgb"):
        img = Image.open(path)
        if mode == "rgb_corrected":
            corrected = self.sorter._apply_rgb_fov_correction(path)
            if corrected.mode not in ("RGB", "RGBA"):
                corrected = corrected.convert("RGB")
            img.close()
            return corrected

        if img.mode not in ("RGB", "RGBA"):
            img = ImageOps.autocontrast(img.convert("L")).convert("RGB")
        else:
            img = img.convert("RGB")
        return img

    def _get_crop_box(self, raw_image):
        if self.sorter.CAMERA_USED == "M30T":
            return (
                640 + 40 - 60,
                412 + 30 + 12,
                4000 - 640 - 40 - 40 - 40 - 16 - 16 + 40,
                3000 - 412 - 30 - 30 - 30 - 12,
            )
        if self.sorter.CAMERA_USED == "M2EA":
            return (1280 + 80, 824, 8000 - 1280 + 80, 6000 - 824)
        return (0, 0, raw_image.width, raw_image.height)

    def _build_raw_overlay_image(self, raw_path):
        raw = self._load_preview_image(raw_path, mode="rgb")
        overlay = raw.copy()
        draw = ImageDraw.Draw(overlay)
        crop_box = self._get_crop_box(raw)
        draw.rectangle(crop_box, outline=(255, 80, 80), width=max(4, raw.width // 400))
        return overlay

    def _build_compare_image(self, raw_path):
        raw = self._load_preview_image(raw_path, mode="rgb")
        corrected = self._load_preview_image(raw_path, mode="rgb_corrected")
        canvas_width = max(raw.width, corrected.width)
        canvas_height = raw.height + corrected.height
        combined = Image.new("RGB", (canvas_width, canvas_height), color=(18, 18, 18))
        combined.paste(raw, (0, 0))
        combined.paste(corrected, (0, raw.height))
        draw = ImageDraw.Draw(combined)
        draw.text((16, 16), "Raw RGB", fill=(255, 255, 255))
        draw.text((16, raw.height + 16), "Corrected FOV", fill=(255, 255, 255))
        return combined

    def _open_matching_raw_rgb(self):
        if not hasattr(self, "current_pair"):
            return
        self._open_path(self.current_pair["rgb"]["filepath"])

    def _open_output_folder(self):
        self._open_path(self.burn_set["source_root"])

    def _open_path(self, path):
        try:
            if os.name == "nt":
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as exc:
            messagebox.showerror("Open failed", f"Could not open:\n{path}\n\n{exc}")


class RawSortingGui:
    def __init__(self, root):
        self.root = root
        self.root.title("FLAME Raw File Sorting Assistant")
        self.root.geometry("1680x980")

        self.input_var = tk.StringVar(value=str(SCRIPT_DIR / "Input Folder"))
        self.output_var = tk.StringVar(value=str(SCRIPT_DIR / "Output Folder"))
        self.mode_var = tk.StringVar(value="PRESORTED_STANDARD")
        self.camera_var = tk.StringVar(value="M30T")
        self.status_var = tk.StringVar(
            value="Set folders, then run the sort. After a successful run, Check Results becomes available."
        )
        self.progress_var = tk.DoubleVar(value=0.0)
        self.progress_label_var = tk.StringVar(value="Progress: idle")
        self.summary_var = tk.StringVar(value="No results loaded yet.")

        self.analysis = []
        self.selected_burn_set = None
        self.selected_pair = None
        self.output_queue = queue.Queue()
        self.preview_images = {}
        self.results_ready = False

        self._build_ui()
        self._sync_existing_results_state()
        self.root.after(100, self._poll_output_queue)

    def _build_ui(self):
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(2, weight=1)

        header = ttk.Frame(self.root, padding=12)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)

        ttk.Label(
            header,
            text="FLAME Raw File Sorting Assistant",
            font=("Segoe UI", 16, "bold"),
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            header,
            text=(
                "Run the sort to build the FLAME labeling-tool folder structure. "
                "After sorting finishes, use Check Results to inspect detected burn sets, pair counts, and image matches."
            ),
            wraplength=1280,
        ).grid(row=1, column=0, sticky="w", pady=(6, 0))

        controls = ttk.LabelFrame(self.root, text="Setup", padding=12)
        controls.grid(row=1, column=0, sticky="ew", padx=12)
        for index in range(8):
            controls.columnconfigure(index, weight=1 if index in (1, 5) else 0)

        ttk.Label(controls, text="Input Folder").grid(row=0, column=0, sticky="w")
        ttk.Entry(controls, textvariable=self.input_var).grid(row=0, column=1, columnspan=3, sticky="ew", padx=(8, 8))
        ttk.Button(controls, text="Browse", command=self._browse_input).grid(row=0, column=4, sticky="ew")

        ttk.Label(controls, text="Output Folder").grid(row=0, column=5, sticky="w", padx=(16, 0))
        ttk.Entry(controls, textvariable=self.output_var).grid(row=0, column=6, sticky="ew", padx=(8, 8))
        ttk.Button(controls, text="Browse", command=self._browse_output).grid(row=0, column=7, sticky="ew")

        ttk.Label(controls, text="Mode").grid(row=1, column=0, sticky="w", pady=(10, 0))
        mode_combo = ttk.Combobox(
            controls,
            textvariable=self.mode_var,
            values=["PRESORTED_STANDARD", "DJI_RAW"],
            state="readonly",
            width=22,
        )
        mode_combo.grid(row=1, column=1, sticky="w", padx=(8, 8), pady=(10, 0))
        mode_combo.bind("<<ComboboxSelected>>", self._handle_mode_change)

        ttk.Label(controls, text="Camera").grid(row=1, column=2, sticky="w", pady=(10, 0))
        ttk.Combobox(
            controls,
            textvariable=self.camera_var,
            values=["M30T", "M2EA"],
            state="readonly",
            width=10,
        ).grid(row=1, column=3, sticky="w", pady=(10, 0))

        self.check_results_button = ttk.Button(
            controls,
            text="Check Results",
            command=self._check_results,
            state="disabled",
        )
        self.check_results_button.grid(row=1, column=6, sticky="ew", padx=(8, 8), pady=(10, 0))
        ttk.Label(controls, textvariable=self.status_var, wraplength=420).grid(
            row=1, column=7, sticky="e", pady=(10, 0)
        )

        self.main_content = ttk.Panedwindow(self.root, orient="horizontal")
        self.main_content.grid(row=2, column=0, sticky="nsew", padx=12, pady=12)

        side_panel = ttk.Frame(self.main_content, padding=8)
        self.main_content.add(side_panel, weight=1)

        side_panel.columnconfigure(0, weight=1)
        side_panel.rowconfigure(1, weight=1)
        side_panel.rowconfigure(3, weight=2)

        ttk.Label(side_panel, text="Detected Burn Sets", font=("Segoe UI", 11, "bold")).grid(row=0, column=0, sticky="w")
        self.burn_tree = ttk.Treeview(
            side_panel,
            columns=("dataset", "burn", "pairs"),
            show="headings",
            height=7,
        )
        for key, label, width in [
            ("dataset", "Dataset", 120),
            ("burn", "Burn Set", 95),
            ("pairs", "Pairs", 65),
        ]:
            self.burn_tree.heading(key, text=label)
            self.burn_tree.column(key, width=width, anchor="center")
        self.burn_tree.grid(row=1, column=0, sticky="nsew", pady=(8, 14))
        self.burn_tree.bind("<<TreeviewSelect>>", self._handle_burn_selection)

        ttk.Label(side_panel, text="Matched Pairs", font=("Segoe UI", 11, "bold")).grid(row=2, column=0, sticky="w")
        self.pair_tree = ttk.Treeview(
            side_panel,
            columns=("index", "rgb", "thermal", "match"),
            show="headings",
            height=16,
        )
        for key, label, width in [
            ("index", "#", 48),
            ("rgb", "RGB", 110),
            ("thermal", "Thermal", 110),
            ("match", "Match", 80),
        ]:
            self.pair_tree.heading(key, text=label)
            self.pair_tree.column(key, width=width, anchor="center")
        self.pair_tree.grid(row=3, column=0, sticky="nsew", pady=(8, 0))
        self.pair_tree.bind("<<TreeviewSelect>>", self._handle_pair_selection)

        actions = ttk.LabelFrame(side_panel, text="Results Actions", padding=8)
        actions.grid(row=4, column=0, sticky="ew", pady=(12, 0))
        actions.columnconfigure(0, weight=1)
        self.view_output_button = ttk.Button(
            actions,
            text="View Output Folder",
            command=self._open_output_viewer,
            state="disabled",
        )
        self.view_output_button.grid(row=0, column=0, sticky="ew")

        bottom = ttk.Frame(self.root, padding=(12, 0, 12, 12))
        bottom.grid(row=3, column=0, sticky="nsew")
        bottom.columnconfigure(0, weight=1)

        self.progress_bar = ttk.Progressbar(
            bottom,
            variable=self.progress_var,
            maximum=100,
            mode="determinate",
        )
        self.progress_bar.grid(row=0, column=0, sticky="ew")
        ttk.Label(bottom, textvariable=self.progress_label_var).grid(row=1, column=0, sticky="w", pady=(6, 0))

        self.run_sort_button = ttk.Button(
            bottom,
            text="Run Sort",
            command=self._run_sort,
            style="Run.TButton",
        )
        self.run_sort_button.grid(row=2, column=0, sticky="ew", pady=(10, 0), ipady=10)
        ttk.Label(bottom, textvariable=self.summary_var, wraplength=1200).grid(
            row=3, column=0, sticky="w", pady=(10, 0)
        )

        self._handle_mode_change()

    def _browse_input(self):
        selected = filedialog.askdirectory(initialdir=self.input_var.get() or str(SCRIPT_DIR))
        if selected:
            self.input_var.set(selected)
            self._reset_results_state()
            self._sync_existing_results_state()

    def _browse_output(self):
        selected = filedialog.askdirectory(initialdir=self.output_var.get() or str(SCRIPT_DIR))
        if selected:
            self.output_var.set(selected)
            self._reset_results_state()
            self._sync_existing_results_state()

    def _handle_mode_change(self, event=None):
        presorted = self.mode_var.get() == "PRESORTED_STANDARD"
        self._sync_existing_results_state()
        self.status_var.set(
            "PRESORTED_STANDARD mode supports Check Results and clickable pair previews after sorting."
            if presorted
            else "DJI_RAW mode is ready to run. Check Results is currently only available for PRESORTED_STANDARD."
        )

    def _dataset_output_root(self, dataset_name):
        return Path(self.output_var.get().strip()) / dataset_name / "Images"

    def _scan_existing_output_results(self):
        output_root = Path(self.output_var.get().strip())
        if not output_root.exists() or not output_root.is_dir():
            return []

        analysis = []
        for dataset_dir in sorted([p for p in output_root.iterdir() if p.is_dir()]):
            images_root = dataset_dir / "Images"
            rgb_corrected = images_root / "RGB" / "Corrected FOV"
            rgb_raw = images_root / "RGB" / "Raw"
            thermal_jpg = images_root / "Thermal" / "JPG"
            thermal_tiff = images_root / "Thermal" / "Celsius TIFF"

            if not (rgb_corrected.exists() and rgb_raw.exists() and thermal_jpg.exists() and thermal_tiff.exists()):
                continue

            rgb_files = sorted([p for p in rgb_corrected.iterdir() if p.is_file()])
            thermal_jpg_files = sorted([p for p in thermal_jpg.iterdir() if p.is_file()])
            thermal_tiff_files = sorted([p for p in thermal_tiff.iterdir() if p.is_file()])
            if not rgb_files:
                continue

            pairs = []
            for rgb_path in rgb_files:
                stem = rgb_path.stem
                jpg_match = thermal_jpg / f"{stem}.JPG"
                if not jpg_match.exists():
                    jpg_match = thermal_jpg / f"{stem}.jpg"
                tiff_match = thermal_tiff / f"{stem}.TIFF"
                if not tiff_match.exists():
                    tiff_match = thermal_tiff / f"{stem}.tiff"
                raw_match = rgb_raw / rgb_path.name

                if not tiff_match.exists():
                    continue

                rgb_record = {
                    "filename": rgb_path.name,
                    "filepath": str(raw_match if raw_match.exists() else rgb_path),
                    "datetime": sorter._extract_capture_datetime(str(raw_match if raw_match.exists() else rgb_path)),
                }
                pairs.append(
                    {
                        "rgb": rgb_record,
                        "thermal_jpg": {
                            "filename": jpg_match.name,
                            "filepath": str(jpg_match),
                            "datetime": sorter._extract_capture_datetime(str(jpg_match)),
                        } if jpg_match.exists() else None,
                        "thermal_tiff": {
                            "filename": tiff_match.name,
                            "filepath": str(tiff_match),
                            "datetime": sorter._extract_capture_datetime(str(tiff_match)),
                        },
                        "cal_tiff": None,
                        "match_types": {
                            "thermal_jpg": "output",
                            "thermal_tiff": "output",
                            "cal_tiff": "output",
                        },
                    }
                )

            analysis.append(
                {
                    "name": dataset_dir.name,
                    "root": str(dataset_dir),
                    "burn_sets": [
                        {
                            "name": "sorted_output",
                            "source_root": str(images_root),
                            "layout": "sorted_output",
                            "rgb_count": len(rgb_files),
                            "thermal_jpg_count": len(thermal_jpg_files),
                            "thermal_tiff_count": len(thermal_tiff_files),
                            "cal_tiff_count": 0,
                            "pair_count": len(pairs),
                            "pairs": pairs,
                        }
                    ],
                }
            )

        return analysis

    def _sync_existing_results_state(self):
        existing_results = self._scan_existing_output_results() if self.mode_var.get() == "PRESORTED_STANDARD" else []
        self.results_ready = bool(existing_results)
        self.check_results_button.configure(state="normal" if self.results_ready else "disabled")

    def _reset_results_state(self):
        self.results_ready = False
        self.check_results_button.configure(state="disabled")
        self.progress_var.set(0)
        self.progress_label_var.set("Progress: idle")
        self.summary_var.set("No results loaded yet.")
        self.analysis = []
        self.selected_burn_set = None
        self.selected_pair = None
        self.burn_tree.delete(*self.burn_tree.get_children())
        self.pair_tree.delete(*self.pair_tree.get_children())
        self.view_output_button.configure(state="disabled")

    def _append_log(self, message):
        cleaned = message.strip()
        if cleaned:
            self.status_var.set(cleaned)

    def _poll_output_queue(self):
        try:
            while True:
                kind, payload = self.output_queue.get_nowait()
                if kind == "log":
                    self._append_log(payload)
                elif kind == "analysis":
                    self.analysis = payload
                    self._populate_analysis()
                elif kind == "status":
                    self.status_var.set(payload)
                elif kind == "progress":
                    current = payload["current"]
                    total = payload["total"] if payload["total"] else 1
                    percent = (current / total) * 100.0
                    self.progress_var.set(percent)
                    self.progress_label_var.set(payload["message"])
                elif kind == "results_ready":
                    self.results_ready = True
                    if self.mode_var.get() == "PRESORTED_STANDARD":
                        self.check_results_button.configure(state="normal")
                elif kind == "error":
                    self.status_var.set("Error encountered. See log below.")
                    self._append_log(payload + "\n")
                    messagebox.showerror("FLAME Raw File Sorting Assistant", payload)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_output_queue)

    def _run_in_thread(self, target):
        threading.Thread(target=target, daemon=True).start()

    def _check_results(self):
        if self.mode_var.get() != "PRESORTED_STANDARD":
            messagebox.showinfo("Unavailable", "Check Results is only available for PRESORTED_STANDARD mode.")
            return
        if not self.results_ready:
            messagebox.showinfo("Not ready", "Run Sort successfully first, then Check Results will become available.")
            return
        self.status_var.set("Checking results and loading detected matches...")

        def worker():
            try:
                analysis = self._scan_existing_output_results()
                if not analysis:
                    input_folder = self.input_var.get().strip()
                    if not input_folder:
                        raise FileNotFoundError("No existing output results were found and no input folder is set.")
                    analysis = sorter.analyze_presorted_standard(input_folder=input_folder)
            except Exception as exc:
                self.output_queue.put(("error", f"{exc}"))
                return

            self.output_queue.put(("analysis", analysis))
            self.output_queue.put(("status", f"Check Results complete. {len(analysis)} dataset(s) loaded."))

        self._run_in_thread(worker)

    def _run_sort(self):
        input_folder = self.input_var.get().strip()
        output_folder = self.output_var.get().strip()
        if not input_folder or not output_folder:
            messagebox.showerror("Missing folders", "Choose both input and output folders before running.")
            return

        output_path = Path(output_folder)
        if output_path.exists() and any(output_path.iterdir()):
            should_replace = messagebox.askyesno(
                "Replace existing output?",
                (
                    "The current Output Folder already contains a dataset output.\n\n"
                    "Are you sure you want to delete the existing contents of Output Folder "
                    "and create a new output?"
                ),
            )
            if not should_replace:
                return

            for child in output_path.iterdir():
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()

        sorter.CAMERA_USED = self.camera_var.get()
        sorter.PROCESSING_MODE = self.mode_var.get()
        self._reset_results_state()
        self.status_var.set("Running sort...")
        self.progress_var.set(0)
        self.progress_label_var.set("Progress: preparing")
        self.summary_var.set("Sorting in progress...")

        def worker():
            writer = QueueWriter(self.output_queue)
            try:
                with contextlib.redirect_stdout(writer), contextlib.redirect_stderr(writer):
                    if sorter.PROCESSING_MODE == "PRESORTED_STANDARD":
                        def progress_callback(payload):
                            self.output_queue.put(("progress", payload))

                        sorter.process_presorted_standard(
                            input_folder=input_folder,
                            output_folder=output_folder,
                            dry_run_only=False,
                            progress_callback=progress_callback,
                        )
                    else:
                        sorter.INPUT_FOLDER = os.path.abspath(input_folder)
                        sorter.OUTPUT_FOLDER = os.path.abspath(output_folder)
                        sorter.raw_file_sorting()
            except SystemExit as exc:
                if exc.code not in (0, None):
                    self.output_queue.put(("error", f"Sorter exited with code {exc.code}."))
                    return
            except Exception:
                self.output_queue.put(("error", traceback.format_exc()))
                return

            self.output_queue.put(
                (
                    "progress",
                    {"current": 1, "total": 1, "message": "Progress: complete"},
                )
            )
            self.output_queue.put(("results_ready", True))
            self.output_queue.put(("status", "Sort completed successfully. You can now click Check Results."))

        self._run_in_thread(worker)

    def _populate_analysis(self):
        self.burn_tree.delete(*self.burn_tree.get_children())
        self.pair_tree.delete(*self.pair_tree.get_children())
        self.selected_burn_set = None
        self.selected_pair = None
        self.view_output_button.configure(state="disabled")

        dataset_count = len(self.analysis)
        burn_set_count = sum(len(dataset["burn_sets"]) for dataset in self.analysis)
        pair_count = sum(
            burn_set["pair_count"] for dataset in self.analysis for burn_set in dataset["burn_sets"]
        )
        self.summary_var.set(
            f"Loaded {dataset_count} dataset(s), {burn_set_count} burn set(s), and {pair_count} matched pair(s)."
        )

        for dataset_idx, dataset in enumerate(self.analysis):
            for burn_idx, burn_set in enumerate(dataset["burn_sets"]):
                iid = f"{dataset_idx}:{burn_idx}"
                self.burn_tree.insert(
                    "",
                    "end",
                    iid=iid,
                    values=(dataset["name"], burn_set["name"], burn_set["pair_count"]),
                )

        if self.burn_tree.get_children():
            first = self.burn_tree.get_children()[0]
            self.burn_tree.selection_set(first)
            self._handle_burn_selection()
            self.view_output_button.configure(state="normal")

    def _handle_burn_selection(self, event=None):
        selection = self.burn_tree.selection()
        if not selection:
            return

        dataset_idx, burn_idx = [int(part) for part in selection[0].split(":")]
        self.selected_burn_set = self.analysis[dataset_idx]["burn_sets"][burn_idx]
        self.view_output_button.configure(state="normal")

        self.pair_tree.delete(*self.pair_tree.get_children())
        for pair_idx, pair in enumerate(self.selected_burn_set["pairs"], start=1):
            self.pair_tree.insert(
                "",
                "end",
                iid=str(pair_idx - 1),
                values=(
                    pair_idx,
                    Path(pair["rgb"]["filename"]).name,
                    Path(pair["thermal_jpg"]["filename"]).name if pair["thermal_jpg"] else Path(pair["thermal_tiff"]["filename"]).name,
                    pair["match_types"]["thermal_tiff"],
                ),
            )

        self.summary_var.set(
            f"{self.selected_burn_set['name']} from {Path(self.selected_burn_set['source_root']).name}: "
            f"{self.selected_burn_set['pair_count']} matched pairs, "
            f"{self.selected_burn_set['rgb_count']} RGB, "
            f"{self.selected_burn_set['thermal_jpg_count']} thermal JPG, "
            f"{self.selected_burn_set['thermal_tiff_count']} thermal TIFF."
        )

        children = self.pair_tree.get_children()
        if children:
            self.pair_tree.selection_set(children[0])

    def _handle_pair_selection(self, event=None):
        if self.selected_burn_set is None:
            return
        selection = self.pair_tree.selection()
        if not selection:
            return

        self.selected_pair = self.selected_burn_set["pairs"][int(selection[0])]
        self.view_output_button.configure(state="normal")

    def _open_output_viewer(self):
        if self.selected_burn_set is None:
            return
        initial_index = 0
        selection = self.pair_tree.selection()
        if selection:
            initial_index = int(selection[0])
        PairPreviewWindow(self.root, sorter, self.selected_burn_set, initial_index=initial_index)

    def _open_output_folder(self):
        output_folder = self.output_var.get().strip()
        if output_folder:
            self._open_path(output_folder)

    def _open_path(self, path):
        try:
            if os.name == "nt":
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as exc:
            messagebox.showerror("Open failed", f"Could not open:\n{path}\n\n{exc}")


def main():
    root = tk.Tk()
    style = ttk.Style(root)
    if "vista" in style.theme_names():
        style.theme_use("vista")
    style.configure("Run.TButton", font=("Segoe UI", 12, "bold"))
    RawSortingGui(root)
    root.mainloop()


if __name__ == "__main__":
    import sys

    main()
