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


class AlignmentValidationWindow:
    def __init__(self, parent, sorter_module, pair):
        self.sorter = sorter_module
        self.pair = pair
        self.overlay_dx = 0.0
        self.overlay_dy = 0.0
        self.drag_last = None
        self.click_start = None
        self.dragging = False
        self.last_probe_canvas_point = None
        self.last_render_state = {}
        self.current_canvas_image = None
        self.current_composite = None
        self.cached_images = {}

        self.base_mode_var = tk.StringVar(value="Corrected FOV")
        self.thermal_source_var = tk.StringVar()
        self.opacity_var = tk.DoubleVar(value=55.0)
        self.thermal_scale_var = tk.DoubleVar(value=100.0)
        self.rgb_grayscale_var = tk.BooleanVar(value=False)
        self.thermal_grayscale_var = tk.BooleanVar(value=False)
        self.show_crop_box_var = tk.BooleanVar(value=True)
        self.transform_var = tk.StringVar(value="")
        self.probe_var = tk.StringVar(value="Click a point to inspect coordinates and values.")

        self.window = tk.Toplevel(parent)
        self.window.title("Alignment Validation Tool")
        self.window.geometry("1680x980")
        self.window.minsize(1200, 760)

        self._load_images()
        self._build_ui()
        self._bind_events()
        self._reset_overlay()

    def _build_ui(self):
        outer = ttk.Frame(self.window, padding=12)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=0)
        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(1, weight=1)

        ttk.Label(
            outer,
            text="Alignment Validation Tool",
            font=("Segoe UI", 13, "bold"),
        ).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(
            outer,
            text=(
                "Drag the thermal layer to move it. Use the mouse wheel or the scale slider to resize it. "
                "This is for visual validation only; it does not change the sorted files."
            ),
            wraplength=1400,
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 10))

        controls = ttk.LabelFrame(outer, text="Overlay Controls", padding=10)
        controls.grid(row=2, column=0, sticky="nsw", padx=(0, 12))
        controls.columnconfigure(0, weight=1)

        ttk.Label(controls, text="Base Image").grid(row=0, column=0, sticky="w")
        base_combo = ttk.Combobox(
            controls,
            textvariable=self.base_mode_var,
            values=["Corrected FOV", "Raw RGB"],
            state="readonly",
            width=24,
        )
        base_combo.grid(row=1, column=0, sticky="ew", pady=(4, 10))
        base_combo.bind("<<ComboboxSelected>>", lambda event: self._refresh_canvas())

        ttk.Label(controls, text="Thermal Source").grid(row=2, column=0, sticky="w")
        thermal_combo = ttk.Combobox(
            controls,
            textvariable=self.thermal_source_var,
            values=list(self.thermal_sources.keys()),
            state="readonly",
            width=24,
        )
        thermal_combo.grid(row=3, column=0, sticky="ew", pady=(4, 10))
        thermal_combo.bind("<<ComboboxSelected>>", lambda event: self._refresh_canvas())

        ttk.Label(controls, text="Thermal Opacity").grid(row=4, column=0, sticky="w")
        ttk.Scale(
            controls,
            variable=self.opacity_var,
            from_=0,
            to=100,
            orient="horizontal",
            command=lambda value: self._refresh_canvas(),
        ).grid(row=5, column=0, sticky="ew", pady=(4, 10))

        ttk.Label(controls, text="Thermal Scale").grid(row=6, column=0, sticky="w")
        ttk.Scale(
            controls,
            variable=self.thermal_scale_var,
            from_=20,
            to=220,
            orient="horizontal",
            command=lambda value: self._refresh_canvas(),
        ).grid(row=7, column=0, sticky="ew", pady=(4, 10))

        ttk.Checkbutton(
            controls,
            text="RGB to Grayscale",
            variable=self.rgb_grayscale_var,
            command=self._refresh_canvas,
        ).grid(row=8, column=0, sticky="w", pady=(2, 0))
        ttk.Checkbutton(
            controls,
            text="Thermal to Grayscale",
            variable=self.thermal_grayscale_var,
            command=self._refresh_canvas,
        ).grid(row=9, column=0, sticky="w", pady=(2, 0))
        ttk.Checkbutton(
            controls,
            text="Show Fixed Crop Box on Raw RGB",
            variable=self.show_crop_box_var,
            command=self._refresh_canvas,
        ).grid(row=10, column=0, sticky="w", pady=(2, 10))

        nudge_frame = ttk.LabelFrame(controls, text="Fine Nudge", padding=8)
        nudge_frame.grid(row=11, column=0, sticky="ew", pady=(8, 10))
        for column in range(3):
            nudge_frame.columnconfigure(column, weight=1)
        ttk.Button(nudge_frame, text="Up", command=lambda: self._nudge_overlay(0, -2)).grid(row=0, column=1, sticky="ew")
        ttk.Button(nudge_frame, text="Left", command=lambda: self._nudge_overlay(-2, 0)).grid(row=1, column=0, sticky="ew", padx=(0, 4), pady=(4, 0))
        ttk.Button(nudge_frame, text="Right", command=lambda: self._nudge_overlay(2, 0)).grid(row=1, column=2, sticky="ew", padx=(4, 0), pady=(4, 0))
        ttk.Button(nudge_frame, text="Down", command=lambda: self._nudge_overlay(0, 2)).grid(row=2, column=1, sticky="ew", pady=(4, 0))

        ttk.Button(controls, text="Reset Overlay", command=self._reset_overlay).grid(row=12, column=0, sticky="ew", pady=(4, 0))
        ttk.Button(controls, text="Copy Transform", command=self._copy_transform).grid(row=13, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(controls, text="Save Snapshot", command=self._save_snapshot).grid(row=14, column=0, sticky="ew", pady=(8, 0))

        ttk.Label(
            controls,
            textvariable=self.transform_var,
            wraplength=260,
            justify="left",
        ).grid(row=15, column=0, sticky="w", pady=(12, 0))
        ttk.Label(
            controls,
            textvariable=self.probe_var,
            wraplength=260,
            justify="left",
        ).grid(row=16, column=0, sticky="w", pady=(12, 0))

        self.canvas = tk.Canvas(outer, background="#1f1f1f", highlightthickness=0)
        self.canvas.grid(row=2, column=1, sticky="nsew")

    def _bind_events(self):
        self.canvas.bind("<Configure>", lambda event: self._refresh_canvas())
        self.canvas.bind("<ButtonPress-1>", self._start_drag)
        self.canvas.bind("<B1-Motion>", self._drag_overlay)
        self.canvas.bind("<ButtonRelease-1>", self._stop_drag)
        self.window.bind("<MouseWheel>", self._handle_mouse_wheel)
        self.window.bind("<Left>", lambda event: self._nudge_overlay(-2, 0))
        self.window.bind("<Right>", lambda event: self._nudge_overlay(2, 0))
        self.window.bind("<Up>", lambda event: self._nudge_overlay(0, -2))
        self.window.bind("<Down>", lambda event: self._nudge_overlay(0, 2))
        self.window.bind("r", lambda event: self._reset_overlay())

    def _load_standard_image(self, path):
        image = Image.open(path)
        if image.mode not in ("RGB", "RGBA"):
            image = ImageOps.autocontrast(image.convert("L")).convert("RGB")
        else:
            image = image.convert("RGB")
        return image

    def _load_value_image(self, path):
        with Image.open(path) as image:
            return image.copy()

    def _load_images(self):
        dataset_name = self.pair.get("dataset_name")
        burn_set_name = self.pair.get("burn_set_name")
        detected_camera = self.pair.get("detected_camera")
        self.raw_rgb = self._load_standard_image(self.pair["rgb"]["filepath"])
        self.raw_rgb_value_image = self._load_value_image(self.pair["rgb"]["filepath"])
        self.thermal_alignment_source = (
            self.pair["cal_tiff"]["filepath"]
            if self.pair["cal_tiff"] is not None
            else self.pair["thermal_tiff"]["filepath"]
        )
        self.fixed_crop_debug = self.sorter._get_crop_debug_info(
            self.pair["rgb"]["filepath"],
            thermal_source_path=self.thermal_alignment_source,
            use_experimental_shift=False,
            dataset_name=dataset_name,
            burn_set_name=burn_set_name,
            camera_used=detected_camera,
        )
        self.corrected_fixed = self.sorter._apply_rgb_fov_correction(
            self.pair["rgb"]["filepath"],
            thermal_source_path=self.thermal_alignment_source,
            use_experimental_shift=False,
            dataset_name=dataset_name,
            burn_set_name=burn_set_name,
            camera_used=detected_camera,
        ).convert("RGB")
        self.corrected_fixed_value_image = self.corrected_fixed.copy()

        self.thermal_sources = {}
        if self.pair["thermal_jpg"] is not None:
            self.thermal_sources["Thermal JPG"] = {
                "path": self.pair["thermal_jpg"]["filepath"],
                "image": self._load_standard_image(self.pair["thermal_jpg"]["filepath"]),
                "value_image": self._load_value_image(self.pair["thermal_jpg"]["filepath"]),
            }
        if self.pair["cal_tiff"] is not None:
            self.thermal_sources["Cal TIFF"] = {
                "path": self.pair["cal_tiff"]["filepath"],
                "image": self._load_standard_image(self.pair["cal_tiff"]["filepath"]),
                "value_image": self._load_value_image(self.pair["cal_tiff"]["filepath"]),
            }
        if self.pair["thermal_tiff"] is not None:
            self.thermal_sources["Thermal TIFF"] = {
                "path": self.pair["thermal_tiff"]["filepath"],
                "image": self._load_standard_image(self.pair["thermal_tiff"]["filepath"]),
                "value_image": self._load_value_image(self.pair["thermal_tiff"]["filepath"]),
            }

        self.thermal_source_var.set(next(iter(self.thermal_sources.keys())))

    def _start_drag(self, event):
        self.click_start = (event.x, event.y)
        self.drag_last = (event.x, event.y)
        self.dragging = False
        self.canvas.focus_set()

    def _drag_overlay(self, event):
        if self.drag_last is None:
            return
        if self.click_start is not None:
            travel = abs(event.x - self.click_start[0]) + abs(event.y - self.click_start[1])
            if travel < 4:
                return
            self.dragging = True
        last_x, last_y = self.drag_last
        self.overlay_dx += event.x - last_x
        self.overlay_dy += event.y - last_y
        self.drag_last = (event.x, event.y)
        self._refresh_canvas()

    def _stop_drag(self, event=None):
        if not self.dragging and event is not None:
            self._set_probe_point(event.x, event.y)
        self.drag_last = None
        self.click_start = None
        self.dragging = False

    def _handle_mouse_wheel(self, event):
        direction = 1 if event.delta > 0 else -1
        next_value = min(220, max(20, self.thermal_scale_var.get() + (direction * 2)))
        self.thermal_scale_var.set(next_value)
        self._refresh_canvas()

    def _nudge_overlay(self, delta_x, delta_y):
        self.overlay_dx += delta_x
        self.overlay_dy += delta_y
        self._refresh_canvas()

    def _reset_overlay(self):
        self.overlay_dx = 0.0
        self.overlay_dy = 0.0
        self.thermal_scale_var.set(100.0)
        self.opacity_var.set(55.0)
        self._refresh_canvas()

    def _set_probe_point(self, x, y):
        self.last_probe_canvas_point = (x, y)
        self._refresh_canvas()

    def _copy_transform(self):
        payload = self.transform_var.get()
        self.window.clipboard_clear()
        self.window.clipboard_append(payload)

    def _save_snapshot(self):
        if self.current_composite is None:
            return
        default_name = f"{Path(self.pair['rgb']['filename']).stem}_alignment_overlay.png"
        destination = filedialog.asksaveasfilename(
            parent=self.window,
            defaultextension=".png",
            initialfile=default_name,
            filetypes=[("PNG Image", "*.png")],
        )
        if not destination:
            return
        self.current_composite.save(destination)

    def _fit_rect(self, image_size, available_width, available_height, margin=16):
        width, height = image_size
        usable_width = max(available_width - margin * 2, 1)
        usable_height = max(available_height - margin * 2, 1)
        scale = min(usable_width / width, usable_height / height)
        scaled_width = max(1, int(width * scale))
        scaled_height = max(1, int(height * scale))
        left = (available_width - scaled_width) // 2
        top = (available_height - scaled_height) // 2
        return left, top, scaled_width, scaled_height, scale

    def _map_canvas_point_to_image(self, point, rect, image_size):
        x, y = point
        left, top, width, height = rect
        if width <= 0 or height <= 0:
            return None
        if x < left or y < top or x >= left + width or y >= top + height:
            return None

        normalized_x = (x - left) / float(width)
        normalized_y = (y - top) / float(height)
        image_x = min(image_size[0] - 1, max(0, int(normalized_x * image_size[0])))
        image_y = min(image_size[1] - 1, max(0, int(normalized_y * image_size[1])))
        return image_x, image_y

    def _format_pixel_value(self, value):
        if hasattr(value, "item"):
            value = value.item()
        if isinstance(value, tuple):
            return "(" + ", ".join(str(int(channel)) if isinstance(channel, (int, float)) else str(channel) for channel in value) + ")"
        if isinstance(value, float):
            return f"{value:.3f}"
        return str(value)

    def _get_pixel_value(self, image, coords):
        if coords is None:
            return None
        return image.getpixel(coords)

    def _probe_text(self):
        if self.last_probe_canvas_point is None or not self.last_render_state:
            return "Click a point to inspect coordinates and values."

        point = self.last_probe_canvas_point
        state = self.last_render_state

        base_image = self.raw_rgb_value_image if self.base_mode_var.get() == "Raw RGB" else self.corrected_fixed_value_image
        base_coords = self._map_canvas_point_to_image(
            point,
            state["base_rect"],
            base_image.size,
        )
        thermal_value_image = self.thermal_sources[self.thermal_source_var.get()]["value_image"]
        thermal_coords = self._map_canvas_point_to_image(
            point,
            state["overlay_rect"],
            thermal_value_image.size,
        )

        lines = [f"Canvas: ({int(point[0])}, {int(point[1])})"]
        if base_coords is None:
            lines.append(f"{self.base_mode_var.get()}: outside image")
        else:
            base_value = self._format_pixel_value(self._get_pixel_value(base_image, base_coords))
            lines.append(
                f"{self.base_mode_var.get()}: ({base_coords[0]}, {base_coords[1]}) value={base_value}"
            )
            if self.base_mode_var.get() == "Raw RGB":
                crop_box = self.fixed_crop_debug["final_crop_box"]
                if (
                    crop_box[0] <= base_coords[0] < crop_box[2]
                    and crop_box[1] <= base_coords[1] < crop_box[3]
                ):
                    corrected_coords = (base_coords[0] - crop_box[0], base_coords[1] - crop_box[1])
                    lines.append(
                        f"Fixed crop-relative: ({corrected_coords[0]}, {corrected_coords[1]})"
                    )
                else:
                    lines.append("Fixed crop-relative: outside crop box")

        if thermal_coords is None:
            lines.append(f"{self.thermal_source_var.get()}: outside overlay")
        else:
            thermal_value = self._format_pixel_value(self._get_pixel_value(thermal_value_image, thermal_coords))
            lines.append(
                f"{self.thermal_source_var.get()}: ({thermal_coords[0]}, {thermal_coords[1]}) value={thermal_value}"
            )

        return "\n".join(lines)

    def _draw_probe_marker(self, draw):
        if self.last_probe_canvas_point is None:
            return
        x, y = self.last_probe_canvas_point
        radius = 8
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), outline=(255, 255, 0), width=2)
        draw.line((x - 16, y, x + 16, y), fill=(255, 255, 0), width=2)
        draw.line((x, y - 16, x, y + 16), fill=(255, 255, 0), width=2)

    def _draw_dashed_rectangle(self, draw, rectangle, color=(0, 0, 0), width=3, dash=14, gap=8):
        x1, y1, x2, y2 = rectangle
        x = x1
        while x < x2:
            draw.line((x, y1, min(x + dash, x2), y1), fill=color, width=width)
            draw.line((x, y2, min(x + dash, x2), y2), fill=color, width=width)
            x += dash + gap
        y = y1
        while y < y2:
            draw.line((x1, y, x1, min(y + dash, y2)), fill=color, width=width)
            draw.line((x2, y, x2, min(y + dash, y2)), fill=color, width=width)
            y += dash + gap

    def _prepare_base_image(self):
        if self.base_mode_var.get() == "Raw RGB":
            image = self.raw_rgb.copy()
        else:
            image = self.corrected_fixed.copy()
        if self.rgb_grayscale_var.get():
            image = ImageOps.grayscale(image).convert("RGB")
        return image

    def _prepare_thermal_image(self):
        selected = self.thermal_sources[self.thermal_source_var.get()]["image"].copy()
        if self.thermal_grayscale_var.get():
            selected = ImageOps.grayscale(selected).convert("RGB")
        return selected

    def _compose_overlay(self, width, height):
        base_image = self._prepare_base_image()
        thermal_image = self._prepare_thermal_image()
        composite = Image.new("RGB", (width, height), color=(31, 31, 31))

        base_left, base_top, base_width, base_height, base_scale = self._fit_rect(
            base_image.size,
            width,
            height,
        )
        base_display = base_image.resize((base_width, base_height), Image.LANCZOS)
        composite.paste(base_display, (base_left, base_top))
        draw = ImageDraw.Draw(composite)

        if self.base_mode_var.get() == "Raw RGB":
            crop_box = self.fixed_crop_debug["final_crop_box"]
            anchor_left = int(base_left + crop_box[0] * base_scale)
            anchor_top = int(base_top + crop_box[1] * base_scale)
            anchor_width = max(1, int((crop_box[2] - crop_box[0]) * base_scale))
            anchor_height = max(1, int((crop_box[3] - crop_box[1]) * base_scale))
            if self.show_crop_box_var.get():
                self._draw_dashed_rectangle(
                    draw,
                    (
                        anchor_left,
                        anchor_top,
                        anchor_left + anchor_width,
                        anchor_top + anchor_height,
                    ),
                )
        else:
            anchor_left = base_left
            anchor_top = base_top
            anchor_width = base_width
            anchor_height = base_height

        overlay_scale = self.thermal_scale_var.get() / 100.0
        thermal_width = max(1, int(anchor_width * overlay_scale))
        thermal_height = max(1, int(anchor_height * overlay_scale))
        thermal_display = thermal_image.resize((thermal_width, thermal_height), Image.LANCZOS).convert("RGBA")
        alpha_value = int((self.opacity_var.get() / 100.0) * 255)
        thermal_display.putalpha(alpha_value)

        overlay_left = int(anchor_left + ((anchor_width - thermal_width) / 2.0) + self.overlay_dx)
        overlay_top = int(anchor_top + ((anchor_height - thermal_height) / 2.0) + self.overlay_dy)

        composite_rgba = composite.convert("RGBA")
        overlay_layer = Image.new("RGBA", composite_rgba.size, (0, 0, 0, 0))
        overlay_layer.paste(thermal_display, (overlay_left, overlay_top), thermal_display)
        composite_rgba = Image.alpha_composite(composite_rgba, overlay_layer)
        composite = composite_rgba.convert("RGB")
        self.last_render_state = {
            "base_rect": (base_left, base_top, base_width, base_height),
            "overlay_rect": (overlay_left, overlay_top, thermal_width, thermal_height),
            "anchor_rect": (anchor_left, anchor_top, anchor_width, anchor_height),
        }
        draw = ImageDraw.Draw(composite)
        self._draw_probe_marker(draw)

        self.transform_var.set(
            "Base: {base} | Thermal: {thermal} | Offset x={x:+.0f}, y={y:+.0f} | Scale={scale:.1f}% | Opacity={opacity:.0f}%".format(
                base=self.base_mode_var.get(),
                thermal=self.thermal_source_var.get(),
                x=self.overlay_dx,
                y=self.overlay_dy,
                scale=self.thermal_scale_var.get(),
                opacity=self.opacity_var.get(),
            )
        )
        self.probe_var.set(self._probe_text())
        return composite

    def _refresh_canvas(self):
        width = max(self.canvas.winfo_width(), 400)
        height = max(self.canvas.winfo_height(), 300)
        self.current_composite = self._compose_overlay(width, height)
        self.current_canvas_image = ImageTk.PhotoImage(self.current_composite)
        self.canvas.delete("all")
        self.canvas.create_image(width // 2, height // 2, image=self.current_canvas_image, anchor="center")


class CalibrationProfileWindow:
    def __init__(self, parent, sorter_module, burn_set, initial_index=0):
        self.sorter = sorter_module
        self.burn_set = burn_set
        self.pairs = burn_set["pairs"]
        self.dataset_name = burn_set.get("dataset_name") or Path(burn_set["source_root"]).parent.name
        self.burn_set_name = burn_set.get("name", "burn_set_001")
        self.detected_camera = burn_set.get("detected_camera", self.sorter.CAMERA_USED)
        self.current_pair_index = max(0, min(initial_index, len(self.pairs) - 1)) if self.pairs else 0
        self.control_points = []
        self.pending_source = None
        self.pending_target = None
        self.current_profile = None
        self.estimated_profile = None
        self.current_source_photo = None
        self.current_thermal_photo = None
        self.large_source_photo = None
        self.large_thermal_photo = None
        self.current_source_state = {}
        self.current_thermal_state = {}
        self.large_source_state = {}
        self.large_thermal_state = {}
        self.current_pair = None
        self.current_crop_debug = None
        self.current_raw_rgb = None
        self.current_crop_only = None
        self.current_thermal = None
        self.large_click_window = None
        self.large_source_canvas = None
        self.large_thermal_canvas = None

        self.base_mode_var = tk.StringVar(value="Crop Baseline")
        self.scope_var = tk.StringVar(value="dataset")
        self.pair_label_var = tk.StringVar(value="")
        self.pending_var = tk.StringVar(value="Click one source point and one thermal point in either order.")
        self.profile_summary_var = tk.StringVar(value="No calibration estimated yet.")
        self.profile_path_var = tk.StringVar(value="No saved calibration profile loaded.")

        self.window = tk.Toplevel(parent)
        self.window.title(f"Developer Calibration - {self.dataset_name} / {self.burn_set_name}")
        self.window.geometry("2140x1240")
        self.window.minsize(1500, 920)

        self._build_ui()
        self._load_existing_profile()
        self._load_pair()

    def _build_ui(self):
        outer = ttk.Frame(self.window, padding=12)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=0)
        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(1, weight=0)
        outer.rowconfigure(2, weight=1)

        ttk.Label(
            outer,
            text=f"Developer Calibration: {self.dataset_name} / {self.burn_set_name}",
            font=("Segoe UI", 13, "bold"),
        ).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(
            outer,
            text=(
                "Collect source-to-thermal correspondences, estimate the geometric correction model, "
                "then save the profile for automatic reuse during sorting/export."
            ),
            wraplength=1500,
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 10))

        controls = ttk.LabelFrame(outer, text="Calibration Controls", padding=10)
        controls.grid(row=2, column=0, sticky="nsw", padx=(0, 12))
        controls.columnconfigure(0, weight=1)

        ttk.Label(controls, textvariable=self.pair_label_var, font=("Segoe UI", 10, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        pair_nav = ttk.Frame(controls)
        pair_nav.grid(row=1, column=0, sticky="ew", pady=(8, 10))
        pair_nav.columnconfigure(0, weight=1)
        pair_nav.columnconfigure(1, weight=1)
        ttk.Button(pair_nav, text="Previous Pair", command=self._show_previous_pair).grid(
            row=0, column=0, sticky="ew", padx=(0, 6)
        )
        ttk.Button(pair_nav, text="Next Pair", command=self._show_next_pair).grid(
            row=0, column=1, sticky="ew", padx=(6, 0)
        )

        ttk.Label(controls, text="Source View").grid(row=2, column=0, sticky="w")
        source_combo = ttk.Combobox(
            controls,
            textvariable=self.base_mode_var,
            values=["Crop Baseline", "Raw RGB"],
            state="readonly",
            width=24,
        )
        source_combo.grid(row=3, column=0, sticky="ew", pady=(4, 10))
        source_combo.bind("<<ComboboxSelected>>", lambda event: self._refresh_canvases())

        ttk.Label(controls, text="Save Scope").grid(row=4, column=0, sticky="w")
        scope_combo = ttk.Combobox(
            controls,
            textvariable=self.scope_var,
            values=["dataset", "burn_set", "camera_default"],
            state="readonly",
            width=24,
        )
        scope_combo.grid(row=5, column=0, sticky="ew", pady=(4, 10))

        ttk.Button(controls, text="Estimate Models", command=self._estimate_models).grid(
            row=6, column=0, sticky="ew", pady=(4, 0)
        )
        ttk.Button(controls, text="Save Calibration Profile", command=self._save_profile).grid(
            row=7, column=0, sticky="ew", pady=(8, 0)
        )
        ttk.Button(controls, text="Export Validation Samples", command=self._export_validation).grid(
            row=8, column=0, sticky="ew", pady=(8, 0)
        )
        ttk.Button(controls, text="Open Large Click View", command=self._open_large_click_view).grid(
            row=9, column=0, sticky="ew", pady=(12, 0)
        )
        ttk.Button(controls, text="Remove Last Point", command=self._remove_last_point).grid(
            row=10, column=0, sticky="ew", pady=(12, 0)
        )
        ttk.Button(controls, text="Clear All Points", command=self._clear_points).grid(
            row=11, column=0, sticky="ew", pady=(8, 0)
        )

        ttk.Label(
            controls,
            textvariable=self.pending_var,
            wraplength=280,
            justify="left",
        ).grid(row=12, column=0, sticky="w", pady=(12, 0))
        ttk.Label(
            controls,
            textvariable=self.profile_summary_var,
            wraplength=280,
            justify="left",
        ).grid(row=13, column=0, sticky="w", pady=(12, 0))
        ttk.Label(
            controls,
            textvariable=self.profile_path_var,
            wraplength=280,
            justify="left",
        ).grid(row=14, column=0, sticky="w", pady=(12, 0))

        right = ttk.Frame(outer)
        right.grid(row=2, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.columnconfigure(1, weight=1)
        right.rowconfigure(1, weight=8)
        right.rowconfigure(3, weight=2)

        ttk.Label(right, text="Source Image", font=("Segoe UI", 10, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(right, text="Thermal Image", font=("Segoe UI", 10, "bold")).grid(row=0, column=1, sticky="w")

        self.source_canvas = tk.Canvas(right, background="#1f1f1f", highlightthickness=0)
        self.source_canvas.grid(row=1, column=0, sticky="nsew", padx=(0, 8), pady=(8, 12))
        self.thermal_canvas = tk.Canvas(right, background="#1f1f1f", highlightthickness=0)
        self.thermal_canvas.grid(row=1, column=1, sticky="nsew", padx=(8, 0), pady=(8, 12))
        self.source_canvas.bind("<Button-1>", self._handle_source_click)
        self.thermal_canvas.bind("<Button-1>", self._handle_thermal_click)
        self.source_canvas.bind("<Configure>", lambda event: self._refresh_canvases())
        self.thermal_canvas.bind("<Configure>", lambda event: self._refresh_canvases())

        ttk.Label(right, text="Estimated Models", font=("Segoe UI", 10, "bold")).grid(row=2, column=0, sticky="w")
        ttk.Label(right, text="Control Points", font=("Segoe UI", 10, "bold")).grid(row=2, column=1, sticky="w")

        self.model_tree = ttk.Treeview(
            right,
            columns=("model", "rmse", "mean", "max", "points", "chosen"),
            show="headings",
            height=8,
        )
        for key, label, width in [
            ("model", "Model", 110),
            ("rmse", "RMSE", 70),
            ("mean", "Mean", 70),
            ("max", "Max", 70),
            ("points", "Points", 65),
            ("chosen", "Chosen", 70),
        ]:
            self.model_tree.heading(key, text=label)
            self.model_tree.column(key, width=width, anchor="center")
        self.model_tree.grid(row=3, column=0, sticky="nsew", padx=(0, 8))

        self.point_tree = ttk.Treeview(
            right,
            columns=("point", "pair", "source", "target", "error"),
            show="headings",
            height=8,
        )
        for key, label, width in [
            ("point", "Point", 70),
            ("pair", "Pair", 70),
            ("source", "Source", 130),
            ("target", "Thermal", 130),
            ("error", "Error", 80),
        ]:
            self.point_tree.heading(key, text=label)
            self.point_tree.column(key, width=width, anchor="center")
        self.point_tree.grid(row=3, column=1, sticky="nsew", padx=(8, 0))

    def _load_existing_profile(self):
        self.current_profile = self.sorter.load_calibration_profile(
            camera_used=self.detected_camera,
            dataset_name=self.dataset_name,
            burn_set_name=self.burn_set_name,
        )
        if self.current_profile is None:
            self.profile_path_var.set("No saved calibration profile loaded.")
            return

        selected_model = self.current_profile.get("selected_model", "crop_only")
        selected_summary = self.current_profile.get("selected_model_summary", {})
        rmse = selected_summary.get("rmse")
        rmse_text = "n/a" if rmse is None else f"{rmse:.4f}px"
        self.profile_summary_var.set(
            f"Loaded saved profile. Model={selected_model}, RMSE={rmse_text}"
        )
        self.profile_path_var.set(
            f"Loaded profile:\n{self.current_profile.get('profile_path', '')}"
        )
        self._populate_model_tree(self.current_profile)

    def _load_standard_image(self, path):
        with Image.open(path) as image:
            if image.mode not in ("RGB", "RGBA"):
                return ImageOps.autocontrast(image.convert("L")).convert("RGB")
            return image.convert("RGB")

    def _fit_rect(self, image_size, available_width, available_height, margin=16):
        width, height = image_size
        usable_width = max(available_width - margin * 2, 1)
        usable_height = max(available_height - margin * 2, 1)
        scale = min(usable_width / width, usable_height / height)
        scaled_width = max(1, int(width * scale))
        scaled_height = max(1, int(height * scale))
        left = (available_width - scaled_width) // 2
        top = (available_height - scaled_height) // 2
        return left, top, scaled_width, scaled_height, scale

    def _map_canvas_point_to_image(self, point, rect, image_size):
        x, y = point
        left, top, width, height = rect
        if width <= 0 or height <= 0:
            return None
        if x < left or y < top or x >= left + width or y >= top + height:
            return None
        normalized_x = (x - left) / float(width)
        normalized_y = (y - top) / float(height)
        image_x = min(image_size[0] - 1, max(0, int(normalized_x * image_size[0])))
        image_y = min(image_size[1] - 1, max(0, int(normalized_y * image_size[1])))
        return image_x, image_y

    def _draw_dashed_rectangle(self, draw, rectangle, color=(0, 0, 0), width=3, dash=14, gap=8):
        x1, y1, x2, y2 = rectangle
        x = x1
        while x < x2:
            draw.line((x, y1, min(x + dash, x2), y1), fill=color, width=width)
            draw.line((x, y2, min(x + dash, x2), y2), fill=color, width=width)
            x += dash + gap
        y = y1
        while y < y2:
            draw.line((x1, y, x1, min(y + dash, y2)), fill=color, width=width)
            draw.line((x2, y, x2, min(y + dash, y2)), fill=color, width=width)
            y += dash + gap

    def _corrected_to_raw_coords(self, corrected_coords):
        crop_box = self.current_crop_debug["final_crop_box"]
        output_width, output_height = self.sorter._get_output_size()
        crop_width = max(crop_box[2] - crop_box[0], 1)
        crop_height = max(crop_box[3] - crop_box[1], 1)
        return (
            crop_box[0] + (corrected_coords[0] / float(output_width)) * crop_width,
            crop_box[1] + (corrected_coords[1] / float(output_height)) * crop_height,
        )

    def _refresh_canvases(self):
        if self.current_pair is None:
            return

        source_image = self.current_crop_only if self.base_mode_var.get() == "Crop Baseline" else self.current_raw_rgb
        thermal_image = self.current_thermal

        self.current_source_state = self._draw_image_canvas(
            self.source_canvas,
            source_image,
            draw_crop_box=self.base_mode_var.get() == "Raw RGB",
            point_mode="source",
        )
        self.current_thermal_state = self._draw_image_canvas(
            self.thermal_canvas,
            thermal_image,
            draw_crop_box=False,
            point_mode="thermal",
        )
        self._refresh_large_click_view()

    def _draw_image_canvas(self, canvas, image, draw_crop_box=False, point_mode="source", state_attr=None, photo_attr=None):
        width = max(canvas.winfo_width(), 240)
        height = max(canvas.winfo_height(), 200)
        rect = self._fit_rect(image.size, width, height)
        display = image.resize((rect[2], rect[3]), Image.LANCZOS)
        composite = Image.new("RGB", (width, height), color=(31, 31, 31))
        composite.paste(display, (rect[0], rect[1]))
        draw = ImageDraw.Draw(composite)

        if draw_crop_box:
            crop_box = self.current_crop_debug["final_crop_box"]
            crop_left = int(rect[0] + crop_box[0] * rect[4])
            crop_top = int(rect[1] + crop_box[1] * rect[4])
            crop_right = int(rect[0] + crop_box[2] * rect[4])
            crop_bottom = int(rect[1] + crop_box[3] * rect[4])
            self._draw_dashed_rectangle(draw, (crop_left, crop_top, crop_right, crop_bottom))

        current_pair_label = f"{self.current_pair_index + 1:05d}"
        for point in self.control_points:
            if point["pair_label"] != current_pair_label:
                continue
            coords = point["target"] if point_mode == "thermal" else point["source"]
            if point_mode == "source" and self.base_mode_var.get() == "Raw RGB":
                coords = self._corrected_to_raw_coords(point["source"])
            canvas_x = int(rect[0] + (coords[0] / float(image.size[0])) * rect[2])
            canvas_y = int(rect[1] + (coords[1] / float(image.size[1])) * rect[3])
            draw.ellipse((canvas_x - 8, canvas_y - 8, canvas_x + 8, canvas_y + 8), outline=(255, 255, 0), width=2)
            draw.text((canvas_x + 10, canvas_y - 12), point["point_id"], fill=(255, 255, 0))

        pending = self.pending_source if point_mode == "source" else self.pending_target
        if pending is not None:
            pending_coords = pending["display_coords"] if point_mode == "source" else pending["coords"]
            canvas_x = int(rect[0] + (pending_coords[0] / float(image.size[0])) * rect[2])
            canvas_y = int(rect[1] + (pending_coords[1] / float(image.size[1])) * rect[3])
            draw.ellipse((canvas_x - 8, canvas_y - 8, canvas_x + 8, canvas_y + 8), outline=(0, 255, 255), width=2)

        photo = ImageTk.PhotoImage(composite)
        if photo_attr is not None:
            setattr(self, photo_attr, photo)
        elif point_mode == "source":
            self.current_source_photo = photo
        else:
            self.current_thermal_photo = photo
        canvas.delete("all")
        canvas.create_image(width // 2, height // 2, image=photo, anchor="center")
        state = {"rect": (rect[0], rect[1], rect[2], rect[3]), "image_size": image.size}
        if state_attr is not None:
            setattr(self, state_attr, state)
        return state

    def _refresh_large_click_view(self):
        if self.large_click_window is None or not self.large_click_window.winfo_exists():
            self.large_click_window = None
            self.large_source_canvas = None
            self.large_thermal_canvas = None
            return
        if self.current_pair is None:
            return

        source_image = self.current_crop_only if self.base_mode_var.get() == "Crop Baseline" else self.current_raw_rgb
        thermal_image = self.current_thermal
        self._draw_image_canvas(
            self.large_source_canvas,
            source_image,
            draw_crop_box=self.base_mode_var.get() == "Raw RGB",
            point_mode="source",
            state_attr="large_source_state",
            photo_attr="large_source_photo",
        )
        self._draw_image_canvas(
            self.large_thermal_canvas,
            thermal_image,
            draw_crop_box=False,
            point_mode="thermal",
            state_attr="large_thermal_state",
            photo_attr="large_thermal_photo",
        )

    def _load_pair(self):
        if not self.pairs:
            return

        self.current_pair = self.pairs[self.current_pair_index]
        self.current_pair["dataset_name"] = self.dataset_name
        self.current_pair["burn_set_name"] = self.burn_set_name
        self.current_pair["detected_camera"] = self.detected_camera
        thermal_source = (
            self.current_pair["thermal_jpg"]["filepath"]
            if self.current_pair["thermal_jpg"] is not None
            else self.current_pair["cal_tiff"]["filepath"] if self.current_pair["cal_tiff"] is not None else self.current_pair["thermal_tiff"]["filepath"]
        )
        self.current_raw_rgb = self._load_standard_image(self.current_pair["rgb"]["filepath"])
        self.current_crop_only, self.current_crop_debug = self.sorter._apply_rgb_fov_correction(
            self.current_pair["rgb"]["filepath"],
            thermal_source_path=thermal_source,
            use_experimental_shift=False,
            dataset_name=self.dataset_name,
            burn_set_name=self.burn_set_name,
            calibration_profile=None,
            camera_used=self.detected_camera,
            return_debug_info=True,
        )
        self.current_crop_only = self.current_crop_only.convert("RGB")
        self.current_thermal = self._load_standard_image(thermal_source)
        self.pair_label_var.set(
            f"Pair {self.current_pair_index + 1} of {len(self.pairs)} | {Path(self.current_pair['rgb']['filename']).name}"
        )
        self.pending_source = None
        self.pending_target = None
        self.pending_var.set("Click one source point and one thermal point in either order.")
        self._refresh_canvases()
        self._populate_point_tree()

    def _complete_pending_control_point_if_ready(self):
        if self.pending_source is None or self.pending_target is None:
            return False

        point_id = f"P{len(self.control_points) + 1:03d}"
        self.control_points.append(
            {
                "point_id": point_id,
                "pair_label": f"{self.current_pair_index + 1:05d}",
                "source": list(self.pending_source["corrected_coords"]),
                "target": list(self.pending_target["coords"]),
                "source_basis": self.pending_source["basis"],
            }
        )
        self.pending_source = None
        self.pending_target = None
        self.estimated_profile = None
        self.pending_var.set(f"Added {point_id}. Click one source point and one thermal point in either order.")
        self._populate_point_tree()
        self._refresh_canvases()
        return True

    def _handle_source_click(self, event):
        self._handle_source_click_for_state(event, self.current_source_state)

    def _handle_thermal_click(self, event):
        self._handle_thermal_click_for_state(event, self.current_thermal_state)

    def _handle_source_click_for_state(self, event, state):
        if not state:
            return

        point = self._map_canvas_point_to_image(
            (event.x, event.y),
            state["rect"],
            state["image_size"],
        )
        if point is None:
            return

        if self.base_mode_var.get() == "Raw RGB":
            crop_box = self.current_crop_debug["final_crop_box"]
            if not (crop_box[0] <= point[0] < crop_box[2] and crop_box[1] <= point[1] < crop_box[3]):
                self.pending_var.set("Raw RGB click is outside the baseline crop box. Pick a point inside the dashed rectangle.")
                return
            corrected_coords = self.sorter._project_raw_point_to_corrected_coords(point, crop_box)
            self.pending_source = {
                "corrected_coords": corrected_coords,
                "display_coords": point,
                "basis": "raw_rgb",
            }
        else:
            self.pending_source = {
                "corrected_coords": (float(point[0]), float(point[1])),
                "display_coords": point,
                "basis": "crop_baseline",
            }

        if self._complete_pending_control_point_if_ready():
            return

        self.pending_var.set("Source point recorded. Now click the matching point in the thermal image.")
        self._refresh_canvases()

    def _handle_thermal_click_for_state(self, event, state):
        if not state:
            return

        point = self._map_canvas_point_to_image(
            (event.x, event.y),
            state["rect"],
            state["image_size"],
        )
        if point is None:
            return

        self.pending_target = {"coords": (float(point[0]), float(point[1]))}
        if self._complete_pending_control_point_if_ready():
            return

        self.pending_var.set("Thermal point recorded. Click the matching source point next.")
        self._refresh_canvases()

    def _estimate_models(self):
        if not self.control_points:
            messagebox.showinfo("No points", "Add at least one source/thermal correspondence before estimating a calibration model.")
            return

        self.estimated_profile = self.sorter.build_calibration_profile(
            self.control_points,
            camera_used=self.detected_camera,
            dataset_name=self.dataset_name,
            burn_set_name=self.burn_set_name,
            profile_scope=self.scope_var.get(),
            baseline_crop_box=self.current_crop_debug["base_crop_box"],
            source_rgb_size=self.current_raw_rgb.size,
            notes="Created with the Raw File Sorting GUI developer calibration tool.",
        )
        self._populate_model_tree(self.estimated_profile)
        self._populate_point_tree()

        selected_model = self.estimated_profile["selected_model"]
        selected_summary = self.estimated_profile["selected_model_summary"]
        crop_only_rmse = self.estimated_profile["models"]["crop_only"]["rmse"]
        final_rmse = selected_summary.get("rmse")
        if crop_only_rmse is None or final_rmse is None:
            improvement_text = "Improvement unavailable"
        else:
            improvement_text = f"RMSE change: {crop_only_rmse - final_rmse:+.4f}px"
        self.profile_summary_var.set(
            f"Estimated model={selected_model}, RMSE={final_rmse:.4f}px. {improvement_text}"
        )

    def _open_large_click_view(self):
        if self.large_click_window is not None and self.large_click_window.winfo_exists():
            self.large_click_window.lift()
            self.large_click_window.focus_force()
            self._refresh_large_click_view()
            return

        self.large_click_window = tk.Toplevel(self.window)
        self.large_click_window.title(f"Large Click View - {self.dataset_name} / {self.burn_set_name}")
        self.large_click_window.geometry("2460x1380")
        self.large_click_window.minsize(1600, 900)
        self.large_click_window.protocol("WM_DELETE_WINDOW", self._close_large_click_view)

        outer = ttk.Frame(self.large_click_window, padding=12)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(1, weight=1)

        ttk.Label(
            outer,
            text="Large Click View",
            font=("Segoe UI", 13, "bold"),
        ).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(
            outer,
            text=(
                "Use this window for precise point picking. Click one source point and one matching thermal point "
                "in either order. The control-point list and model estimates stay synced with the developer calibration window."
            ),
            wraplength=1800,
        ).grid(row=0, column=1, sticky="e")

        left_frame = ttk.Frame(outer)
        left_frame.grid(row=1, column=0, sticky="nsew", padx=(0, 8), pady=(10, 0))
        left_frame.columnconfigure(0, weight=1)
        left_frame.rowconfigure(1, weight=1)
        ttk.Label(left_frame, text="Source Image", font=("Segoe UI", 10, "bold")).grid(row=0, column=0, sticky="w")
        self.large_source_canvas = tk.Canvas(left_frame, background="#1f1f1f", highlightthickness=0)
        self.large_source_canvas.grid(row=1, column=0, sticky="nsew")

        right_frame = ttk.Frame(outer)
        right_frame.grid(row=1, column=1, sticky="nsew", padx=(8, 0), pady=(10, 0))
        right_frame.columnconfigure(0, weight=1)
        right_frame.rowconfigure(1, weight=1)
        ttk.Label(right_frame, text="Thermal Image", font=("Segoe UI", 10, "bold")).grid(row=0, column=0, sticky="w")
        self.large_thermal_canvas = tk.Canvas(right_frame, background="#1f1f1f", highlightthickness=0)
        self.large_thermal_canvas.grid(row=1, column=0, sticky="nsew")

        self.large_source_canvas.bind("<Button-1>", lambda event: self._handle_source_click_for_state(event, self.large_source_state))
        self.large_thermal_canvas.bind("<Button-1>", lambda event: self._handle_thermal_click_for_state(event, self.large_thermal_state))
        self.large_source_canvas.bind("<Configure>", lambda event: self._refresh_large_click_view())
        self.large_thermal_canvas.bind("<Configure>", lambda event: self._refresh_large_click_view())

        self._refresh_large_click_view()

    def _close_large_click_view(self):
        if self.large_click_window is not None and self.large_click_window.winfo_exists():
            self.large_click_window.destroy()
        self.large_click_window = None
        self.large_source_canvas = None
        self.large_thermal_canvas = None
        self.large_source_state = {}
        self.large_thermal_state = {}

    def _save_profile(self):
        if self.estimated_profile is None:
            self._estimate_models()
            if self.estimated_profile is None:
                return

        self.estimated_profile["scope"] = self.scope_var.get()
        profile_path = self.sorter.save_calibration_profile(self.estimated_profile)
        self.current_profile = dict(self.estimated_profile)
        self.current_profile["profile_path"] = profile_path
        self.profile_path_var.set(f"Saved profile:\n{profile_path}")
        messagebox.showinfo("Calibration Saved", f"Calibration profile saved:\n{profile_path}")

    def _export_validation(self):
        profile = self.estimated_profile or self.current_profile
        export_root = Path(self.burn_set["source_root"])
        if export_root.name.lower() == "images":
            export_root = export_root.parent
        debug_root = self.sorter.export_alignment_debug_samples(
            str(export_root),
            self.dataset_name,
            self.burn_set_name,
            self.pairs,
            calibration_profile=profile,
        )
        if not debug_root:
            messagebox.showinfo("No samples", "No validation samples were generated.")
            return
        messagebox.showinfo("Validation Exported", f"Validation samples exported to:\n{debug_root}")

    def _remove_last_point(self):
        if not self.control_points:
            return
        self.control_points.pop()
        self.estimated_profile = None
        self.pending_var.set("Removed the last control point.")
        self._populate_point_tree()
        self._refresh_canvases()

    def _clear_points(self):
        self.control_points = []
        self.pending_source = None
        self.pending_target = None
        self.estimated_profile = None
        self.pending_var.set("All control points cleared.")
        self._populate_point_tree()
        self._refresh_canvases()

    def _show_previous_pair(self):
        if not self.pairs:
            return
        self.current_pair_index = (self.current_pair_index - 1) % len(self.pairs)
        self._load_pair()

    def _show_next_pair(self):
        if not self.pairs:
            return
        self.current_pair_index = (self.current_pair_index + 1) % len(self.pairs)
        self._load_pair()

    def _populate_model_tree(self, profile):
        self.model_tree.delete(*self.model_tree.get_children())
        if profile is None:
            return

        selected_model = profile.get("selected_model", "")
        for model_name in self.sorter.CALIBRATION_MODEL_ORDER:
            model = profile["models"].get(model_name)
            if model is None:
                continue
            rmse = "" if model.get("rmse") is None else f"{model['rmse']:.4f}"
            mean_error = "" if model.get("mean_error") is None else f"{model['mean_error']:.4f}"
            max_error = "" if model.get("max_error") is None else f"{model['max_error']:.4f}"
            self.model_tree.insert(
                "",
                "end",
                values=(
                    model_name,
                    rmse,
                    mean_error,
                    max_error,
                    model.get("point_count", 0),
                    "yes" if model_name == selected_model else "",
                ),
            )

    def _populate_point_tree(self):
        self.point_tree.delete(*self.point_tree.get_children())
        error_lookup = {}
        if self.estimated_profile is not None:
            selected_model = self.estimated_profile["selected_model"]
            model = self.estimated_profile["models"].get(selected_model, {})
            error_lookup = {
                item["point_id"]: item["error"]
                for item in model.get("per_point_error", [])
            }

        for point in self.control_points:
            error_text = ""
            if point["point_id"] in error_lookup:
                error_text = f"{error_lookup[point['point_id']]:.4f}"
            self.point_tree.insert(
                "",
                "end",
                values=(
                    point["point_id"],
                    point["pair_label"],
                    f"({point['source'][0]:.1f}, {point['source'][1]:.1f})",
                    f"({point['target'][0]:.1f}, {point['target'][1]:.1f})",
                    error_text,
                ),
            )


class PairPreviewWindow:
    def __init__(self, parent, sorter_module, burn_set, initial_index=0):
        self.sorter = sorter_module
        self.burn_set = burn_set
        self.all_pairs = burn_set["pairs"]
        self.filtered_indices = list(range(len(self.all_pairs)))
        self.current_filtered_pos = 0
        self.images = {}
        self.source_images = {}
        self.overlay_opacity_var = tk.DoubleVar(value=50.0)
        self.metrics_var = tk.StringVar(value="AUTO_ALIGN metrics will appear after a pair is loaded.")

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

        ttk.Label(preview_area, text="Crop-Only Corrected FOV", font=("Segoe UI", 10, "bold")).grid(row=3, column=0, sticky="w")
        ttk.Label(preview_area, text="Thermal", font=("Segoe UI", 10, "bold")).grid(row=3, column=1, sticky="w")

        actions = ttk.LabelFrame(preview_area, text="Viewer Actions", padding=8)
        actions.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(10, 10))
        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=1)
        actions.columnconfigure(2, weight=1)
        actions.columnconfigure(3, weight=1)
        self.open_raw_button = ttk.Button(actions, text="Open Matching Raw RGB", command=self._open_matching_raw_rgb)
        self.open_raw_button.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.open_output_button = ttk.Button(actions, text="Open Output Folder", command=self._open_output_folder)
        self.open_output_button.grid(row=0, column=1, sticky="ew", padx=8)
        self.alignment_tool_button = ttk.Button(
            actions,
            text="Validate Alignment Overlay",
            command=self._open_alignment_validation,
        )
        self.alignment_tool_button.grid(row=0, column=2, sticky="ew", padx=8)
        self.calibration_tool_button = ttk.Button(
            actions,
            text="Developer Calibration",
            command=self._open_calibration_tool,
        )
        self.calibration_tool_button.grid(row=0, column=3, sticky="ew", padx=(8, 0))

        ttk.Label(actions, text="Overlay Opacity").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Scale(
            actions,
            variable=self.overlay_opacity_var,
            from_=0,
            to=100,
            orient="horizontal",
            command=lambda value: self._refresh_validation_overlays(),
        ).grid(row=1, column=1, columnspan=3, sticky="ew", pady=(8, 0))

        ttk.Label(preview_area, text="Crop-Only vs Thermal Overlay", font=("Segoe UI", 10, "bold")).grid(row=6, column=0, sticky="w")
        ttk.Label(preview_area, text="AUTO_ALIGN vs Thermal Overlay", font=("Segoe UI", 10, "bold")).grid(row=6, column=1, sticky="w")
        ttk.Label(
            preview_area,
            textvariable=self.metrics_var,
            wraplength=1200,
            justify="left",
        ).grid(row=7, column=0, columnspan=2, sticky="ew", pady=(8, 0))

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
        self._draw_canvas_image(self.raw_overlay_canvas, "crop_overlay")
        self._draw_canvas_image(self.compare_canvas, "auto_overlay")

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
        self.current_dataset_name = pair.get("dataset_name", self.burn_set.get("dataset_name"))
        self.current_burn_set_name = pair.get("burn_set_name", self.burn_set.get("name"))
        self.current_detected_camera = pair.get("detected_camera", self.burn_set.get("detected_camera"))

        thermal_source = (
            pair["thermal_jpg"]["filepath"]
            if pair["thermal_jpg"] is not None
            else pair["cal_tiff"]["filepath"] if pair["cal_tiff"] is not None else pair["thermal_tiff"]["filepath"]
        )
        self.current_thermal_source = thermal_source
        crop_only, crop_debug = self._load_corrected_with_mode(pair["rgb"]["filepath"], "CROP_ONLY")
        auto_align, auto_debug = self._load_corrected_with_mode(pair["rgb"]["filepath"], "AUTO_ALIGN")
        thermal = self._load_preview_image(thermal_source, mode="thermal")
        self.current_crop_only_image = crop_only
        self.current_auto_align_image = auto_align
        self.current_thermal_image = thermal
        self.current_auto_align_debug = auto_debug
        self.current_crop_debug = crop_debug
        crop_overlay = self._build_thermal_overlay(crop_only, thermal)
        auto_overlay = self._build_thermal_overlay(auto_align, thermal)

        self.source_images["corrected"] = crop_only
        self.source_images["thermal"] = thermal
        self.source_images["crop_overlay"] = crop_overlay
        self.source_images["auto_overlay"] = auto_overlay
        self._update_metrics_text(auto_debug)
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
            corrected = self.sorter._apply_rgb_fov_correction(
                path,
                getattr(self, "current_thermal_source", None),
                dataset_name=getattr(self, "current_dataset_name", None),
                burn_set_name=getattr(self, "current_burn_set_name", None),
                camera_used=getattr(self, "current_detected_camera", None),
            )
            if corrected.mode not in ("RGB", "RGBA"):
                corrected = corrected.convert("RGB")
            img.close()
            return corrected

        if img.mode not in ("RGB", "RGBA"):
            img = ImageOps.autocontrast(img.convert("L")).convert("RGB")
        else:
            img = img.convert("RGB")
        return img

    def _load_corrected_with_mode(self, raw_path, mode):
        previous_mode = self.sorter.FOV_CORRECTION_MODE
        try:
            self.sorter.FOV_CORRECTION_MODE = mode
            corrected, debug_info = self.sorter._apply_rgb_fov_correction(
                raw_path,
                getattr(self, "current_thermal_source", None),
                dataset_name=getattr(self, "current_dataset_name", None),
                burn_set_name=getattr(self, "current_burn_set_name", None),
                camera_used=getattr(self, "current_detected_camera", None),
                return_debug_info=True,
            )
        finally:
            self.sorter.FOV_CORRECTION_MODE = previous_mode

        if corrected.mode not in ("RGB", "RGBA"):
            corrected = corrected.convert("RGB")
        return corrected.convert("RGB"), debug_info

    def _build_thermal_overlay(self, rgb_image, thermal_image):
        opacity = max(0.0, min(self.overlay_opacity_var.get() / 100.0, 1.0))
        thermal = ImageOps.autocontrast(thermal_image.convert("L")).convert("RGB").resize(rgb_image.size, Image.LANCZOS)
        return Image.blend(rgb_image.convert("RGB"), thermal, opacity)

    def _refresh_validation_overlays(self):
        if not all(
            hasattr(self, attr)
            for attr in ("current_crop_only_image", "current_auto_align_image", "current_thermal_image")
        ):
            return
        self.source_images["crop_overlay"] = self._build_thermal_overlay(
            self.current_crop_only_image,
            self.current_thermal_image,
        )
        self.source_images["auto_overlay"] = self._build_thermal_overlay(
            self.current_auto_align_image,
            self.current_thermal_image,
        )
        self._refresh_canvases()

    def _update_metrics_text(self, debug_info):
        alignment = debug_info.get("feature_alignment", {})
        reasons = " | ".join(alignment.get("reasons", [])) or "none"
        questionable = " | ".join(alignment.get("auto_align_questionable_reasons", [])) or "none"
        self.metrics_var.set(
            "AUTO_ALIGN review: visually_better_unknown | "
            f"model={alignment.get('transform_type', '')} | "
            f"prep={alignment.get('representation', '')} | "
            f"confidence={alignment.get('confidence_level', '')} | "
            f"status={alignment.get('status', '')} | "
            f"scale=({alignment.get('scale_x', 1.0):.4f}, {alignment.get('scale_y', 1.0):.4f}) | "
            f"translation=({alignment.get('translation_x', 0.0):.1f}, {alignment.get('translation_y', 0.0):.1f}) | "
            f"skew={alignment.get('skew_dot', 0.0):.4f} | "
            f"rotation={alignment.get('rotation_degrees', 0.0):.2f} deg | "
            f"inliers={alignment.get('inliers', 0)} | "
            f"inlier_ratio={alignment.get('inlier_ratio', 0.0)} | "
            f"inlier_grid_cells={alignment.get('inlier_grid_cells', 0)} | "
            f"RMSE={alignment.get('mean_reprojection_error_px', '')} | "
            f"fallback={alignment.get('fallback_used', '')} | "
            f"reasons={reasons} | "
            f"questionable={questionable}"
        )

    def _get_crop_box(self, raw_path):
        raw = self._load_preview_image(raw_path, mode="rgb")
        crop_box = self.sorter._get_aligned_crop_box(
            raw_path,
            getattr(self, "current_thermal_source", None),
            dataset_name=getattr(self, "current_dataset_name", None),
            burn_set_name=getattr(self, "current_burn_set_name", None),
            camera_used=getattr(self, "current_detected_camera", None),
        )
        return raw, crop_box

    def _build_raw_overlay_image(self, raw_path):
        raw, crop_box = self._get_crop_box(raw_path)
        overlay = raw.copy()
        draw = ImageDraw.Draw(overlay)
        dash = max(10, raw.width // 120)
        gap = max(6, dash // 2)
        x1, y1, x2, y2 = crop_box

        x = x1
        while x < x2:
            draw.line((x, y1, min(x + dash, x2), y1), fill=(0, 0, 0), width=max(3, raw.width // 600))
            draw.line((x, y2, min(x + dash, x2), y2), fill=(0, 0, 0), width=max(3, raw.width // 600))
            x += dash + gap
        y = y1
        while y < y2:
            draw.line((x1, y, x1, min(y + dash, y2)), fill=(0, 0, 0), width=max(3, raw.width // 600))
            draw.line((x2, y, x2, min(y + dash, y2)), fill=(0, 0, 0), width=max(3, raw.width // 600))
            y += dash + gap
        return overlay

    def _build_compare_image(self, raw_path):
        raw = self._load_preview_image(raw_path, mode="rgb")
        corrected = self._load_preview_image(raw_path, mode="rgb_corrected")
        pad = 24
        label_h = 40
        canvas_width = raw.width + corrected.width + pad * 3
        canvas_height = max(raw.height, corrected.height) + pad * 2 + label_h
        combined = Image.new("RGB", (canvas_width, canvas_height), color=(245, 245, 245))
        combined.paste(raw, (pad, pad + label_h))
        combined.paste(corrected, (raw.width + pad * 2, pad + label_h))
        draw = ImageDraw.Draw(combined)
        draw.text((pad, 10), "Raw RGB", fill=(0, 0, 0))
        draw.text((raw.width + pad * 2, 10), "Corrected FOV", fill=(0, 0, 0))
        return combined

    def _open_matching_raw_rgb(self):
        if not hasattr(self, "current_pair"):
            return
        self._open_path(self.current_pair["rgb"]["filepath"])

    def _open_output_folder(self):
        self._open_path(self.burn_set["source_root"])

    def _open_alignment_validation(self):
        if not hasattr(self, "current_pair"):
            return
        AlignmentValidationWindow(self.window, self.sorter, self.current_pair)

    def _open_calibration_tool(self):
        if not hasattr(self, "current_pair"):
            return
        pair_index = self.filtered_indices[self.current_filtered_pos]
        CalibrationProfileWindow(self.window, self.sorter, self.burn_set, initial_index=pair_index)

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
        self.mode_var = tk.StringVar(value="AUTO")
        self.camera_var = tk.StringVar(value="Detected automatically per dataset")
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
                "The tool auto-detects the workflow, then writes the standard FLAME output. "
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

        ttk.Label(controls, text="Workflow").grid(row=1, column=0, sticky="w", pady=(10, 0))
        ttk.Label(controls, text="Auto-detect from Input Folder").grid(row=1, column=1, sticky="w", padx=(8, 8), pady=(10, 0))

        ttk.Label(controls, text="Camera").grid(row=1, column=2, sticky="w", pady=(10, 0))
        ttk.Label(
            controls,
            textvariable=self.camera_var,
            wraplength=180,
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
        self._sync_existing_results_state()
        self.status_var.set(
            "Auto-detect is enabled. Run Sort will inspect the input folder, detect the camera per dataset, and choose the appropriate workflow."
        )

    def _dataset_output_root(self, dataset_name):
        return Path(self.output_var.get().strip()) / dataset_name / "Images"

    def _scan_existing_output_results(self):
        output_root = Path(self.output_var.get().strip())
        if not output_root.exists() or not output_root.is_dir():
            return []

        analysis = []
        for dataset_dir in sorted([p for p in output_root.iterdir() if p.is_dir()]):
            burn_set_roots = []
            direct_images_root = dataset_dir / "Images"
            if direct_images_root.exists():
                burn_set_roots.append(("sorted_output", direct_images_root))
            else:
                for child_dir in sorted([p for p in dataset_dir.iterdir() if p.is_dir()]):
                    child_images_root = child_dir / "Images"
                    if child_images_root.exists():
                        burn_set_roots.append((child_dir.name, child_images_root))

            if not burn_set_roots:
                continue

            dataset_entry = {"name": dataset_dir.name, "root": str(dataset_dir), "burn_sets": []}
            for burn_set_name, images_root in burn_set_roots:
                rgb_corrected = images_root / "RGB" / "Corrected FOV"
                rgb_raw = images_root / "RGB" / "Raw"
                thermal_jpg = images_root / "Thermal" / "JPG"
                thermal_tiff = images_root / "Thermal" / "Celsius TIFF"

                if not (rgb_corrected.exists() and rgb_raw.exists() and thermal_tiff.exists()):
                    continue

                rgb_files = sorted([p for p in rgb_corrected.iterdir() if p.is_file() and p.name != ".gitkeep"])
                thermal_jpg_files = sorted([p for p in thermal_jpg.iterdir() if p.is_file() and p.name != ".gitkeep"]) if thermal_jpg.exists() else []
                thermal_tiff_files = sorted([p for p in thermal_tiff.iterdir() if p.is_file() and p.name != ".gitkeep"])
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

                    rgb_source_path = raw_match if raw_match.exists() else rgb_path
                    pairs.append(
                        {
                            "dataset_name": dataset_dir.name,
                            "burn_set_name": burn_set_name,
                            "rgb": {
                                "filename": rgb_path.name,
                                "filepath": str(rgb_source_path),
                                "datetime": sorter._extract_capture_datetime(str(rgb_source_path)),
                            },
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

                rgb_records = [
                    {"filepath": pair["rgb"]["filepath"], "image_size": None}
                    for pair in pairs
                ]
                camera_detection = sorter.detect_camera_from_rgb_records(rgb_records)
                profile = sorter.load_calibration_profile(
                    camera_used=camera_detection["camera"],
                    dataset_name=dataset_dir.name,
                    burn_set_name=burn_set_name,
                )
                for pair in pairs:
                    pair["detected_camera"] = camera_detection["camera"]
                    pair["camera_detection_reason"] = camera_detection["reason"]
                    pair["camera_image_size"] = camera_detection.get("image_size")
                dataset_entry["burn_sets"].append(
                    {
                        "name": burn_set_name,
                        "dataset_name": dataset_dir.name,
                        "source_root": str(images_root),
                        "layout": "sorted_output",
                        "rgb_count": len(rgb_files),
                        "thermal_jpg_count": len(thermal_jpg_files),
                        "thermal_tiff_count": len(thermal_tiff_files),
                        "cal_tiff_count": 0,
                        "pair_count": len(pairs),
                        "detected_camera": camera_detection["camera"],
                        "camera_dimension_summary": camera_detection.get("dimension_summary", ""),
                        "camera_detection_reason": camera_detection["reason"],
                        "correction_model": (
                            profile["selected_model"]
                            if profile and sorter._get_fov_correction_mode() == "CALIBRATION_PROFILE"
                            else sorter._get_fov_correction_mode().lower()
                        ),
                        "correction_rmse": (
                            profile.get("selected_model_summary", {}).get("rmse")
                            if profile is not None and sorter._get_fov_correction_mode() == "CALIBRATION_PROFILE"
                            else None
                        ),
                        "calibration_profile_path": profile.get("profile_path", "") if profile else "",
                        "pairs": pairs,
                    }
                )

            if dataset_entry["burn_sets"]:
                analysis.append(dataset_entry)

        return analysis

    def _sync_existing_results_state(self):
        existing_results = self._scan_existing_output_results()
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
        if not self.results_ready:
            self.status_var.set("Checking results from the current output folder...")
        else:
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

            gitkeep_path = output_path / ".gitkeep"
            gitkeep_exists = gitkeep_path.exists()
            for child in output_path.iterdir():
                if child.name == ".gitkeep":
                    continue
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()
            if gitkeep_exists and not gitkeep_path.exists():
                gitkeep_path.write_text("", encoding="utf-8")

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
                    def progress_callback(payload):
                        self.output_queue.put(("progress", payload))

                    sorter.run_sort_pipeline(
                        input_folder=input_folder,
                        output_folder=output_folder,
                        processing_mode=self.mode_var.get(),
                        progress_callback=progress_callback,
                    )
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
            f"{self.selected_burn_set['thermal_tiff_count']} thermal TIFF, "
            f"camera={self.selected_burn_set.get('detected_camera', 'unknown')}, "
            f"correction model={self.selected_burn_set.get('correction_model', 'crop_only')}."
        )
        self.camera_var.set(
            f"Detected in results: {self.selected_burn_set.get('detected_camera', 'unknown')}"
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
