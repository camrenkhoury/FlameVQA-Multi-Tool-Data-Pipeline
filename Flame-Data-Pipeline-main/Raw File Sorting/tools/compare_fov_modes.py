"""Compare AUTO_ALIGN against CALIBRATION_PROFILE on a representative sample.

This is an experiment harness only. It does not change production defaults.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps

try:
    import cv2
except ImportError:  # pragma: no cover - the project venv normally has OpenCV.
    cv2 = None


SCRIPT_PATH = Path(__file__).resolve()
TOOLS_DIR = SCRIPT_PATH.parent
RAW_SORTING_DIR = TOOLS_DIR.parent
SORTER_PATH = RAW_SORTING_DIR / "Raw File Sorting.py"
DEFAULT_DATASET_PATH = RAW_SORTING_DIR / "Input Folder" / "payson_test"
RUNS_ROOT = TOOLS_DIR / "fov_compare_runs"

OUTPUT_SIZE = (640, 512)
THERMAL_FIRE_MIN_BLOB_AREA_FRAC = 0.003
RGB_FIRE_COVERAGE_MIN = 0.15
RGB_FIRE_MASK_DILATE_PX = 5
JPG_QUALITY = 92


def load_sorter():
    spec = importlib.util.spec_from_file_location("raw_file_sorting", SORTER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not import sorter from {SORTER_PATH}")
    sorter = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = sorter
    spec.loader.exec_module(sorter)
    return sorter


def unique_run_dir(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    candidate = root / stamp
    suffix = 1
    while candidate.exists():
        candidate = root / f"{stamp}_{suffix:02d}"
        suffix += 1
    candidate.mkdir(parents=True)
    return candidate


def find_dataset_analysis(sorter, input_path: Path, dataset_name: str | None):
    input_path = input_path.resolve()
    if not input_path.exists():
        raise FileNotFoundError(f"Input path does not exist: {input_path}")

    if dataset_name:
        analysis_root = input_path
        analysis = sorter.analyze_presorted_standard(str(analysis_root))
        matches = [dataset for dataset in analysis if dataset["name"] == dataset_name]
        if not matches and input_path.name == dataset_name:
            analysis = sorter.analyze_presorted_standard(str(input_path.parent))
            matches = [dataset for dataset in analysis if dataset["name"] == dataset_name]
    else:
        analysis = sorter.analyze_presorted_standard(str(input_path.parent))
        matches = [
            dataset
            for dataset in analysis
            if Path(dataset["root"]).resolve() == input_path or dataset["name"] == input_path.name
        ]
        if not matches:
            analysis = sorter.analyze_presorted_standard(str(input_path))
            matches = analysis

    if not matches:
        raise RuntimeError(
            "Could not find a presorted dataset for "
            f"input_path={input_path} dataset_name={dataset_name or ''}"
        )
    if len(matches) > 1:
        names = ", ".join(dataset["name"] for dataset in matches)
        raise RuntimeError(f"Comparison expects one dataset. Matched: {names}")
    return matches[0]


def sampled_pairs_for_burn_set(sorter, burn_set: dict, sample_count: int, seed: int):
    pairs = list(burn_set.get("pairs", []))
    indices = sorter.representative_transform_sample_indices(
        len(pairs),
        target_count=sample_count,
        seed=seed,
    )
    return [(index + 1, pairs[index]) for index in indices]


def calibration_profile_status(sorter, dataset_name: str, burn_set_name: str, camera_used: str | None):
    """Return the first calibration profile candidate and whether runtime accepts it."""
    if not camera_used:
        return {"path": "", "valid": False, "reasons": ["camera_missing"], "selected_model": ""}

    candidate_paths = [
        sorter._calibration_profiles_root()
        / sorter._profile_filename(
            camera_used=camera_used,
            dataset_name=dataset_name,
            burn_set_name=burn_set_name,
            scope="burn_set",
        ),
        sorter._calibration_profiles_root()
        / sorter._profile_filename(
            camera_used=camera_used,
            dataset_name=dataset_name,
            scope="dataset",
        ),
        sorter._calibration_profiles_root()
        / sorter._profile_filename(camera_used=camera_used, scope="camera_default"),
    ]
    for candidate_path in candidate_paths:
        if not candidate_path.exists():
            continue
        with open(candidate_path, "r", encoding="utf-8") as profile_file:
            profile = json.load(profile_file)
        valid, reasons = sorter.validate_calibration_profile(profile)
        return {
            "path": str(candidate_path),
            "valid": bool(valid),
            "reasons": list(reasons),
            "selected_model": profile.get("selected_model", ""),
        }

    return {"path": "", "valid": False, "reasons": ["profile_missing"], "selected_model": ""}


def save_rgb_jpg(image: Image.Image, output_path: Path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(output_path, quality=JPG_QUALITY)


def thermal_preview_image(pair: dict, sorter, output_size=OUTPUT_SIZE) -> Image.Image:
    preview_path = None
    if pair.get("thermal_jpg"):
        preview_path = pair["thermal_jpg"].get("filepath")
    if preview_path and Path(preview_path).exists():
        with Image.open(preview_path) as image:
            return image.convert("RGB").resize(output_size, Image.BICUBIC)

    thermal_path, _ = sorter._select_corrected_fov_thermal_source(pair)
    if thermal_path and Path(thermal_path).exists():
        with Image.open(thermal_path) as image:
            if image.mode in {"RGB", "RGBA"}:
                return image.convert("RGB").resize(output_size, Image.BICUBIC)
            normalized = ImageOps.autocontrast(image.convert("L")).convert("RGB")
            return normalized.resize(output_size, Image.BICUBIC)

    return Image.new("RGB", output_size, (0, 0, 0))


def overlay_image(rgb_image: Image.Image, thermal_image: Image.Image) -> Image.Image:
    return Image.blend(
        rgb_image.convert("RGB").resize(OUTPUT_SIZE, Image.BICUBIC),
        thermal_image.convert("RGB").resize(OUTPUT_SIZE, Image.BICUBIC),
        0.5,
    )


def labeled_panel(image: Image.Image, label: str) -> Image.Image:
    panel = image.convert("RGB").resize(OUTPUT_SIZE, Image.BICUBIC)
    label_height = 34
    output = Image.new("RGB", (OUTPUT_SIZE[0], OUTPUT_SIZE[1] + label_height), (0, 0, 0))
    output.paste(panel, (0, label_height))
    draw = ImageDraw.Draw(output)
    draw.rectangle((0, 0, output.width, label_height), fill=(0, 0, 0))
    draw.text((10, 9), label, fill=(255, 255, 255))
    return output


def save_side_by_side(panels: list[tuple[str, Image.Image]], output_path: Path):
    labeled = [labeled_panel(image, label) for label, image in panels]
    separator_width = 8
    width = sum(panel.width for panel in labeled) + separator_width * (len(labeled) - 1)
    height = max(panel.height for panel in labeled)
    output = Image.new("RGB", (width, height), (0, 0, 0))
    x = 0
    for panel in labeled:
        output.paste(panel, (x, 0))
        x += panel.width + separator_width
    save_rgb_jpg(output, output_path)


def dilate_mask(mask: np.ndarray, sorter) -> np.ndarray:
    mask = np.asarray(mask, dtype=bool)
    if RGB_FIRE_MASK_DILATE_PX <= 0:
        return mask

    sorter_cv2 = getattr(sorter, "cv2", None) or cv2
    if sorter_cv2 is not None:
        kernel_size = (RGB_FIRE_MASK_DILATE_PX * 2) + 1
        kernel = sorter_cv2.getStructuringElement(
            sorter_cv2.MORPH_ELLIPSE,
            (kernel_size, kernel_size),
        )
        return sorter_cv2.dilate(mask.astype(np.uint8) * 255, kernel) > 0

    mask_image = Image.fromarray(mask.astype(np.uint8) * 255)
    return np.asarray(mask_image.filter(ImageFilter.MaxFilter((RGB_FIRE_MASK_DILATE_PX * 2) + 1))) > 0


def connected_components(mask: np.ndarray, sorter):
    mask = np.asarray(mask, dtype=bool)
    min_area = int(round(mask.size * THERMAL_FIRE_MIN_BLOB_AREA_FRAC))
    sorter_cv2 = getattr(sorter, "cv2", None) or cv2
    if sorter_cv2 is None:
        area = int(np.count_nonzero(mask))
        return [mask] if area >= min_area else []

    component_count, labels, stats, _ = sorter_cv2.connectedComponentsWithStats(
        mask.astype(np.uint8),
        connectivity=8,
    )
    components = []
    for component_id in range(1, component_count):
        area = int(stats[component_id, sorter_cv2.CC_STAT_AREA])
        if area >= min_area:
            components.append(labels == component_id)
    return components


def final_image_fire_gate(sorter, rgb_image: Image.Image, thermal_source_path: str | None):
    result = {
        "rejected": False,
        "reason": "no_thermal_fire_blobs",
        "score": "",
        "jaccard": "",
        "thermal_fire_blob_count": 0,
        "min_blob_rgb_coverage": "",
        "thermal_fire_unmatched": False,
        "thermal_status": "",
        "rgb_status": "",
    }
    if not thermal_source_path:
        result["reason"] = "thermal_source_missing"
        return result

    thermal_mask, thermal_metrics = sorter._thermal_fire_mask_from_path(
        thermal_source_path,
        OUTPUT_SIZE,
    )
    result["thermal_status"] = thermal_metrics.get("status", "")
    if thermal_mask is None:
        result["reason"] = result["thermal_status"] or "no_thermal_fire_blobs"
        return result

    components = connected_components(thermal_mask, sorter)
    result["thermal_fire_blob_count"] = len(components)
    if not components:
        result["reason"] = "no_thermal_fire_blobs_after_area_filter"
        return result

    rgb_mask, rgb_metrics = sorter._rgb_fire_mask_from_image(rgb_image)
    result["rgb_status"] = rgb_metrics.get("status", "")
    if rgb_mask is None:
        fire_metrics = {"status": "thermal_fire_unmatched_in_rgb"}
        result.update(
            {
                "rejected": bool(sorter._fire_gate_rejects(fire_metrics)),
                "reason": "thermal_fire_unmatched_in_rgb",
                "score": "0.0000",
                "jaccard": "0.0000",
                "min_blob_rgb_coverage": "0.0000",
                "thermal_fire_unmatched": True,
            }
        )
        return result

    overlap_scores = sorter._fire_overlap_scores(thermal_mask, rgb_mask)
    overlap_score = float(overlap_scores.get("thermal_overlap", 0.0))
    result["score"] = f"{overlap_score:.4f}"
    result["jaccard"] = f"{float(overlap_scores.get('jaccard', 0.0)):.4f}"

    dilated_rgb_mask = dilate_mask(rgb_mask, sorter)
    coverages = []
    for component in components:
        area = int(np.count_nonzero(component))
        if area <= 0:
            continue
        coverage = float(np.count_nonzero(component & dilated_rgb_mask) / float(area))
        coverages.append(coverage)

    if not coverages:
        result["reason"] = "no_thermal_fire_blobs_after_area_filter"
        return result

    min_coverage = min(coverages)
    result["min_blob_rgb_coverage"] = f"{min_coverage:.4f}"
    low_overlap_threshold = float(getattr(sorter, "FIRE_ALIGNMENT_LOW_OVERLAP_REJECT", RGB_FIRE_COVERAGE_MIN))
    if min_coverage < RGB_FIRE_COVERAGE_MIN or overlap_score < low_overlap_threshold:
        fire_metrics = {"status": "fire_overlap_low_unresolved"}
        result.update(
            {
                "rejected": bool(sorter._fire_gate_rejects(fire_metrics)),
                "reason": "fire_overlap_low_unresolved",
                "thermal_fire_unmatched": True,
            }
        )
    else:
        result["reason"] = "fire_gate_passed"
    return result


def alignment_status(debug_info: dict) -> dict:
    alignment = debug_info.get("feature_alignment", {}) or {}
    return {
        "status": alignment.get("status", ""),
        "confidence": alignment.get("confidence_level", ""),
        "inliers": alignment.get("inliers", ""),
        "reprojection_error": (
            ""
            if alignment.get("mean_reprojection_error_px") is None
            else f"{float(alignment['mean_reprojection_error_px']):.4f}"
        ),
        "matrix": alignment.get("matrix") or debug_info.get("final_transform_matrix"),
        "scale_x": alignment.get("scale_x", 1.0),
        "scale_y": alignment.get("scale_y", 1.0),
        "translation_x": alignment.get("translation_x", 0.0),
        "translation_y": alignment.get("translation_y", 0.0),
        "fallback_used": alignment.get("fallback_used", ""),
        "accepted": alignment.get("accepted", False),
    }


def auto_align_fell_back_to_identity(debug_info: dict) -> bool:
    alignment = alignment_status(debug_info)
    try:
        matrix = np.asarray(alignment["matrix"], dtype=np.float32)
    except (TypeError, ValueError):
        matrix = np.eye(3, dtype=np.float32)

    identity_like = (
        matrix.shape == (3, 3)
        and np.allclose(matrix, np.eye(3, dtype=np.float32), atol=1e-5)
    )
    geometry_identity_like = (
        abs(float(alignment["scale_x"]) - 1.0) < 1e-5
        and abs(float(alignment["scale_y"]) - 1.0) < 1e-5
        and abs(float(alignment["translation_x"])) < 1e-5
        and abs(float(alignment["translation_y"])) < 1e-5
    )
    sift_not_accepted = not bool(alignment["accepted"])
    fallback = str(alignment["fallback_used"] or "")
    return bool((identity_like or geometry_identity_like) and (sift_not_accepted or fallback == "crop_only"))


def mode_recommendation(auto_gate: dict, calibration_gate: dict) -> str:
    auto_passed = not auto_gate["rejected"]
    calibration_passed = not calibration_gate["rejected"]
    if auto_passed and calibration_passed:
        return "agree_pass"
    if not auto_passed and not calibration_passed:
        return "agree_reject"
    if auto_passed:
        return "auto_better"
    return "calibration_better"


def pair_record_filename(pair: dict, key: str) -> str:
    record = pair.get(key) or {}
    return record.get("filename", "")


def process_pair(sorter, dataset: dict, burn_set: dict, pair_index: int, pair: dict, output_dir: Path):
    pair_id = f"{pair_index:05d}"
    pair["dataset_name"] = dataset["name"]
    pair["burn_set_name"] = burn_set["name"]
    pair["detected_camera"] = burn_set.get("detected_camera")

    thermal_source_path, _ = sorter._select_corrected_fov_thermal_source(pair)
    thermal_image = thermal_preview_image(pair, sorter)

    auto_image, auto_debug = sorter.generate_corrected_fov(
        pair,
        mode="AUTO_ALIGN",
        dataset_name=dataset["name"],
        burn_set_name=burn_set["name"],
        camera_used=burn_set.get("detected_camera"),
        return_debug_info=True,
    )
    calibration_image, calibration_debug = sorter.generate_corrected_fov(
        pair,
        mode="CALIBRATION_PROFILE",
        dataset_name=dataset["name"],
        burn_set_name=burn_set["name"],
        camera_used=burn_set.get("detected_camera"),
        return_debug_info=True,
    )

    auto_gate = final_image_fire_gate(sorter, auto_image, thermal_source_path)
    calibration_gate = final_image_fire_gate(sorter, calibration_image, thermal_source_path)
    auto_alignment = alignment_status(auto_debug)
    identity_fallback = auto_align_fell_back_to_identity(auto_debug)
    recommendation = mode_recommendation(auto_gate, calibration_gate)

    auto_output = output_dir / f"{pair_id}_auto_align.jpg"
    calibration_output = output_dir / f"{pair_id}_calibration.jpg"
    thermal_output = output_dir / f"{pair_id}_thermal.jpg"
    overlay_auto = overlay_image(auto_image, thermal_image)
    overlay_calibration = overlay_image(calibration_image, thermal_image)

    save_rgb_jpg(auto_image, auto_output)
    save_rgb_jpg(calibration_image, calibration_output)
    save_rgb_jpg(thermal_image, thermal_output)
    save_rgb_jpg(overlay_auto, output_dir / f"{pair_id}_overlay_auto.jpg")
    save_rgb_jpg(overlay_calibration, output_dir / f"{pair_id}_overlay_calibration.jpg")
    save_side_by_side(
        [
            ("AUTO_ALIGN", auto_image),
            ("CALIBRATION_PROFILE", calibration_image),
            ("Thermal", thermal_image),
            ("AUTO overlay", overlay_auto),
            ("Calibration overlay", overlay_calibration),
        ],
        output_dir / f"{pair_id}_sidebyside.jpg",
    )

    auto_image.close()
    calibration_image.close()
    thermal_image.close()
    overlay_auto.close()
    overlay_calibration.close()

    thermal_filename = (
        pair_record_filename(pair, "cal_tiff")
        or pair_record_filename(pair, "thermal_tiff")
        or pair_record_filename(pair, "thermal_jpg")
    )
    return {
        "pair_id": pair_id,
        "rgb_filename": pair_record_filename(pair, "rgb"),
        "thermal_filename": thermal_filename,
        "auto_align_status": auto_alignment["status"],
        "auto_align_confidence": auto_alignment["confidence"],
        "auto_align_inliers": auto_alignment["inliers"],
        "auto_align_reprojection_error": auto_alignment["reprojection_error"],
        "auto_align_fire_overlap_score": auto_gate["score"],
        "auto_align_fire_gate_rejected": str(bool(auto_gate["rejected"])),
        "auto_align_fire_gate_reason": auto_gate["reason"],
        "calibration_status": calibration_debug.get("selected_model", "calibration_profile"),
        "calibration_fire_overlap_score": calibration_gate["score"],
        "calibration_fire_gate_rejected": str(bool(calibration_gate["rejected"])),
        "calibration_fire_gate_reason": calibration_gate["reason"],
        "auto_align_fell_back_to_identity": str(bool(identity_fallback)),
        "mode_recommendation": recommendation,
        "thermal_fire_blob_count": auto_gate["thermal_fire_blob_count"],
        "auto_min_blob_rgb_coverage": auto_gate["min_blob_rgb_coverage"],
        "calibration_min_blob_rgb_coverage": calibration_gate["min_blob_rgb_coverage"],
        "auto_selected_model": auto_debug.get("selected_model", ""),
        "calibration_selected_model": calibration_debug.get("selected_model", ""),
    }


def write_metrics_csv(rows: list[dict], output_path: Path):
    fieldnames = [
        "pair_id",
        "rgb_filename",
        "thermal_filename",
        "auto_align_status",
        "auto_align_confidence",
        "auto_align_inliers",
        "auto_align_reprojection_error",
        "auto_align_fire_overlap_score",
        "auto_align_fire_gate_rejected",
        "auto_align_fire_gate_reason",
        "calibration_status",
        "calibration_fire_overlap_score",
        "calibration_fire_gate_rejected",
        "calibration_fire_gate_reason",
        "auto_align_fell_back_to_identity",
        "mode_recommendation",
        "thermal_fire_blob_count",
        "auto_min_blob_rgb_coverage",
        "calibration_min_blob_rgb_coverage",
        "auto_selected_model",
        "calibration_selected_model",
    ]
    with open(output_path, "w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verdict_for_rows(rows: list[dict]) -> str:
    tally = Counter(row["mode_recommendation"] for row in rows)
    agree_reject_auto_identity = sum(
        1
        for row in rows
        if row["mode_recommendation"] == "agree_reject"
        and row["auto_align_fell_back_to_identity"] == "True"
    )
    calibration_support = tally["calibration_better"] + tally["agree_pass"]
    auto_support = tally["auto_better"] + agree_reject_auto_identity
    if tally["calibration_better"] > tally["auto_better"] and calibration_support >= 2 * max(auto_support, 1):
        return "switch_to_calibration_profile"
    if tally["auto_better"] >= 2 * max(tally["calibration_better"], 1):
        return "keep_auto_align"
    return "inconclusive_needs_more_data"


def write_summary(
    rows: list[dict],
    output_path: Path,
    dataset: dict,
    run_dir: Path,
    sample_count: int,
    seed: int,
    input_path: Path,
    calibration_profile_path: str,
    calibration_profile_statuses: list[dict],
    metrics_sha256: str,
):
    tally = Counter(row["mode_recommendation"] for row in rows)
    auto_passed = sum(row["auto_align_fire_gate_rejected"] == "False" for row in rows)
    calibration_passed = sum(row["calibration_fire_gate_rejected"] == "False" for row in rows)
    both_passed = sum(
        row["auto_align_fire_gate_rejected"] == "False"
        and row["calibration_fire_gate_rejected"] == "False"
        for row in rows
    )
    neither_passed = sum(
        row["auto_align_fire_gate_rejected"] == "True"
        and row["calibration_fire_gate_rejected"] == "True"
        for row in rows
    )
    auto_identity = sum(row["auto_align_fell_back_to_identity"] == "True" for row in rows)
    auto_identity_cal_valid = [
        row
        for row in rows
        if row["auto_align_fell_back_to_identity"] == "True"
        and row["calibration_fire_gate_rejected"] == "False"
    ]
    calibration_failed_auto_passed = [
        row
        for row in rows
        if row["calibration_fire_gate_rejected"] == "True"
        and row["auto_align_fire_gate_rejected"] == "False"
    ]
    calibration_runtime_models = sorted({row["calibration_selected_model"] for row in rows})
    calibration_profile_valid = any(status.get("valid") for status in calibration_profile_statuses)
    calibration_runtime_fell_to_crop_only = calibration_runtime_models == ["crop_only"]
    if not calibration_profile_valid or calibration_runtime_fell_to_crop_only:
        verdict = "inconclusive_needs_more_data"
        verdict_note = (
            "CALIBRATION_PROFILE did not run a valid stored calibration matrix; "
            "the current profile was missing/invalid or runtime fell back to crop_only."
        )
    else:
        verdict = verdict_for_rows(rows)
        verdict_note = "Verdict computed from fire-gate pass/fail counts."

    lines = [
        f"# FOV Mode Comparison - {dataset['name']}",
        "",
        f"Top-line verdict: **{verdict}**",
        "",
        f"Verdict note: {verdict_note}",
        "",
        "## Run Config",
        "",
        f"- Dataset path: `{input_path}`",
        f"- Run folder: `{run_dir}`",
        f"- Sample count requested: `{sample_count}`",
        f"- Seed: `{seed}`",
        f"- Calibration file used: `{calibration_profile_path or 'none'}`",
        f"- CALIBRATION_PROFILE runtime selected models: `{', '.join(calibration_runtime_models)}`",
        f"- Metrics SHA256: `{metrics_sha256}`",
        "",
        "## Calibration Profile Status",
        "",
    ]
    for status in calibration_profile_statuses:
        lines.append(
            "- "
            + f"path=`{status.get('path') or 'none'}` "
            + f"valid=`{status.get('valid')}` "
            + f"selected_model=`{status.get('selected_model', '')}` "
            + f"reasons=`{' | '.join(status.get('reasons', []))}`"
        )
    lines.extend(
        [
        "",
        "## Counts",
        "",
        f"- Pairs sampled: `{len(rows)}`",
        f"- AUTO_ALIGN passed fire gate: `{auto_passed}`",
        f"- CALIBRATION_PROFILE passed fire gate: `{calibration_passed}`",
        f"- Both passed: `{both_passed}`",
        f"- Neither passed: `{neither_passed}`",
        f"- AUTO_ALIGN fell back to identity: `{auto_identity}`",
        "",
        "## Mode Recommendation Tally",
        "",
        f"- agree_pass: `{tally['agree_pass']}`",
        f"- agree_reject: `{tally['agree_reject']}`",
        f"- auto_better: `{tally['auto_better']}`",
        f"- calibration_better: `{tally['calibration_better']}`",
        "",
        "## AUTO_ALIGN Identity Fallback But Calibration Passed",
        "",
        ]
    )
    if auto_identity_cal_valid:
        lines.extend(
            f"- `{row['pair_id']}` {row['rgb_filename']} -> {row['thermal_filename']}"
            for row in auto_identity_cal_valid
        )
    else:
        lines.append("- None")

    lines.extend(["", "## Calibration Failed Fire Gate But AUTO_ALIGN Passed", ""])
    if calibration_failed_auto_passed:
        lines.extend(
            f"- `{row['pair_id']}` {row['rgb_filename']} -> {row['thermal_filename']}"
            for row in calibration_failed_auto_passed
        )
    else:
        lines.append("- None")

    lines.extend(["", "## Sampled Pair IDs", ""])
    lines.append(", ".join(f"`{row['pair_id']}`" for row in rows))
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return verdict


def parse_args():
    parser = argparse.ArgumentParser(
        description="Compare AUTO_ALIGN and CALIBRATION_PROFILE corrected FOV outputs.",
    )
    parser.add_argument(
        "--input",
        default=str(DEFAULT_DATASET_PATH),
        help="Dataset folder or Input Folder root. Defaults to Raw File Sorting/Input Folder/payson_test.",
    )
    parser.add_argument("--dataset-name", default=None, help="Dataset name when --input is an Input Folder root.")
    parser.add_argument("--sample-count", type=int, default=20)
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


def main():
    args = parse_args()
    sorter = load_sorter()
    input_path = Path(args.input).resolve()
    dataset = find_dataset_analysis(sorter, input_path, args.dataset_name)
    run_dir = unique_run_dir(RUNS_ROOT)

    rows = []
    calibration_profile_paths = []
    calibration_profile_statuses = []
    for burn_set in dataset.get("burn_sets", []):
        camera_used = burn_set.get("detected_camera")
        status = calibration_profile_status(sorter, dataset["name"], burn_set["name"], camera_used)
        calibration_profile_statuses.append(status)
        if status.get("path"):
            calibration_profile_paths.append(status["path"])

        burn_output_dir = run_dir / burn_set["name"]
        burn_output_dir.mkdir(parents=True, exist_ok=True)
        sampled = sampled_pairs_for_burn_set(sorter, burn_set, args.sample_count, args.seed)
        print(
            f"Processing {dataset['name']} / {burn_set['name']}: "
            f"{len(sampled)} sampled pair(s)"
        )
        for pair_index, pair in sampled:
            print(f"  pair {pair_index:05d}: {pair['rgb']['filename']}")
            rows.append(process_pair(sorter, dataset, burn_set, pair_index, pair, burn_output_dir))

    if not rows:
        raise RuntimeError("No sampled pairs were produced.")

    metrics_path = run_dir / "comparison_metrics.csv"
    write_metrics_csv(rows, metrics_path)
    metrics_hash = file_sha256(metrics_path)
    verdict = write_summary(
        rows,
        run_dir / "summary.md",
        dataset,
        run_dir,
        args.sample_count,
        args.seed,
        input_path,
        "; ".join(sorted(set(calibration_profile_paths))),
        calibration_profile_statuses,
        metrics_hash,
    )

    print("")
    print(f"Run folder: {run_dir}")
    print(f"Metrics: {metrics_path}")
    print(f"Summary: {run_dir / 'summary.md'}")
    print(f"Verdict: {verdict}")
    print(json.dumps(Counter(row["mode_recommendation"] for row in rows), indent=2))


if __name__ == "__main__":
    main()
