#### File name:     Raw File Sorting.py
#### Version:       1.0
#### Date:          02/19/2024
#### Creator:       Bryce Hopkins
#### Contact email: bryceh@clemson.edu
#### Purpose:       When input with some folders of raw M30T or M2EA image pairs and videos, this program will pair the videos,
####                pair the thermal images to the wide angle images if available, and regenerate the thermal images with a color
####                map (also creating tiffs). This is done for each sub folder in the input folder.
#### Instructions:  Specify input folder and output folder. The program operates assuming that there will be one layer of subfolders
####                in the input folder. Ex: Input Folder/Subfolders/Images&Videos. (or Burn/Plot/Media) The sorted images/videos will
####                be exported to appropriate output subfolders. Depending on number of images, program may take several minutes to
####                execute. Updates will be provided at cell output. NOTE: This program relies on wide angle images having "W" in the
####                filename and thermal images w/ "T" for the M30T and relies on image resolution for the M2EA. FOR THE M2EA, DO NOT
####                INPUT MORE RGB IMAGES THAN THERMALS.
####
#### WARNING:       This program has a known memory leak. As a result, it is not recommended to process >3000 image pairs at a time.
####                Largest working batch: 3000 image pairs - 40,000 MiB peak RAM usage (as reported by task manager) - 2 hour runtime

# import required dependencies
import csv
import datetime
import gc
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time

import numpy as np
from PIL import Image, ImageDraw, ImageOps

try:
    import cv2
except ImportError:
    cv2 = None


SCRIPT_DIR = Path(__file__).resolve().parent

# specify the input and output folder filenames
INPUT_FOLDER = "./Input Folder/"
OUTPUT_FOLDER = "./Output Folder/"
# Current valid options:
# - "AUTO": inspect the input folder and choose the appropriate workflow
# - "DJI_RAW": original workflow for M30T/M2EA RJPG inputs
# - "PRESORTED_STANDARD": existing RGB JPG + thermal JPG/TIFF/Cal TIFF folders
PROCESSING_MODE = "AUTO"
# Current valid options: "M2EA", "M30T"
CAMERA_USED = "M30T"
# Boolean that controls whether files will be renamed or not when placed in output folder
RENAME_FILES = True
OUTPUT_FILENAME_DIGITS = 5

# Can be set to last completed image pair number to resume image pair processing if interrupted.
RESUME_ID = 0

# PRESORTED_STANDARD mode settings
PRESORTED_RGB_DIRNAME = "raw_rgb_jpg"
PRESORTED_THERMAL_JPG_DIRNAME = "raw_thermal_jpg"
PRESORTED_THERMAL_TIFF_DIRNAME = "raw_thermal_tiff"
PRESORTED_CAL_TIFF_DIRNAME = "calibrated_thermal_tiff"
PRESORTED_PAIRING_LOG_FILENAME = "pairing_log.csv"
PRESORTED_PAIRING_REVIEW_FILENAME = "pairing_review.csv"
PAIR_TIME_TOLERANCE_SECONDS = 3.0
DRY_RUN_ONLY = False
HIGH_CONFIDENCE_THRESHOLD = 80.0
MEDIUM_CONFIDENCE_THRESHOLD = 55.0

CORRECTED_FOV_OUTPUT_SIZE = (640, 512)
# Production Corrected FOV now uses guarded automatic alignment. AUTO_ALIGN
# saves the same aligned RGB candidate that appears in the debug overlay when
# confidence is HIGH; otherwise it falls back to the crop-only safety baseline.
FOV_CORRECTION_MODE = "AUTO_ALIGN"
VALID_FOV_CORRECTION_MODES = {
    "CROP_ONLY",
    "CALIBRATION_PROFILE",
    "EXPERIMENTAL_SIFT",
    "AUTO_ALIGN",
    "AUTO_SIFT_CALIBRATED",
}
# Fractional crop tightening used by AUTO_ALIGN-style modes. This trims extra
# scene content before feature matching so SIFT does not learn from regions
# outside the thermal FOV. CROP_ONLY remains the unshrunk safety baseline.
CROP_SHRINK_LEFT = 0.06
CROP_SHRINK_RIGHT = 0.02
CROP_SHRINK_TOP = 0.00
CROP_SHRINK_BOTTOM = 0.00
FEATURE_ALIGNMENT_MODEL = "auto"
FEATURE_ALIGNMENT_MODEL_ORDER = ["similarity", "affine"]
FEATURE_ALIGNMENT_ENABLE_HOMOGRAPHY = False
FEATURE_ALIGNMENT_PREPROCESSING_VARIANTS = [
    "clahe",
    "edge_blend",
    "sobel",
    "canny",
    "thermal_inverted_clahe",
]
FEATURE_ALIGNMENT_USE_EDGE_BLEND = True
FEATURE_ALIGNMENT_EDGE_BLEND_WEIGHT = 0.35
FEATURE_ALIGNMENT_MIN_GOOD_MATCHES = 20
FEATURE_ALIGNMENT_MIN_INLIERS = 12
FEATURE_ALIGNMENT_MIN_INLIER_RATIO = 0.35
FEATURE_ALIGNMENT_GRID_SIZE = (4, 4)
FEATURE_ALIGNMENT_MAX_MATCHES_PER_GRID_CELL = 8
FEATURE_ALIGNMENT_MIN_MATCH_GRID_CELLS = 4
FEATURE_ALIGNMENT_MIN_INLIER_GRID_CELLS = 3
FEATURE_ALIGNMENT_MAX_MEAN_REPROJECTION_ERROR_PX = 8.0
FEATURE_ALIGNMENT_MAX_HIGH_CONFIDENCE_REPROJECTION_ERROR_PX = 5.0
FEATURE_ALIGNMENT_MIN_SCALE = 0.45
FEATURE_ALIGNMENT_MAX_SCALE = 1.90
FEATURE_ALIGNMENT_MAX_TRANSLATION_FRACTION = 0.45
FEATURE_ALIGNMENT_MAX_SKEW_DOT = 0.55
FEATURE_ALIGNMENT_RATIO_TEST = 0.75
FEATURE_ALIGNMENT_USE_ECC_REFINEMENT = False
FEATURE_ALIGNMENT_ECC_MAX_ITERATIONS = 80
FEATURE_ALIGNMENT_ECC_EPSILON = 1e-5
CORRECTION_VALIDATION_SAMPLE_COUNT = 20
CORRECTION_VALIDATION_DIRNAME = "correction_validation"
VISUAL_ALIGNMENT_REVIEW_DEFAULT = "visually_better_unknown"
CALIBRATION_PROFILES_DIRNAME = "Calibration Profiles"
INVALID_CALIBRATION_PROFILES_DIRNAME = "Invalid Calibration Profiles"
QUARANTINE_INVALID_CALIBRATION_PROFILES = False
CALIBRATION_PROFILE_VERSION = 1
CALIBRATION_MODEL_SELECTION_ABSOLUTE_TOLERANCE_PX = 1.5
CALIBRATION_MODEL_SELECTION_RELATIVE_TOLERANCE = 1.10
CALIBRATION_ACCEPTABLE_RMSE_PX = 8.0
CALIBRATION_RANSAC_REPROJECTION_THRESHOLD_PX = 5.0
CALIBRATION_HOMOGRAPHY_RANSAC_THRESHOLDS_PX = [5.0, 8.0, 12.0, 20.0]
CALIBRATION_HOMOGRAPHY_MIN_RMSE_IMPROVEMENT_PX = 0.5
CALIBRATION_HOMOGRAPHY_MIN_MAX_ERROR_IMPROVEMENT_PX = 1.0
CALIBRATION_HOMOGRAPHY_MIN_AREA_RATIO = 0.25
CALIBRATION_HOMOGRAPHY_MAX_AREA_RATIO = 4.00
CALIBRATION_HOMOGRAPHY_MAX_CORNER_EXTENSION_FRACTION = 1.00
CALIBRATION_MIN_POINTS = {
    "crop_only": 1,
    "translation": 1,
    "scale_translate": 2,
    "affine": 3,
    "homography": 4,
}
CALIBRATION_MODEL_ORDER = [
    "crop_only",
    "translation",
    "scale_translate",
    "affine",
    "homography",
]
CALIBRATION_MODELS_WITH_MATRIX = {"translation", "scale_translate", "affine", "homography"}

# Fixed baseline crop. This is only the approximate thermal FOV region.
# Any additional alignment is applied later through a saved geometric calibration profile.
CAMERA_BASELINE_CROP_BOXES = {
    "M30T": {
        "crop_left": 620,
        "crop_top": 454,
        "crop_right": 3248,
        "crop_bottom": 2486,
    },
    "M2EA": {
        "crop_left": 1360,
        "crop_top": 824,
        "crop_right": 6800,
        "crop_bottom": 5176,
    },
}

CAMERA_RESOLUTION_HINTS = {
    "M30T": {
        "target": (4000, 3000),
        "width_range": (3600, 4400),
        "height_range": (2600, 3400),
    },
    "M2EA": {
        "target": (8000, 6000),
        "width_range": (7200, 8400),
        "height_range": (5200, 6400),
    },
}

CAMERA_EXIF_HINTS = {
    "M30T": ["M30T", "MATRICE 30T", "MATRICE30T", "M30 THERMAL"],
    "M2EA": ["M2EA", "MAVIC 2 ENTERPRISE ADVANCED", "MAVIC2 ENTERPRISE ADVANCED"],
}

# The thermal hot-mask centroid heuristic is retained only as an explicit experiment.
# It is not geometric registration and must not be treated as the default alignment path.
EXPERIMENTAL_THERMAL_SHIFT_ENABLED = False
EXPORT_ALIGNMENT_DEBUG_SAMPLES = False
ALIGNMENT_DEBUG_SAMPLE_COUNT = 5
ALIGNMENT_DEBUG_DIRNAME = "alignment_debug"


def configure_runtime():
    global INPUT_FOLDER
    global OUTPUT_FOLDER
    global PROCESSING_MODE

    INPUT_FOLDER = str((SCRIPT_DIR / INPUT_FOLDER).resolve())
    OUTPUT_FOLDER = str((SCRIPT_DIR / OUTPUT_FOLDER).resolve())
    if PROCESSING_MODE not in {"AUTO", "DJI_RAW", "PRESORTED_STANDARD"}:
        PROCESSING_MODE = "AUTO"

    print("Runtime configuration")
    print(f"Script directory: {SCRIPT_DIR}")
    print(f"Input folder: {INPUT_FOLDER}")
    print(f"Output folder: {OUTPUT_FOLDER}")
    print(f"Processing mode: {PROCESSING_MODE}")

try:
    import exif as EXIF
except ImportError:
    EXIF = None

DJI = None
rjpeg_to_heatmap = None
plt = None
sns = None
get_video_properties = None
psutil = None


def _load_dji_dependencies():
    global DJI
    global rjpeg_to_heatmap
    global plt
    global sns
    global get_video_properties
    global psutil

    if (
        DJI is not None
        and rjpeg_to_heatmap is not None
        and plt is not None
        and sns is not None
        and get_video_properties is not None
    ):
        return

    try:
        from dji_thermal_sdk.utility import rjpeg_to_heatmap as imported_rjpeg_to_heatmap
        import dji_thermal_sdk.dji_sdk as imported_dji
        import matplotlib.pyplot as imported_plt
        import seaborn as imported_sns
        from videoprops import get_video_properties as imported_get_video_properties
        import psutil as imported_psutil
    except ImportError as exc:
        print(
            "DJI-specific dependencies could not be imported. "
            "Use PROCESSING_MODE='PRESORTED_STANDARD' for standard JPG/TIFF datasets."
        )
        raise exc

    DJI = imported_dji
    rjpeg_to_heatmap = imported_rjpeg_to_heatmap
    plt = imported_plt
    sns = imported_sns
    get_video_properties = imported_get_video_properties
    psutil = imported_psutil


def _extract_capture_datetime(filepath):
    ext = os.path.splitext(filepath)[1].lower()
    try:
        with Image.open(filepath) as img:
            exif = img.getexif()
            dt_value = exif.get(36867) or exif.get(36868) or exif.get(306)
            if dt_value:
                return datetime.datetime.strptime(str(dt_value), "%Y:%m:%d %H:%M:%S")
    except Exception:
        pass

    return datetime.datetime.fromtimestamp(os.path.getmtime(filepath))


def _numeric_suffix(filename):
    stem = os.path.splitext(os.path.basename(filename))[0]
    match = re.search(r"(\d+)(?=[^0-9]*$)", stem)
    return int(match.group(1)) if match else None


def _copy_if_exists(src, dst):
    if src and os.path.exists(src):
        shutil.copy(src, dst)


def _ensure_gitkeep(directory):
    if os.path.isdir(directory):
        gitkeep_path = os.path.join(directory, ".gitkeep")
        if not os.path.exists(gitkeep_path):
            with open(gitkeep_path, "w", encoding="utf-8"):
                pass


def _meaningful_directory_entries(directory):
    if not os.path.isdir(directory):
        return []
    return [entry for entry in os.listdir(directory) if entry != ".gitkeep"]


def _calibration_profiles_root():
    profiles_root = SCRIPT_DIR / CALIBRATION_PROFILES_DIRNAME
    profiles_root.mkdir(parents=True, exist_ok=True)
    return profiles_root


def _sanitize_identifier(text):
    if text is None:
        return ""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", str(text)).strip("._-")
    return cleaned or "default"


def _camera_used(camera_used=None):
    return camera_used or CAMERA_USED


def _get_output_size():
    return tuple(int(value) for value in CORRECTED_FOV_OUTPUT_SIZE)


def _get_fov_correction_mode():
    mode = str(FOV_CORRECTION_MODE).upper()
    if mode not in VALID_FOV_CORRECTION_MODES:
        return "CROP_ONLY"
    return mode


def _mode_uses_feature_alignment(mode=None):
    effective_mode = _get_fov_correction_mode() if mode is None else str(mode).upper()
    return effective_mode in {"EXPERIMENTAL_SIFT", "AUTO_ALIGN", "AUTO_SIFT_CALIBRATED"}


def _mode_allows_profile_fallback(mode=None):
    effective_mode = _get_fov_correction_mode() if mode is None else str(mode).upper()
    return effective_mode in {"EXPERIMENTAL_SIFT", "AUTO_ALIGN", "AUTO_SIFT_CALIBRATED"}


def _get_baseline_crop_parameters(camera_used=None):
    camera_name = _camera_used(camera_used)
    parameters = CAMERA_BASELINE_CROP_BOXES.get(camera_name)
    if parameters is None:
        raise ValueError(f"Unsupported camera profile: {camera_name}")
    return dict(parameters)


def _scale_crop_box(crop_box, from_size, to_size):
    if from_size == to_size:
        return tuple(int(value) for value in crop_box)

    from_width, from_height = from_size
    to_width, to_height = to_size
    scale_x = to_width / float(from_width)
    scale_y = to_height / float(from_height)
    return (
        int(round(crop_box[0] * scale_x)),
        int(round(crop_box[1] * scale_y)),
        int(round(crop_box[2] * scale_x)),
        int(round(crop_box[3] * scale_y)),
    )


def _get_base_crop_box(image_size, camera_used=None, calibration_profile=None):
    width, height = image_size
    if calibration_profile and calibration_profile.get("baseline_crop_box"):
        profile_crop_box = tuple(
            int(calibration_profile["baseline_crop_box"][key])
            for key in ("left", "top", "right", "bottom")
        )
        profile_source_size = tuple(
            int(value) for value in calibration_profile.get("source_rgb_size", image_size)
        )
        scaled_profile_crop_box = _scale_crop_box(profile_crop_box, profile_source_size, image_size)
        return _clamp_crop_box(*scaled_profile_crop_box, width, height)

    parameters = _get_baseline_crop_parameters(camera_used=camera_used)
    return _clamp_crop_box(
        parameters["crop_left"],
        parameters["crop_top"],
        parameters["crop_right"],
        parameters["crop_bottom"],
        width,
        height,
    )


def _clamp_crop_box(left, top, right, bottom, width, height):
    if left < 0:
        right -= left
        left = 0
    if top < 0:
        bottom -= top
        top = 0
    if right > width:
        left -= (right - width)
        right = width
    if bottom > height:
        top -= (bottom - height)
        bottom = height

    left = max(0, left)
    top = max(0, top)
    right = min(width, right)
    bottom = min(height, bottom)
    return (int(left), int(top), int(right), int(bottom))


def _apply_crop_shrink(crop_box, image_size, mode=None):
    if not _mode_uses_feature_alignment(mode):
        return tuple(int(value) for value in crop_box), {
            "left": 0.0,
            "right": 0.0,
            "top": 0.0,
            "bottom": 0.0,
        }

    width, height = image_size
    left, top, right, bottom = crop_box
    crop_width = max(right - left, 1)
    crop_height = max(bottom - top, 1)
    shrunk_box = _clamp_crop_box(
        left + int(round(crop_width * CROP_SHRINK_LEFT)),
        top + int(round(crop_height * CROP_SHRINK_TOP)),
        right - int(round(crop_width * CROP_SHRINK_RIGHT)),
        bottom - int(round(crop_height * CROP_SHRINK_BOTTOM)),
        width,
        height,
    )

    if shrunk_box[2] <= shrunk_box[0] or shrunk_box[3] <= shrunk_box[1]:
        return tuple(int(value) for value in crop_box), {
            "left": 0.0,
            "right": 0.0,
            "top": 0.0,
            "bottom": 0.0,
        }

    return shrunk_box, {
        "left": float(CROP_SHRINK_LEFT),
        "right": float(CROP_SHRINK_RIGHT),
        "top": float(CROP_SHRINK_TOP),
        "bottom": float(CROP_SHRINK_BOTTOM),
    }


def _estimate_thermal_alignment_shift(thermal_source_path, crop_width, crop_height):
    if not thermal_source_path or not os.path.exists(thermal_source_path):
        return (0, 0)

    try:
        thermal_img = Image.open(thermal_source_path)
        arr = np.array(thermal_img)
        thermal_img.close()
    except Exception:
        return (0, 0)

    if arr.ndim == 3:
        arr = arr.mean(axis=2)
    arr = arr.astype("float32")
    if arr.size == 0:
        return (0, 0)

    # Estimate the active thermal region from the hottest pixels.
    threshold = np.percentile(arr, 95.0)
    hot_mask = arr >= threshold
    if hot_mask.sum() < 10:
        threshold = np.percentile(arr, 90.0)
        hot_mask = arr >= threshold
    if hot_mask.sum() < 10:
        return (0, 0)

    ys, xs = np.nonzero(hot_mask)
    centroid_x = float(xs.mean())
    centroid_y = float(ys.mean())

    thermal_height, thermal_width = arr.shape[:2]
    delta_x_norm = (centroid_x - (thermal_width / 2.0)) / float(thermal_width)
    delta_y_norm = (centroid_y - (thermal_height / 2.0)) / float(thermal_height)

    # Scale the thermal offset into RGB crop-space shift.
    shift_x = int(delta_x_norm * crop_width * 0.8)
    shift_y = int(delta_y_norm * crop_height * 0.8)
    return (shift_x, shift_y)


def _identity_transform_matrix():
    return np.eye(3, dtype=np.float32)


def _matrix_to_list(matrix):
    return [[float(value) for value in row] for row in np.asarray(matrix, dtype=np.float32).tolist()]


def _list_to_matrix(matrix_values):
    if matrix_values is None:
        return _identity_transform_matrix()
    return np.asarray(matrix_values, dtype=np.float32)


def _transform_points(points, matrix):
    if len(points) == 0:
        return np.zeros((0, 2), dtype=np.float32)
    homogenous = np.hstack([points.astype(np.float32), np.ones((len(points), 1), dtype=np.float32)])
    mapped = homogenous @ np.asarray(matrix, dtype=np.float32).T
    mapped[:, 0] /= mapped[:, 2]
    mapped[:, 1] /= mapped[:, 2]
    return mapped[:, :2]


def _rmse_from_errors(errors):
    if len(errors) == 0:
        return None
    return float(np.sqrt(np.mean(np.square(errors))))


def _model_summary(model_name, matrix, source_points, target_points, point_ids=None, estimation_details=None):
    predicted = _transform_points(source_points, matrix)
    deltas = predicted - target_points
    errors = np.linalg.norm(deltas, axis=1)
    summary = {
        "name": model_name,
        "available": True,
        "matrix": _matrix_to_list(matrix),
        "rmse": _rmse_from_errors(errors),
        "mean_error": float(np.mean(errors)) if len(errors) else None,
        "max_error": float(np.max(errors)) if len(errors) else None,
        "point_count": int(len(source_points)),
        "per_point_error": [
            {
                "point_id": point_ids[index] if point_ids else str(index + 1),
                "error": float(errors[index]),
            }
            for index in range(len(errors))
        ],
    }
    if estimation_details:
        summary.update(estimation_details)
    return summary


def _inlier_details(inliers, point_count, ransac_threshold=None):
    if inliers is None:
        inlier_count = point_count
    else:
        inlier_count = int(np.count_nonzero(inliers))
    return {
        "inlier_count": inlier_count,
        "inlier_ratio": float(inlier_count / max(point_count, 1)),
        "ransac_reprojection_threshold_px": (
            CALIBRATION_RANSAC_REPROJECTION_THRESHOLD_PX
            if ransac_threshold is None
            else float(ransac_threshold)
        ),
    }


def _unavailable_model_summary(model_name, reason):
    return {
        "name": model_name,
        "available": False,
        "reason": reason,
        "matrix": _matrix_to_list(_identity_transform_matrix()),
        "rmse": None,
        "mean_error": None,
        "max_error": None,
        "point_count": 0,
        "per_point_error": [],
    }


def _estimate_translation_matrix(source_points, target_points):
    translation = np.mean(target_points - source_points, axis=0)
    return np.asarray(
        [
            [1.0, 0.0, float(translation[0])],
            [0.0, 1.0, float(translation[1])],
            [0.0, 0.0, 1.0],
        ],
        dtype=np.float32,
    )


def _estimate_scale_translate_matrix(source_points, target_points):
    x_design = np.column_stack([source_points[:, 0], np.ones(len(source_points), dtype=np.float32)])
    y_design = np.column_stack([source_points[:, 1], np.ones(len(source_points), dtype=np.float32)])
    sx, tx = np.linalg.lstsq(x_design, target_points[:, 0], rcond=None)[0]
    sy, ty = np.linalg.lstsq(y_design, target_points[:, 1], rcond=None)[0]
    return np.asarray(
        [
            [float(sx), 0.0, float(tx)],
            [0.0, float(sy), float(ty)],
            [0.0, 0.0, 1.0],
        ],
        dtype=np.float32,
    )


def estimate_calibration_models(control_points):
    source_points = np.asarray(
        [point["source"] for point in control_points],
        dtype=np.float32,
    )
    target_points = np.asarray(
        [point["target"] for point in control_points],
        dtype=np.float32,
    )
    point_ids = [point.get("point_id", str(index + 1)) for index, point in enumerate(control_points)]
    models = {}

    if len(control_points) < CALIBRATION_MIN_POINTS["crop_only"]:
        return {
            name: _unavailable_model_summary(name, "not_enough_points")
            for name in CALIBRATION_MODEL_ORDER
        }

    models["crop_only"] = _model_summary(
        "crop_only",
        _identity_transform_matrix(),
        source_points,
        target_points,
        point_ids=point_ids,
    )

    if len(control_points) >= CALIBRATION_MIN_POINTS["translation"]:
        translation_matrix = _estimate_translation_matrix(source_points, target_points)
        models["translation"] = _model_summary(
            "translation",
            translation_matrix,
            source_points,
            target_points,
            point_ids=point_ids,
            estimation_details={
                "translation_x": float(translation_matrix[0, 2]),
                "translation_y": float(translation_matrix[1, 2]),
            },
        )
    else:
        models["translation"] = _unavailable_model_summary("translation", "not_enough_points")

    if len(control_points) >= CALIBRATION_MIN_POINTS["scale_translate"]:
        scale_translate_matrix = _estimate_scale_translate_matrix(source_points, target_points)
        models["scale_translate"] = _model_summary(
            "scale_translate",
            scale_translate_matrix,
            source_points,
            target_points,
            point_ids=point_ids,
            estimation_details={
                "scale_x": float(scale_translate_matrix[0, 0]),
                "scale_y": float(scale_translate_matrix[1, 1]),
                "translation_x": float(scale_translate_matrix[0, 2]),
                "translation_y": float(scale_translate_matrix[1, 2]),
            },
        )
    else:
        models["scale_translate"] = _unavailable_model_summary("scale_translate", "not_enough_points")

    if cv2 is None:
        models["affine"] = _unavailable_model_summary("affine", "opencv_unavailable")
        models["homography"] = _unavailable_model_summary("homography", "opencv_unavailable")
        return models

    if len(control_points) >= CALIBRATION_MIN_POINTS["affine"]:
        affine_matrix, inliers = cv2.estimateAffine2D(
            source_points.reshape(-1, 1, 2),
            target_points.reshape(-1, 1, 2),
            method=cv2.RANSAC,
            ransacReprojThreshold=CALIBRATION_RANSAC_REPROJECTION_THRESHOLD_PX,
            maxIters=2000,
            confidence=0.995,
        )
        if affine_matrix is not None:
            affine_homography = np.vstack([affine_matrix, [0.0, 0.0, 1.0]]).astype(np.float32)
            models["affine"] = _model_summary(
                "affine",
                affine_homography,
                source_points,
                target_points,
                point_ids=point_ids,
                estimation_details=_inlier_details(inliers, len(control_points)),
            )
        else:
            models["affine"] = _unavailable_model_summary("affine", "estimation_failed")
    else:
        models["affine"] = _unavailable_model_summary("affine", "not_enough_points")

    if len(control_points) >= CALIBRATION_MIN_POINTS["homography"]:
        best_homography_summary = None
        for ransac_threshold in CALIBRATION_HOMOGRAPHY_RANSAC_THRESHOLDS_PX:
            homography_matrix, inliers = cv2.findHomography(
                source_points.reshape(-1, 1, 2),
                target_points.reshape(-1, 1, 2),
                method=cv2.RANSAC,
                ransacReprojThreshold=ransac_threshold,
            )
            if homography_matrix is None:
                continue
            candidate_summary = _model_summary(
                "homography",
                homography_matrix.astype(np.float32),
                source_points,
                target_points,
                point_ids=point_ids,
                estimation_details=_inlier_details(
                    inliers,
                    len(control_points),
                    ransac_threshold=ransac_threshold,
                ),
            )
            if (
                best_homography_summary is None
                or candidate_summary["rmse"] < best_homography_summary["rmse"]
            ):
                best_homography_summary = candidate_summary
        if best_homography_summary is not None:
            models["homography"] = best_homography_summary
        else:
            models["homography"] = _unavailable_model_summary("homography", "estimation_failed")
    else:
        models["homography"] = _unavailable_model_summary("homography", "not_enough_points")

    return models


def _select_best_calibration_model(models):
    available_models = [
        models[name]
        for name in CALIBRATION_MODEL_ORDER
        if models.get(name, {}).get("available") and models[name].get("rmse") is not None
    ]
    if not available_models:
        return "crop_only", models.get("crop_only", _unavailable_model_summary("crop_only", "not_available"))

    best_rmse = min(model["rmse"] for model in available_models)
    homography_model = models.get("homography")
    simpler_models = [
        model
        for model in available_models
        if model.get("name") != "homography" and model.get("rmse") is not None
    ]
    if homography_model and homography_model.get("available") and homography_model.get("rmse") is not None and simpler_models:
        best_simpler_model = min(simpler_models, key=lambda model: model["rmse"])
        homography_rmse_improvement = best_simpler_model["rmse"] - homography_model["rmse"]
        homography_max_error_improvement = (
            None
            if best_simpler_model.get("max_error") is None or homography_model.get("max_error") is None
            else best_simpler_model["max_error"] - homography_model["max_error"]
        )
        if (
            homography_model["rmse"] <= CALIBRATION_ACCEPTABLE_RMSE_PX
            and homography_rmse_improvement >= CALIBRATION_HOMOGRAPHY_MIN_RMSE_IMPROVEMENT_PX
            and (
                homography_max_error_improvement is None
                or homography_max_error_improvement >= CALIBRATION_HOMOGRAPHY_MIN_MAX_ERROR_IMPROVEMENT_PX
            )
        ):
            return "homography", homography_model

    for model_name in CALIBRATION_MODEL_ORDER:
        model = models.get(model_name)
        if not model or not model.get("available") or model.get("rmse") is None:
            continue
        if (
            model["rmse"] <= best_rmse + CALIBRATION_MODEL_SELECTION_ABSOLUTE_TOLERANCE_PX
            or model["rmse"] <= best_rmse * CALIBRATION_MODEL_SELECTION_RELATIVE_TOLERANCE
        ):
            return model_name, model

    best_model = min(available_models, key=lambda model: model["rmse"])
    return best_model["name"], best_model


def build_calibration_profile(
    control_points,
    camera_used=None,
    dataset_name=None,
    burn_set_name=None,
    profile_scope="dataset",
    baseline_crop_box=None,
    source_rgb_size=None,
    notes=None,
):
    camera_name = _camera_used(camera_used)
    models = estimate_calibration_models(control_points)
    selected_model_name, selected_model = _select_best_calibration_model(models)
    crop_box = baseline_crop_box or _get_base_crop_box(source_rgb_size or (4000, 3000), camera_used=camera_name)
    now_utc = datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    crop_only_rmse = models.get("crop_only", {}).get("rmse")
    selected_rmse = selected_model.get("rmse")

    return {
        "version": CALIBRATION_PROFILE_VERSION,
        "camera": camera_name,
        "scope": profile_scope,
        "dataset_name": dataset_name,
        "burn_set_name": burn_set_name,
        "output_size": list(_get_output_size()),
        "source_rgb_size": list(source_rgb_size) if source_rgb_size is not None else None,
        "baseline_crop_box": {
            "left": int(crop_box[0]),
            "top": int(crop_box[1]),
            "right": int(crop_box[2]),
            "bottom": int(crop_box[3]),
        },
        "selected_model": selected_model_name,
        "selected_model_summary": selected_model,
        "crop_only_rmse": crop_only_rmse,
        "selected_model_rmse": selected_rmse,
        "rmse_improvement_vs_crop_only": (
            None
            if crop_only_rmse is None or selected_rmse is None
            else float(crop_only_rmse - selected_rmse)
        ),
        "models": models,
        "control_points": [
            {
                "point_id": point.get("point_id", str(index + 1)),
                "pair_label": point.get("pair_label", ""),
                "source": [float(point["source"][0]), float(point["source"][1])],
                "target": [float(point["target"][0]), float(point["target"][1])],
                "source_basis": point.get("source_basis", "crop_baseline"),
            }
            for index, point in enumerate(control_points)
        ],
        "notes": notes or "",
        "created_at": now_utc,
        "updated_at": now_utc,
    }


def _profile_filename(camera_used=None, dataset_name=None, burn_set_name=None, scope="dataset"):
    camera_name = _sanitize_identifier(_camera_used(camera_used))
    if scope == "camera_default":
        return f"{camera_name}__camera_default.json"
    if scope == "burn_set":
        return (
            f"{camera_name}__{_sanitize_identifier(dataset_name)}__"
            f"{_sanitize_identifier(burn_set_name)}__burn_set.json"
        )
    return f"{camera_name}__{_sanitize_identifier(dataset_name)}__dataset.json"


def validate_calibration_profile(profile_data):
    reasons = []
    if profile_data is None:
        return False, ["profile_missing"]

    selected_model = profile_data.get("selected_model", "crop_only")
    selected_summary = profile_data.get("selected_model_summary") or profile_data.get("models", {}).get(selected_model)
    if selected_model == "crop_only":
        return True, []
    if not selected_summary:
        return False, ["selected_model_summary_missing"]

    selected_rmse = selected_summary.get("rmse")
    if selected_rmse is None:
        reasons.append("selected_model_rmse_missing")
    elif selected_rmse > CALIBRATION_ACCEPTABLE_RMSE_PX:
        reasons.append(f"selected_model_rmse_high:{selected_rmse:.4f}")

    matrix = selected_summary.get("matrix")
    if matrix is None:
        reasons.append("selected_model_matrix_missing")
    else:
        output_size = tuple(profile_data.get("output_size") or _get_output_size())
        reasons.extend(_profile_transform_sanity_reasons(matrix, output_size, model_name=selected_model))

    return len(reasons) == 0, _unique_reasons(reasons)


def _quarantine_invalid_profile(profile_path, reasons):
    message = f"Ignoring invalid calibration profile {profile_path}: {' | '.join(reasons)}"
    print(message)
    if not QUARANTINE_INVALID_CALIBRATION_PROFILES:
        return

    invalid_root = SCRIPT_DIR / INVALID_CALIBRATION_PROFILES_DIRNAME
    invalid_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    target = invalid_root / f"{profile_path.stem}__invalid_{timestamp}{profile_path.suffix}"
    shutil.move(str(profile_path), str(target))
    print(f"Moved invalid calibration profile to {target}")


def save_calibration_profile(profile_data):
    is_valid, validation_reasons = validate_calibration_profile(profile_data)
    if not is_valid:
        raise ValueError(
            "Calibration profile failed validation and was not saved: "
            + " | ".join(validation_reasons)
        )

    if profile_data.get("scope") == "camera_default":
        filename = _profile_filename(
            camera_used=profile_data.get("camera"),
            scope="camera_default",
        )
    elif profile_data.get("scope") == "burn_set":
        filename = _profile_filename(
            camera_used=profile_data.get("camera"),
            dataset_name=profile_data.get("dataset_name"),
            burn_set_name=profile_data.get("burn_set_name"),
            scope="burn_set",
        )
    else:
        filename = _profile_filename(
            camera_used=profile_data.get("camera"),
            dataset_name=profile_data.get("dataset_name"),
            scope="dataset",
        )

    profile_path = _calibration_profiles_root() / filename
    payload = dict(profile_data)
    payload["updated_at"] = datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    with open(profile_path, "w", encoding="utf-8") as profile_file:
        json.dump(payload, profile_file, indent=2)
    return str(profile_path)


def _load_profile_file(profile_path):
    if not profile_path.exists():
        return None
    with open(profile_path, "r", encoding="utf-8") as profile_file:
        return json.load(profile_file)


def load_calibration_profile(camera_used=None, dataset_name=None, burn_set_name=None):
    camera_name = _camera_used(camera_used)
    candidate_paths = []
    if dataset_name and burn_set_name:
        candidate_paths.append(
            _calibration_profiles_root()
            / _profile_filename(
                camera_used=camera_name,
                dataset_name=dataset_name,
                burn_set_name=burn_set_name,
                scope="burn_set",
            )
        )
    if dataset_name:
        candidate_paths.append(
            _calibration_profiles_root()
            / _profile_filename(
                camera_used=camera_name,
                dataset_name=dataset_name,
                scope="dataset",
            )
        )
    candidate_paths.append(
        _calibration_profiles_root()
        / _profile_filename(camera_used=camera_name, scope="camera_default")
    )

    for candidate_path in candidate_paths:
        profile = _load_profile_file(candidate_path)
        if profile is not None:
            is_valid, validation_reasons = validate_calibration_profile(profile)
            if not is_valid:
                _quarantine_invalid_profile(candidate_path, validation_reasons)
                continue
            profile["profile_path"] = str(candidate_path)
            return profile
    return None


def _rendered_baseline_crop_box(image_size, camera_used=None, calibration_profile=None):
    return _get_base_crop_box(
        image_size,
        camera_used=camera_used,
        calibration_profile=calibration_profile,
    )


def _project_raw_point_to_corrected_coords(raw_coords, crop_box, output_size=None):
    output_width, output_height = output_size or _get_output_size()
    crop_width = max(crop_box[2] - crop_box[0], 1)
    crop_height = max(crop_box[3] - crop_box[1], 1)
    corrected_x = ((raw_coords[0] - crop_box[0]) / float(crop_width)) * output_width
    corrected_y = ((raw_coords[1] - crop_box[1]) / float(crop_height)) * output_height
    return (float(corrected_x), float(corrected_y))


def _get_active_calibration_profile(dataset_name=None, burn_set_name=None, camera_used=None, calibration_profile=None):
    if calibration_profile is not None:
        return calibration_profile
    return load_calibration_profile(
        camera_used=camera_used,
        dataset_name=dataset_name,
        burn_set_name=burn_set_name,
    )


def _describe_selected_model(selected_model_name, selected_model_summary):
    description = {
        "model": selected_model_name,
        "rmse": selected_model_summary.get("rmse"),
        "translation_x": selected_model_summary.get("translation_x", 0.0),
        "translation_y": selected_model_summary.get("translation_y", 0.0),
        "scale_x": selected_model_summary.get("scale_x", 1.0),
        "scale_y": selected_model_summary.get("scale_y", 1.0),
        "matrix": selected_model_summary.get("matrix", _matrix_to_list(_identity_transform_matrix())),
    }
    return description


def _get_crop_debug_info(
    rgb_source_path,
    thermal_source_path=None,
    use_experimental_shift=None,
    dataset_name=None,
    burn_set_name=None,
    calibration_profile=None,
    camera_used=None,
):
    with Image.open(rgb_source_path) as rgb_img:
        width, height = rgb_img.size

    active_profile = _get_active_calibration_profile(
        dataset_name=dataset_name,
        burn_set_name=burn_set_name,
        camera_used=camera_used,
        calibration_profile=calibration_profile,
    )
    if active_profile is not None:
        profile_valid, profile_reasons = validate_calibration_profile(active_profile)
        if not profile_valid:
            print(
                "Ignoring invalid active calibration profile: "
                + " | ".join(profile_reasons)
            )
            active_profile = None
    fov_correction_mode = _get_fov_correction_mode()
    base_crop_box = _rendered_baseline_crop_box(
        (width, height),
        camera_used=camera_used,
        calibration_profile=active_profile,
    )
    crop_width = base_crop_box[2] - base_crop_box[0]
    crop_height = base_crop_box[3] - base_crop_box[1]
    use_shift = (
        EXPERIMENTAL_THERMAL_SHIFT_ENABLED
        if use_experimental_shift is None
        else use_experimental_shift
    )

    shift_x, shift_y = (0, 0)
    shift_mode = "fixed_camera_crop"
    shift_source = "none"
    if use_shift:
        shift_x, shift_y = _estimate_thermal_alignment_shift(
            thermal_source_path,
            crop_width,
            crop_height,
        )
        shift_mode = "experimental_thermal_hotmask_centroid_shift"
        shift_source = "thermal_hotmask_centroid"

    final_crop_box = _clamp_crop_box(
        base_crop_box[0] + shift_x,
        base_crop_box[1] + shift_y,
        base_crop_box[2] + shift_x,
        base_crop_box[3] + shift_y,
        width,
        height,
    )
    final_crop_box, crop_shrink = _apply_crop_shrink(
        final_crop_box,
        (width, height),
        mode=fov_correction_mode,
    )

    crop_only_summary = _model_summary(
        "crop_only",
        _identity_transform_matrix(),
        np.asarray([[0.0, 0.0]], dtype=np.float32),
        np.asarray([[0.0, 0.0]], dtype=np.float32),
    )
    selected_model_name = "crop_only"
    selected_model_summary = crop_only_summary
    profile_selected_model_name = ""
    profile_selected_model_summary = None
    if active_profile is not None:
        profile_selected_model_name = active_profile.get("selected_model", "crop_only")
        profile_selected_model_summary = active_profile.get("models", {}).get(
            profile_selected_model_name,
            active_profile.get("selected_model_summary", crop_only_summary),
        )

    if fov_correction_mode == "CALIBRATION_PROFILE" and profile_selected_model_summary is not None:
        selected_model_name = profile_selected_model_name
        selected_model_summary = profile_selected_model_summary
    elif _mode_uses_feature_alignment(fov_correction_mode):
        selected_model_name = "auto_align"

    return {
        "rgb_size": (width, height),
        "base_crop_box": tuple(int(value) for value in base_crop_box),
        "crop_shrink": crop_shrink,
        "applied_shift": (int(shift_x), int(shift_y)),
        "final_crop_box": final_crop_box,
        "used_experimental_shift": bool(use_shift),
        "shift_mode": shift_mode,
        "shift_source": shift_source,
        "output_size": _get_output_size(),
        "dataset_name": dataset_name,
        "burn_set_name": burn_set_name,
        "calibration_profile": active_profile,
        "fov_correction_mode": fov_correction_mode,
        "selected_model": selected_model_name,
        "selected_model_summary": _describe_selected_model(selected_model_name, selected_model_summary),
        "final_transform_matrix": selected_model_summary.get("matrix", _matrix_to_list(_identity_transform_matrix())),
        "available_profile_model": profile_selected_model_name,
        "available_profile_summary": (
            None
            if profile_selected_model_summary is None
            else _describe_selected_model(profile_selected_model_name, profile_selected_model_summary)
        ),
    }


def _get_aligned_crop_box(
    rgb_source_path,
    thermal_source_path=None,
    use_experimental_shift=None,
    dataset_name=None,
    burn_set_name=None,
    calibration_profile=None,
    camera_used=None,
):
    return _get_crop_debug_info(
        rgb_source_path,
        thermal_source_path=thermal_source_path,
        use_experimental_shift=use_experimental_shift,
        dataset_name=dataset_name,
        burn_set_name=burn_set_name,
        calibration_profile=calibration_profile,
        camera_used=camera_used,
    )["final_crop_box"]


def _warp_corrected_image(corrected_image, transform_matrix, output_size):
    matrix = np.asarray(transform_matrix, dtype=np.float32)
    if np.allclose(matrix, _identity_transform_matrix()):
        return corrected_image.copy()

    rgb_array = np.array(corrected_image.convert("RGB"))
    if cv2 is None:
        return corrected_image.copy()

    warped = cv2.warpPerspective(
        rgb_array,
        matrix,
        tuple(int(value) for value in output_size),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REPLICATE,
    )
    return Image.fromarray(warped)


def _normalize_feature_array(image, variant="edge_blend", invert=False):
    array = np.asarray(image)
    if array.ndim == 3:
        if cv2 is not None:
            array = cv2.cvtColor(array[:, :, :3], cv2.COLOR_RGB2GRAY)
        else:
            array = np.asarray(Image.fromarray(array[:, :, :3]).convert("L"))

    array = array.astype(np.float32)
    finite = np.isfinite(array)
    if not np.any(finite):
        return np.zeros(array.shape, dtype=np.uint8)

    valid_values = array[finite]
    low, high = np.percentile(valid_values, [2, 98])
    if high <= low:
        low = float(valid_values.min())
        high = float(valid_values.max())
    if high <= low:
        return np.zeros(array.shape, dtype=np.uint8)

    normalized = np.clip((array - low) / (high - low), 0.0, 1.0)
    normalized = (normalized * 255.0).astype(np.uint8)
    if invert:
        normalized = 255 - normalized

    if cv2 is not None:
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        normalized = clahe.apply(normalized)
        if variant == "clahe":
            return normalized

        sobel_x = cv2.Sobel(normalized, cv2.CV_32F, 1, 0, ksize=3)
        sobel_y = cv2.Sobel(normalized, cv2.CV_32F, 0, 1, ksize=3)
        gradient = cv2.magnitude(sobel_x, sobel_y)
        gradient = cv2.normalize(gradient, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
        if variant == "sobel":
            return gradient
        if variant == "canny":
            return cv2.Canny(normalized, 50, 150)
        if variant == "edge_blend" and FEATURE_ALIGNMENT_USE_EDGE_BLEND:
            return cv2.addWeighted(
                normalized,
                1.0 - FEATURE_ALIGNMENT_EDGE_BLEND_WEIGHT,
                gradient,
                FEATURE_ALIGNMENT_EDGE_BLEND_WEIGHT,
                0,
            )
    return normalized


def _default_feature_alignment_result(status="not_run"):
    return {
        "status": status,
        "confidence_level": "LOW",
        "fallback_used": "none",
        "matrix": _matrix_to_list(_identity_transform_matrix()),
        "keypoints_rgb": 0,
        "keypoints_thermal": 0,
        "good_matches": 0,
        "inliers": 0,
        "inlier_ratio": 0.0,
        "match_grid_cells": 0,
        "inlier_grid_cells": 0,
        "mean_reprojection_error_px": None,
        "max_reprojection_error_px": None,
        "transform_type": FEATURE_ALIGNMENT_MODEL,
        "scale_x": 1.0,
        "scale_y": 1.0,
        "scale_ratio": 1.0,
        "rotation_degrees": 0.0,
        "skew_dot": 0.0,
        "determinant": 1.0,
        "translation_x": 0.0,
        "translation_y": 0.0,
        "accepted": False,
        "reasons": [],
    }


def _load_thermal_feature_image(thermal_source_path, output_size, variant="edge_blend", invert=False):
    if not thermal_source_path or not os.path.exists(thermal_source_path):
        return None

    try:
        with Image.open(thermal_source_path) as thermal_img:
            thermal_array = _normalize_feature_array(thermal_img, variant=variant, invert=invert)
    except Exception:
        return None

    if cv2 is None:
        return thermal_array
    return cv2.resize(
        thermal_array,
        tuple(int(value) for value in output_size),
        interpolation=cv2.INTER_AREA,
    )


def _build_alignment_representation_pairs(corrected_crop_image, thermal_source_path, output_size):
    representation_pairs = []
    for variant in FEATURE_ALIGNMENT_PREPROCESSING_VARIANTS:
        thermal_invert = variant == "thermal_inverted_clahe"
        representation_variant = "clahe" if thermal_invert else variant
        rgb_feature = _normalize_feature_array(
            corrected_crop_image.convert("RGB"),
            variant=representation_variant,
            invert=False,
        )
        thermal_feature = _load_thermal_feature_image(
            thermal_source_path,
            output_size,
            variant=representation_variant,
            invert=thermal_invert,
        )
        if thermal_feature is None:
            continue
        representation_pairs.append(
            {
                "name": variant,
                "rgb": rgb_feature,
                "thermal": thermal_feature,
            }
        )
    return representation_pairs


def _project_points_with_matrix(points, matrix):
    points = np.asarray(points, dtype=np.float32)
    matrix = np.asarray(matrix, dtype=np.float32)
    homogenous_points = np.column_stack([points, np.ones(len(points), dtype=np.float32)])
    projected = homogenous_points @ matrix.T
    denominators = projected[:, 2:3]
    denominators[np.isclose(denominators, 0.0)] = 1.0
    return projected[:, :2] / denominators


def _grid_cell_for_point(point, image_size, grid_size=None):
    grid_cols, grid_rows = grid_size or FEATURE_ALIGNMENT_GRID_SIZE
    width, height = image_size
    col = int(np.clip(point[0] / max(width, 1) * grid_cols, 0, grid_cols - 1))
    row = int(np.clip(point[1] / max(height, 1) * grid_rows, 0, grid_rows - 1))
    return (col, row)


def _spatially_balance_matches(matches, rgb_keypoints, image_size):
    grouped_matches = {}
    for match in matches:
        cell = _grid_cell_for_point(rgb_keypoints[match.queryIdx].pt, image_size)
        grouped_matches.setdefault(cell, []).append(match)

    balanced = []
    for cell_matches in grouped_matches.values():
        balanced.extend(
            sorted(cell_matches, key=lambda match: match.distance)[
                :FEATURE_ALIGNMENT_MAX_MATCHES_PER_GRID_CELL
            ]
        )

    return sorted(balanced, key=lambda match: match.distance), len(grouped_matches)


def _occupied_grid_cell_count(points, image_size):
    if points is None or len(points) == 0:
        return 0
    return len({_grid_cell_for_point(point, image_size) for point in points})


def _transform_geometry_summary(matrix, output_size):
    matrix = np.asarray(matrix, dtype=np.float32)
    linear = matrix[:2, :2]
    first_axis = linear[:, 0]
    second_axis = linear[:, 1]
    scale_x = float(np.linalg.norm(first_axis))
    scale_y = float(np.linalg.norm(second_axis))
    if scale_x > 0 and scale_y > 0:
        skew_dot = float(np.dot(first_axis / scale_x, second_axis / scale_y))
    else:
        skew_dot = 1.0
    rotation_degrees = float(np.degrees(np.arctan2(linear[1, 0], linear[0, 0])))
    translation_x = float(matrix[0, 2])
    translation_y = float(matrix[1, 2])
    translation_magnitude = float(np.hypot(translation_x, translation_y))
    output_diagonal = float(np.hypot(output_size[0], output_size[1]))
    determinant = float(np.linalg.det(linear))
    return {
        "scale_x": scale_x,
        "scale_y": scale_y,
        "scale_ratio": scale_x / max(scale_y, 0.0001),
        "rotation_degrees": rotation_degrees,
        "skew_dot": skew_dot,
        "translation_x": translation_x,
        "translation_y": translation_y,
        "translation_fraction": translation_magnitude / max(output_diagonal, 1.0),
        "determinant": determinant,
    }


def _signed_polygon_area(points):
    points = np.asarray(points, dtype=np.float32)
    if len(points) < 3:
        return 0.0
    x_values = points[:, 0]
    y_values = points[:, 1]
    return float(0.5 * np.sum(x_values * np.roll(y_values, -1) - y_values * np.roll(x_values, -1)))


def _project_output_corners(matrix, output_size):
    width, height = output_size
    corners = np.asarray(
        [
            [0.0, 0.0],
            [float(width), 0.0],
            [float(width), float(height)],
            [0.0, float(height)],
        ],
        dtype=np.float32,
    )
    return _transform_points(corners, matrix)


def _homography_sanity_reasons(matrix, output_size):
    reasons = []
    matrix = np.asarray(matrix, dtype=np.float32)
    if matrix.shape != (3, 3) or not np.all(np.isfinite(matrix)):
        return ["fallback_profile_invalid_homography_matrix"]

    projected_corners = _project_output_corners(matrix, output_size)
    if not np.all(np.isfinite(projected_corners)):
        return ["fallback_profile_invalid_homography_corners"]

    width, height = output_size
    source_area = float(max(width * height, 1))
    signed_area = _signed_polygon_area(projected_corners)
    area_ratio = abs(signed_area) / source_area
    if signed_area <= 0:
        reasons.append("fallback_profile_orientation_flip")
    if not (CALIBRATION_HOMOGRAPHY_MIN_AREA_RATIO <= area_ratio <= CALIBRATION_HOMOGRAPHY_MAX_AREA_RATIO):
        reasons.append("fallback_profile_unrealistic_homography_area")

    min_x = float(np.min(projected_corners[:, 0]))
    min_y = float(np.min(projected_corners[:, 1]))
    max_x = float(np.max(projected_corners[:, 0]))
    max_y = float(np.max(projected_corners[:, 1]))
    max_extension = max(0.0, -min_x, -min_y, max_x - float(width), max_y - float(height))
    extension_fraction = max_extension / max(float(max(width, height)), 1.0)
    if extension_fraction > CALIBRATION_HOMOGRAPHY_MAX_CORNER_EXTENSION_FRACTION:
        reasons.append("fallback_profile_unrealistic_homography_extent")

    return reasons


def _profile_transform_sanity_reasons(matrix, output_size, model_name=None):
    if str(model_name or "").lower() == "homography":
        return _homography_sanity_reasons(matrix, output_size)

    geometry = _transform_geometry_summary(matrix, output_size)
    reasons = []
    if not (
        FEATURE_ALIGNMENT_MIN_SCALE <= geometry["scale_x"] <= FEATURE_ALIGNMENT_MAX_SCALE
        and FEATURE_ALIGNMENT_MIN_SCALE <= geometry["scale_y"] <= FEATURE_ALIGNMENT_MAX_SCALE
    ):
        reasons.append("fallback_profile_unrealistic_scale")
    if abs(geometry["skew_dot"]) > FEATURE_ALIGNMENT_MAX_SKEW_DOT:
        reasons.append("fallback_profile_unrealistic_skew")
    if geometry["translation_fraction"] > FEATURE_ALIGNMENT_MAX_TRANSLATION_FRACTION:
        reasons.append("fallback_profile_unrealistic_translation")
    if geometry["determinant"] <= 0:
        reasons.append("fallback_profile_orientation_flip")
    return reasons


def _validate_feature_alignment_result(
    result,
    source_points,
    target_points,
    inlier_mask,
    output_size,
    source_image_size=None,
    match_grid_cells=0,
):
    matrix = np.asarray(result["matrix"], dtype=np.float32)
    inlier_mask = np.asarray(inlier_mask, dtype=bool).reshape(-1) if inlier_mask is not None else np.zeros(
        len(source_points),
        dtype=bool,
    )
    inlier_count = int(inlier_mask.sum())
    good_matches = int(result["good_matches"])
    inlier_ratio = inlier_count / max(good_matches, 1)
    projected_points = _project_points_with_matrix(source_points, matrix)
    errors = np.linalg.norm(projected_points - target_points, axis=1)
    inlier_errors = errors[inlier_mask] if inlier_count else np.asarray([], dtype=np.float32)
    mean_error = None if not len(inlier_errors) else float(inlier_errors.mean())
    max_error = None if not len(inlier_errors) else float(inlier_errors.max())
    geometry = _transform_geometry_summary(matrix, output_size)
    inlier_grid_cells = _occupied_grid_cell_count(
        source_points[inlier_mask] if inlier_count else [],
        source_image_size or output_size,
    )

    reasons = []
    if good_matches < FEATURE_ALIGNMENT_MIN_GOOD_MATCHES:
        reasons.append("not_enough_good_matches")
    if match_grid_cells < FEATURE_ALIGNMENT_MIN_MATCH_GRID_CELLS:
        reasons.append("matches_not_spatially_distributed")
    if inlier_count < FEATURE_ALIGNMENT_MIN_INLIERS:
        reasons.append("not_enough_ransac_inliers")
    if inlier_grid_cells < FEATURE_ALIGNMENT_MIN_INLIER_GRID_CELLS:
        reasons.append("inliers_not_spatially_distributed")
    if inlier_ratio < FEATURE_ALIGNMENT_MIN_INLIER_RATIO:
        reasons.append("low_inlier_ratio")
    if mean_error is None or mean_error > FEATURE_ALIGNMENT_MAX_MEAN_REPROJECTION_ERROR_PX:
        reasons.append("high_reprojection_error")
    if not (
        FEATURE_ALIGNMENT_MIN_SCALE <= geometry["scale_x"] <= FEATURE_ALIGNMENT_MAX_SCALE
        and FEATURE_ALIGNMENT_MIN_SCALE <= geometry["scale_y"] <= FEATURE_ALIGNMENT_MAX_SCALE
    ):
        reasons.append("unrealistic_scale")
    if abs(geometry["skew_dot"]) > FEATURE_ALIGNMENT_MAX_SKEW_DOT:
        reasons.append("unrealistic_skew")
    if geometry["translation_fraction"] > FEATURE_ALIGNMENT_MAX_TRANSLATION_FRACTION:
        reasons.append("unrealistic_translation")
    if geometry["determinant"] <= 0:
        reasons.append("orientation_flip")

    confidence_level = "HIGH"
    if reasons:
        confidence_level = "LOW"
    elif mean_error is not None and mean_error > FEATURE_ALIGNMENT_MAX_HIGH_CONFIDENCE_REPROJECTION_ERROR_PX:
        confidence_level = "MEDIUM"

    result.update(
        {
            "status": "ok" if confidence_level == "HIGH" else "alignment_low_confidence",
            "confidence_level": confidence_level,
            "inliers": inlier_count,
            "inlier_ratio": round(inlier_ratio, 4),
            "match_grid_cells": int(match_grid_cells),
            "inlier_grid_cells": int(inlier_grid_cells),
            "mean_reprojection_error_px": mean_error,
            "max_reprojection_error_px": max_error,
            "scale_x": geometry["scale_x"],
            "scale_y": geometry["scale_y"],
            "scale_ratio": geometry["scale_ratio"],
            "rotation_degrees": geometry["rotation_degrees"],
            "skew_dot": geometry["skew_dot"],
            "determinant": geometry["determinant"],
            "translation_x": geometry["translation_x"],
            "translation_y": geometry["translation_y"],
            "accepted": confidence_level == "HIGH",
            "reasons": reasons,
        }
    )
    return result


def _alignment_model_order():
    if FEATURE_ALIGNMENT_MODEL in {"similarity", "affine", "homography"}:
        return [FEATURE_ALIGNMENT_MODEL]

    models = list(FEATURE_ALIGNMENT_MODEL_ORDER)
    if FEATURE_ALIGNMENT_ENABLE_HOMOGRAPHY and "homography" not in models:
        models.append("homography")
    return models


def _estimate_transform_for_model(source_points, target_points, model_name):
    if model_name == "similarity":
        affine_matrix, inliers = cv2.estimateAffinePartial2D(
            source_points.reshape(-1, 1, 2),
            target_points.reshape(-1, 1, 2),
            method=cv2.RANSAC,
            ransacReprojThreshold=4.0,
        )
        if affine_matrix is None:
            return None, None
        return np.vstack([affine_matrix, np.array([0.0, 0.0, 1.0], dtype=np.float32)]), inliers

    if model_name == "affine":
        affine_matrix, inliers = cv2.estimateAffine2D(
            source_points.reshape(-1, 1, 2),
            target_points.reshape(-1, 1, 2),
            method=cv2.RANSAC,
            ransacReprojThreshold=4.0,
        )
        if affine_matrix is None:
            return None, None
        return np.vstack([affine_matrix, np.array([0.0, 0.0, 1.0], dtype=np.float32)]), inliers

    if model_name == "homography":
        matrix, inliers = cv2.findHomography(
            source_points.reshape(-1, 1, 2),
            target_points.reshape(-1, 1, 2),
            cv2.RANSAC,
            4.0,
        )
        return matrix, inliers

    return None, None


def _refine_candidate_with_ecc(candidate, rgb_feature, thermal_feature, source_points, target_points, inliers, output_size):
    if not FEATURE_ALIGNMENT_USE_ECC_REFINEMENT or candidate.get("transform_type") == "homography":
        return candidate
    if not candidate.get("accepted"):
        return candidate

    try:
        rgb_float = rgb_feature.astype(np.float32) / 255.0
        thermal_float = thermal_feature.astype(np.float32) / 255.0
        initial_warp = np.asarray(candidate["matrix"], dtype=np.float32)[:2, :]
        criteria = (
            cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT,
            FEATURE_ALIGNMENT_ECC_MAX_ITERATIONS,
            FEATURE_ALIGNMENT_ECC_EPSILON,
        )
        ecc_score, refined_warp = cv2.findTransformECC(
            thermal_float,
            rgb_float,
            initial_warp,
            cv2.MOTION_AFFINE,
            criteria,
            None,
            5,
        )
    except Exception as exc:
        refined = dict(candidate)
        refined["ecc_status"] = f"failed:{exc}"
        return refined

    refined_matrix = np.vstack([refined_warp, np.array([0.0, 0.0, 1.0], dtype=np.float32)])
    refined = dict(candidate)
    refined["matrix"] = _matrix_to_list(refined_matrix)
    refined["ecc_status"] = "ok"
    refined["ecc_score"] = float(ecc_score)
    refined = _validate_feature_alignment_result(
        refined,
        source_points,
        target_points,
        inliers,
        output_size,
        source_image_size=output_size,
        match_grid_cells=refined.get("match_grid_cells", 0),
    )
    original_error = candidate.get("mean_reprojection_error_px")
    refined_error = refined.get("mean_reprojection_error_px")
    if (
        refined.get("accepted")
        and refined_error is not None
        and (original_error is None or refined_error <= original_error)
    ):
        refined["ecc_refined"] = True
        return refined

    rejected = dict(candidate)
    rejected["ecc_status"] = "rejected"
    rejected["ecc_score"] = float(ecc_score)
    return rejected


def _run_sift_alignment_candidate(rgb_feature, thermal_feature, representation_name, model_name, output_size):
    result = _default_feature_alignment_result("not_run")
    result["representation"] = representation_name
    result["transform_type"] = model_name

    if cv2 is None:
        result["status"] = "opencv_unavailable"
        result["reasons"] = ["opencv_unavailable"]
        return result

    sift = cv2.SIFT_create()
    rgb_keypoints, rgb_descriptors = sift.detectAndCompute(rgb_feature, None)
    thermal_keypoints, thermal_descriptors = sift.detectAndCompute(thermal_feature, None)
    result["keypoints_rgb"] = len(rgb_keypoints or [])
    result["keypoints_thermal"] = len(thermal_keypoints or [])
    if rgb_descriptors is None or thermal_descriptors is None:
        result["status"] = "descriptors_unavailable"
        result["reasons"] = ["descriptors_unavailable"]
        return result

    matcher = cv2.BFMatcher(cv2.NORM_L2)
    raw_matches = matcher.knnMatch(rgb_descriptors, thermal_descriptors, k=2)
    good_matches = []
    for match_group in raw_matches:
        if len(match_group) < 2:
            continue
        first, second = match_group
        if first.distance < FEATURE_ALIGNMENT_RATIO_TEST * second.distance:
            good_matches.append(first)

    result["raw_good_matches"] = len(good_matches)
    balanced_matches, match_grid_cells = _spatially_balance_matches(
        good_matches,
        rgb_keypoints,
        output_size,
    )
    result["good_matches"] = len(balanced_matches)
    result["match_grid_cells"] = match_grid_cells
    if len(balanced_matches) < FEATURE_ALIGNMENT_MIN_GOOD_MATCHES:
        result["status"] = "not_enough_good_matches"
        result["reasons"] = ["not_enough_good_matches"]
        return result

    source_points = np.float32([rgb_keypoints[match.queryIdx].pt for match in balanced_matches])
    target_points = np.float32([thermal_keypoints[match.trainIdx].pt for match in balanced_matches])
    matrix, inliers = _estimate_transform_for_model(source_points, target_points, model_name)
    if matrix is None:
        result["status"] = "transform_estimation_failed"
        result["reasons"] = ["transform_estimation_failed"]
        return result

    result["status"] = "ok"
    result["matrix"] = _matrix_to_list(matrix)
    result = _validate_feature_alignment_result(
        result,
        source_points,
        target_points,
        inliers,
        output_size,
        source_image_size=output_size,
        match_grid_cells=match_grid_cells,
    )
    return _refine_candidate_with_ecc(
        result,
        rgb_feature,
        thermal_feature,
        source_points,
        target_points,
        inliers,
        output_size,
    )


def _summarize_alignment_candidate(candidate):
    summary = {}
    for key, value in candidate.items():
        if isinstance(value, np.generic):
            value = value.item()
        if key.startswith("_"):
            continue
        summary[key] = value
    return summary


def _select_best_alignment_candidate(candidates):
    if not candidates:
        return _default_feature_alignment_result("no_candidates")

    model_rank = {"crop_only": 0, "similarity": 1, "affine": 2, "homography": 3}
    accepted = [candidate for candidate in candidates if candidate.get("accepted")]
    if accepted:
        return sorted(
            accepted,
            key=lambda candidate: (
                model_rank.get(candidate.get("transform_type"), 99),
                candidate.get("mean_reprojection_error_px") or float("inf"),
                -candidate.get("inlier_grid_cells", 0),
                -candidate.get("inliers", 0),
            ),
        )[0]

    return sorted(
        candidates,
        key=lambda candidate: (
            candidate.get("confidence_level") == "HIGH",
            candidate.get("confidence_level") == "MEDIUM",
            candidate.get("inlier_grid_cells", 0),
            candidate.get("inliers", 0),
            candidate.get("inlier_ratio", 0.0),
            -(candidate.get("mean_reprojection_error_px") or float("inf")),
        ),
        reverse=True,
    )[0]


def _auto_align_questionable_reasons(alignment_result):
    reasons = []
    if not alignment_result.get("accepted"):
        reasons.append("auto_align_not_accepted")
    if alignment_result.get("confidence_level") != "HIGH":
        reasons.append("auto_align_not_high_confidence")
    if alignment_result.get("inlier_grid_cells", 0) < max(FEATURE_ALIGNMENT_MIN_INLIER_GRID_CELLS + 1, 4):
        reasons.append("edge_coverage_questionable")
    scale_ratio = float(alignment_result.get("scale_ratio", 1.0))
    if scale_ratio < 0.92 or scale_ratio > 1.08:
        reasons.append("scale_ratio_questionable")
    scale_x = float(alignment_result.get("scale_x", 1.0))
    scale_y = float(alignment_result.get("scale_y", 1.0))
    if abs(scale_x - scale_y) > 0.15:
        reasons.append("nonuniform_scale_questionable")
    if abs(float(alignment_result.get("skew_dot", 0.0))) > 0.15:
        reasons.append("skew_questionable")
    return _unique_reasons(reasons)


def _estimate_sift_alignment_matrix(corrected_crop_image, thermal_source_path, output_size):
    if cv2 is None:
        result = _default_feature_alignment_result("opencv_unavailable")
        result["reasons"] = ["opencv_unavailable"]
        return result

    representation_pairs = _build_alignment_representation_pairs(
        corrected_crop_image,
        thermal_source_path,
        output_size,
    )
    if not representation_pairs:
        result = _default_feature_alignment_result("thermal_unavailable")
        result["reasons"] = ["thermal_unavailable"]
        return result

    candidates = []
    for representation in representation_pairs:
        for model_name in _alignment_model_order():
            candidates.append(
                _run_sift_alignment_candidate(
                    representation["rgb"],
                    representation["thermal"],
                    representation["name"],
                    model_name,
                    output_size,
                )
            )

    selected = dict(_select_best_alignment_candidate(candidates))
    selected["candidate_count"] = len(candidates)
    selected["alignment_candidates"] = [
        _summarize_alignment_candidate(candidate) for candidate in candidates
    ]
    selected["auto_align_questionable_reasons"] = _auto_align_questionable_reasons(selected)
    return selected


def _apply_sift_alignment_to_color(corrected_crop_image, thermal_source_path, output_size):
    alignment_result = _estimate_sift_alignment_matrix(
        corrected_crop_image,
        thermal_source_path,
        output_size,
    )
    if alignment_result["status"] != "ok":
        return corrected_crop_image.copy(), alignment_result

    aligned = _warp_corrected_image(
        corrected_crop_image,
        alignment_result["matrix"],
        output_size,
    )
    return aligned, alignment_result


def _apply_rgb_fov_correction(
    rgb_source_path,
    thermal_source_path=None,
    use_experimental_shift=None,
    dataset_name=None,
    burn_set_name=None,
    calibration_profile=None,
    camera_used=None,
    return_debug_info=False,
):
    debug_info = _get_crop_debug_info(
        rgb_source_path,
        thermal_source_path=thermal_source_path,
        use_experimental_shift=use_experimental_shift,
        dataset_name=dataset_name,
        burn_set_name=burn_set_name,
        calibration_profile=calibration_profile,
        camera_used=camera_used,
    )

    with Image.open(rgb_source_path) as rgb_img:
        exif_bytes = rgb_img.info.get("exif")
        baseline_corrected = rgb_img.crop(debug_info["final_crop_box"]).resize(
            debug_info["output_size"],
            Image.LANCZOS,
        )

    alignment_result = None
    if debug_info["fov_correction_mode"] == "CALIBRATION_PROFILE":
        selected_model_summary = debug_info["selected_model_summary"]
        final_image = _warp_corrected_image(
            baseline_corrected,
            selected_model_summary.get("matrix", _matrix_to_list(_identity_transform_matrix())),
            debug_info["output_size"],
        )
    elif _mode_uses_feature_alignment(debug_info["fov_correction_mode"]):
        final_image, alignment_result = _apply_sift_alignment_to_color(
            baseline_corrected,
            thermal_source_path,
            debug_info["output_size"],
        )
        debug_info["feature_alignment"] = alignment_result
        debug_info["alignment_candidates"] = alignment_result.get("alignment_candidates", [])
        if alignment_result["accepted"]:
            debug_info["final_transform_matrix"] = alignment_result["matrix"]
        elif _mode_allows_profile_fallback(debug_info["fov_correction_mode"]) and debug_info["available_profile_summary"] is not None:
            fallback_matrix = debug_info["available_profile_summary"].get(
                "matrix",
                _matrix_to_list(_identity_transform_matrix()),
            )
            fallback_reasons = _profile_transform_sanity_reasons(
                fallback_matrix,
                debug_info["output_size"],
                model_name=debug_info["available_profile_model"],
            )
            if fallback_reasons:
                alignment_result["fallback_used"] = "crop_only"
                alignment_result["reasons"] = _unique_reasons(
                    alignment_result.get("reasons", []) + fallback_reasons
                )
                debug_info["selected_model"] = "experimental_sift_fallback_crop_only"
                debug_info["final_transform_matrix"] = _matrix_to_list(_identity_transform_matrix())
            else:
                final_image.close()
                final_image = _warp_corrected_image(
                    baseline_corrected,
                    fallback_matrix,
                    debug_info["output_size"],
                )
                alignment_result["fallback_used"] = "calibration_profile"
                debug_info["selected_model"] = "experimental_sift_fallback_calibration_profile"
                debug_info["final_transform_matrix"] = fallback_matrix
        else:
            alignment_result["fallback_used"] = "crop_only"
            debug_info["selected_model"] = "experimental_sift_fallback_crop_only"
            debug_info["final_transform_matrix"] = _matrix_to_list(_identity_transform_matrix())
    else:
        final_image = baseline_corrected.copy()

    if exif_bytes:
        final_image.info["exif"] = exif_bytes

    if return_debug_info:
        debug_info["baseline_only_image_size"] = baseline_corrected.size
        if alignment_result is None:
            debug_info["feature_alignment"] = _default_feature_alignment_result()
        return final_image, debug_info
    return final_image


def _pair_record_path(pair, key):
    record = pair.get(key) if pair is not None else None
    if not record:
        return None
    return record.get("filepath")


def _select_corrected_fov_thermal_source(pair):
    for source_name, key in (
        ("CalTIFF", "cal_tiff"),
        ("TIFF", "thermal_tiff"),
        ("thermal JPG", "thermal_jpg"),
    ):
        source_path = _pair_record_path(pair, key)
        if source_path:
            return source_path, source_name
    return None, "none"


def _debug_fallback_used(debug_info):
    alignment = debug_info.get("feature_alignment", {})
    fallback = alignment.get("fallback_used")
    return bool(fallback and fallback != "none")


def generate_corrected_fov(
    pair,
    mode="AUTO_ALIGN",
    dataset_name=None,
    burn_set_name=None,
    calibration_profile=None,
    camera_used=None,
    use_experimental_shift=False,
    return_debug_info=False,
):
    thermal_source_path, thermal_source_name = _select_corrected_fov_thermal_source(pair)
    previous_mode = FOV_CORRECTION_MODE
    try:
        globals()["FOV_CORRECTION_MODE"] = mode
        corrected_rgb, debug_info = _apply_rgb_fov_correction(
            pair["rgb"]["filepath"],
            thermal_source_path=thermal_source_path,
            use_experimental_shift=use_experimental_shift,
            dataset_name=dataset_name if dataset_name is not None else pair.get("dataset_name"),
            burn_set_name=burn_set_name if burn_set_name is not None else pair.get("burn_set_name"),
            calibration_profile=calibration_profile,
            camera_used=camera_used if camera_used is not None else pair.get("detected_camera"),
            return_debug_info=True,
        )
    finally:
        globals()["FOV_CORRECTION_MODE"] = previous_mode

    debug_info["correction_mode_used"] = debug_info.get("fov_correction_mode", mode)
    debug_info["thermal_source_used"] = thermal_source_name
    debug_info["thermal_source_path"] = thermal_source_path or ""
    debug_info["fallback_occurred"] = _debug_fallback_used(debug_info)
    debug_info["transform_matrix"] = debug_info.get("final_transform_matrix")

    if return_debug_info:
        return corrected_rgb, debug_info
    return corrected_rgb


def _fit_image_to_panel(image, panel_size=(640, 512), background=(245, 245, 245)):
    panel = Image.new("RGB", panel_size, color=background)
    image_copy = image.copy()
    image_copy.thumbnail(panel_size)
    x_offset = (panel_size[0] - image_copy.width) // 2
    y_offset = (panel_size[1] - image_copy.height) // 2
    panel.paste(image_copy, (x_offset, y_offset))
    return panel


def _load_debug_preview_image(path):
    with Image.open(path) as image:
        if image.mode not in ("RGB", "RGBA"):
            return ImageOps.autocontrast(image.convert("L")).convert("RGB")
        return image.convert("RGB")


def _build_alignment_debug_image(
    rgb_path,
    thermal_preview_path,
    thermal_shift_source_path,
    dataset_name=None,
    burn_set_name=None,
    calibration_profile=None,
    camera_used=None,
):
    raw_rgb = _load_debug_preview_image(rgb_path)
    debug_pair = {
        "rgb": {"filepath": rgb_path, "filename": os.path.basename(rgb_path)},
        "cal_tiff": None,
        "thermal_tiff": {
            "filepath": thermal_shift_source_path,
            "filename": os.path.basename(thermal_shift_source_path) if thermal_shift_source_path else "",
        },
        "thermal_jpg": {
            "filepath": thermal_preview_path,
            "filename": os.path.basename(thermal_preview_path) if thermal_preview_path else "",
        },
        "dataset_name": dataset_name,
        "burn_set_name": burn_set_name,
        "detected_camera": camera_used,
    }
    crop_only_corrected, crop_only_debug = generate_corrected_fov(
        debug_pair,
        mode="CROP_ONLY",
        dataset_name=dataset_name,
        burn_set_name=burn_set_name,
        calibration_profile=None,
        camera_used=camera_used,
        return_debug_info=True,
    )
    final_corrected, final_debug = generate_corrected_fov(
        debug_pair,
        mode=_get_fov_correction_mode(),
        dataset_name=dataset_name,
        burn_set_name=burn_set_name,
        calibration_profile=calibration_profile,
        camera_used=camera_used,
        return_debug_info=True,
    )
    crop_only_corrected = crop_only_corrected.convert("RGB")
    final_corrected = final_corrected.convert("RGB")
    thermal_preview = _load_debug_preview_image(thermal_preview_path)

    panel_size = _get_output_size()
    label_height = 44
    gap = 20
    labels = [
        ("Raw RGB", raw_rgb),
        ("Crop-Only Corrected FOV", crop_only_corrected),
        (
            f"Final Corrected FOV ({final_debug['selected_model']})",
            final_corrected,
        ),
        ("Thermal", thermal_preview),
    ]

    canvas_width = panel_size[0] * 2 + gap * 3
    canvas_height = (panel_size[1] + label_height) * 2 + gap * 3
    canvas = Image.new("RGB", (canvas_width, canvas_height), color=(245, 245, 245))
    draw = ImageDraw.Draw(canvas)

    for panel_index, (label, image) in enumerate(labels):
        row = panel_index // 2
        col = panel_index % 2
        x = gap + col * (panel_size[0] + gap)
        y = gap + row * (panel_size[1] + label_height + gap)
        draw.text((x, y), label, fill=(0, 0, 0))
        panel = _fit_image_to_panel(image, panel_size=panel_size)
        canvas.paste(panel, (x, y + label_height))

    crop_only_corrected.close()
    final_corrected.close()
    return canvas, crop_only_debug, final_debug


def _sample_pair_indices(pair_count, sample_count):
    if pair_count <= 0:
        return []
    if pair_count <= sample_count:
        return list(range(pair_count))
    if sample_count <= 1:
        return [0]

    indices = []
    for position in range(sample_count):
        index = round(position * (pair_count - 1) / (sample_count - 1))
        if index not in indices:
            indices.append(index)
    return indices


def _save_alignment_candidate_debug_images(debug_root, sample_number, rgb_path, thermal_path, debug_info):
    sample_prefix = f"sample_{sample_number:02d}"
    output_size = debug_info["output_size"]
    with Image.open(rgb_path) as rgb_img:
        crop_only = rgb_img.crop(debug_info["final_crop_box"]).resize(output_size, Image.LANCZOS).convert("RGB")
    crop_only.save(os.path.join(debug_root, f"{sample_prefix}_crop_only.png"))

    thermal_preview = _load_debug_preview_image(thermal_path)
    _fit_image_to_panel(thermal_preview, panel_size=output_size).save(
        os.path.join(debug_root, f"{sample_prefix}_thermal.png")
    )
    thermal_preview.close()

    for candidate_index, candidate in enumerate(debug_info.get("alignment_candidates", []), start=1):
        matrix = candidate.get("matrix")
        if matrix is None:
            continue
        candidate_image = _warp_corrected_image(crop_only, matrix, output_size)
        label = _sanitize_identifier(
            f"{candidate_index:02d}_{candidate.get('representation', 'unknown')}_{candidate.get('transform_type', 'unknown')}_{candidate.get('confidence_level', 'low')}"
        )
        candidate_image.save(os.path.join(debug_root, f"{sample_prefix}_{label}.png"))
        candidate_image.close()
    crop_only.close()


def _blend_rgb_thermal_overlay(rgb_image, thermal_image, opacity=0.50):
    rgb_base = rgb_image.convert("RGB").resize(_get_output_size(), Image.LANCZOS)
    thermal_base = thermal_image.convert("RGB").resize(rgb_base.size, Image.LANCZOS)
    thermal_gray = ImageOps.autocontrast(thermal_base.convert("L")).convert("RGB")
    return Image.blend(rgb_base, thermal_gray, max(0.0, min(float(opacity), 1.0)))


def _build_validation_comparison_grid(items):
    panel_size = _get_output_size()
    label_height = 44
    gap = 20
    visible_items = [(label, image) for label, image in items if image is not None]
    if not visible_items:
        return Image.new("RGB", panel_size, color=(245, 245, 245))

    column_count = 2
    row_count = int(np.ceil(len(visible_items) / column_count))
    canvas_width = panel_size[0] * column_count + gap * (column_count + 1)
    canvas_height = (panel_size[1] + label_height) * row_count + gap * (row_count + 1)
    canvas = Image.new("RGB", (canvas_width, canvas_height), color=(245, 245, 245))
    draw = ImageDraw.Draw(canvas)

    for panel_index, (label, image) in enumerate(visible_items):
        row = panel_index // column_count
        col = panel_index % column_count
        x = gap + col * (panel_size[0] + gap)
        y = gap + row * (panel_size[1] + label_height + gap)
        draw.text((x, y), label, fill=(0, 0, 0))
        canvas.paste(_fit_image_to_panel(image, panel_size=panel_size), (x, y + label_height))

    return canvas


def _write_manual_calibration_model_metrics(debug_root, calibration_profile):
    if not calibration_profile:
        return None

    model_metrics_path = os.path.join(debug_root, "manual_calibration_model_metrics.csv")
    point_errors_path = os.path.join(debug_root, "manual_calibration_point_errors.csv")
    model_fieldnames = [
        "model",
        "selected",
        "available",
        "reason",
        "rmse",
        "mean_error",
        "max_error",
        "point_count",
        "inlier_count",
        "inlier_ratio",
        "ransac_reprojection_threshold_px",
        "matrix",
    ]
    selected_model = calibration_profile.get("selected_model", "")
    model_rows = []
    point_error_rows = []
    control_points = calibration_profile.get("control_points", [])
    source_points = np.asarray([point["source"] for point in control_points], dtype=np.float32)
    target_points = np.asarray([point["target"] for point in control_points], dtype=np.float32)
    for model_name in CALIBRATION_MODEL_ORDER:
        model = calibration_profile.get("models", {}).get(model_name, {})
        model_rows.append(
            {
                "model": model_name,
                "selected": str(model_name == selected_model),
                "available": str(model.get("available", False)),
                "reason": model.get("reason", ""),
                "rmse": "" if model.get("rmse") is None else f"{model['rmse']:.4f}",
                "mean_error": "" if model.get("mean_error") is None else f"{model['mean_error']:.4f}",
                "max_error": "" if model.get("max_error") is None else f"{model['max_error']:.4f}",
                "point_count": model.get("point_count", ""),
                "inlier_count": model.get("inlier_count", ""),
                "inlier_ratio": "" if model.get("inlier_ratio") is None else f"{model['inlier_ratio']:.4f}",
                "ransac_reprojection_threshold_px": model.get("ransac_reprojection_threshold_px", ""),
                "matrix": json.dumps(model.get("matrix", "")),
            }
        )
        if model.get("available") and len(control_points):
            predicted_points = _transform_points(source_points, model.get("matrix"))
            errors = np.linalg.norm(predicted_points - target_points, axis=1)
            for point_index, point in enumerate(control_points):
                point_error_rows.append(
                    {
                        "model": model_name,
                        "selected": str(model_name == selected_model),
                        "point_id": point.get("point_id", str(point_index + 1)),
                        "source_x": f"{source_points[point_index, 0]:.4f}",
                        "source_y": f"{source_points[point_index, 1]:.4f}",
                        "target_x": f"{target_points[point_index, 0]:.4f}",
                        "target_y": f"{target_points[point_index, 1]:.4f}",
                        "predicted_x": f"{predicted_points[point_index, 0]:.4f}",
                        "predicted_y": f"{predicted_points[point_index, 1]:.4f}",
                        "error": f"{errors[point_index]:.4f}",
                    }
                )

    with open(model_metrics_path, "w", newline="", encoding="utf-8") as metrics_file:
        writer = csv.DictWriter(metrics_file, fieldnames=model_fieldnames)
        writer.writeheader()
        writer.writerows(model_rows)

    point_error_fieldnames = [
        "model",
        "selected",
        "point_id",
        "source_x",
        "source_y",
        "target_x",
        "target_y",
        "predicted_x",
        "predicted_y",
        "error",
    ]
    with open(point_errors_path, "w", newline="", encoding="utf-8") as point_file:
        writer = csv.DictWriter(point_file, fieldnames=point_error_fieldnames)
        writer.writeheader()
        writer.writerows(point_error_rows)

    return model_metrics_path


def export_alignment_debug_samples(
    output_root,
    dataset_name,
    burn_set_name,
    pairs,
    sample_count=None,
    calibration_profile=None,
):
    if not pairs:
        return None

    sample_count = CORRECTION_VALIDATION_SAMPLE_COUNT if sample_count is None else sample_count
    debug_root = os.path.join(output_root, CORRECTION_VALIDATION_DIRNAME)
    os.makedirs(debug_root, exist_ok=True)
    summary_path = os.path.join(debug_root, "correction_validation_summary.csv")
    candidate_summary_path = os.path.join(debug_root, "alignment_candidate_metrics.csv")
    _write_manual_calibration_model_metrics(debug_root, calibration_profile)
    fieldnames = [
        "sample_index",
        "detected_camera",
        "rgb_filename",
        "thermal_preview_filename",
        "visual_review_status",
        "base_crop_box",
        "crop_only_shift",
        "crop_only_final_crop_box",
        "final_shift",
        "final_final_crop_box",
        "selected_model",
        "selected_model_rmse",
        "translation_x",
        "translation_y",
        "scale_x",
        "scale_y",
        "final_transform_matrix",
        "alignment_status",
        "alignment_confidence_level",
        "alignment_fallback_used",
        "alignment_good_matches",
        "alignment_inliers",
        "alignment_inlier_ratio",
        "alignment_mean_reprojection_error_px",
        "alignment_reasons",
        "auto_align_questionable_reasons",
        "manual_calibration_model",
        "manual_calibration_rmse",
        "manual_calibration_improvement_vs_crop_only",
        "manual_calibration_transform_matrix",
        "calibration_profile_path",
    ]
    candidate_fieldnames = [
        "sample_index",
        "rgb_filename",
        "candidate_index",
        "representation",
        "transform_type",
        "status",
        "confidence_level",
        "accepted",
        "raw_good_matches",
        "good_matches",
        "match_grid_cells",
        "inliers",
        "inlier_grid_cells",
        "inlier_ratio",
        "mean_reprojection_error_px",
        "max_reprojection_error_px",
        "scale_x",
        "scale_y",
        "scale_ratio",
        "rotation_degrees",
        "skew_dot",
        "determinant",
        "translation_x",
        "translation_y",
        "reasons",
    ]

    rows = []
    candidate_rows = []
    for sample_number, pair_index in enumerate(_sample_pair_indices(len(pairs), sample_count), start=1):
        pair = pairs[pair_index]
        thermal_preview_path, _ = _select_corrected_fov_thermal_source(pair)
        thermal_shift_source_path = thermal_preview_path
        manual_image = None
        manual_debug = None
        crop_only_image, crop_only_debug = generate_corrected_fov(
            pair,
            mode="CROP_ONLY",
            dataset_name=dataset_name,
            burn_set_name=burn_set_name,
            calibration_profile=None,
            camera_used=pair.get("detected_camera"),
            return_debug_info=True,
        )
        auto_align_image, auto_align_debug = generate_corrected_fov(
            pair,
            mode="AUTO_ALIGN",
            dataset_name=dataset_name,
            burn_set_name=burn_set_name,
            calibration_profile=calibration_profile,
            camera_used=pair.get("detected_camera"),
            return_debug_info=True,
        )
        if calibration_profile is not None:
            manual_image, manual_debug = generate_corrected_fov(
                pair,
                mode="CALIBRATION_PROFILE",
                dataset_name=dataset_name,
                burn_set_name=burn_set_name,
                calibration_profile=calibration_profile,
                camera_used=pair.get("detected_camera"),
                return_debug_info=True,
            )

        thermal_overlay_source = _load_debug_preview_image(thermal_preview_path)
        debug_image, _, _ = _build_alignment_debug_image(
            pair["rgb"]["filepath"],
            thermal_preview_path,
            thermal_shift_source_path,
            dataset_name=dataset_name,
            burn_set_name=burn_set_name,
            calibration_profile=calibration_profile,
            camera_used=pair.get("detected_camera"),
        )
        debug_image_path = os.path.join(debug_root, f"sample_{sample_number:02d}.png")
        debug_image.save(debug_image_path)
        debug_image.close()
        _save_alignment_candidate_debug_images(
            debug_root,
            sample_number,
            pair["rgb"]["filepath"],
            thermal_preview_path,
            auto_align_debug,
        )
        crop_overlay = _blend_rgb_thermal_overlay(crop_only_image, thermal_overlay_source)
        auto_overlay = _blend_rgb_thermal_overlay(auto_align_image, thermal_overlay_source)
        manual_overlay = (
            _blend_rgb_thermal_overlay(manual_image, thermal_overlay_source)
            if manual_image is not None
            else None
        )
        sample_prefix = f"sample_{sample_number:02d}"
        crop_only_image.save(os.path.join(debug_root, f"{sample_prefix}_crop_only_corrected_fov.png"))
        crop_overlay.save(os.path.join(debug_root, f"{sample_prefix}_overlay_crop_only_vs_thermal.png"))
        auto_overlay.save(os.path.join(debug_root, f"{sample_prefix}_overlay_auto_align_vs_thermal.png"))
        auto_align_image.save(os.path.join(debug_root, f"{sample_prefix}_auto_align_best.png"))
        if manual_image is not None:
            manual_image.save(os.path.join(debug_root, f"{sample_prefix}_manual_calibration.png"))
            manual_overlay.save(os.path.join(debug_root, f"{sample_prefix}_overlay_manual_calibration_vs_thermal.png"))
        comparison_grid = _build_validation_comparison_grid(
            [
                ("Crop-Only Corrected FOV", crop_only_image),
                (f"AUTO_ALIGN / SIFT ({auto_align_debug['selected_model']})", auto_align_image),
                (
                    f"Manual Calibration ({manual_debug['selected_model']})"
                    if manual_debug is not None
                    else "Manual Calibration",
                    manual_image,
                ),
                ("Thermal", thermal_overlay_source),
            ]
        )
        comparison_grid.save(os.path.join(debug_root, f"{sample_prefix}_comparison_crop_sift_manual_thermal.png"))
        comparison_grid.close()
        crop_overlay.close()
        auto_overlay.close()
        if manual_overlay is not None:
            manual_overlay.close()
        crop_only_image.close()
        auto_align_image.close()
        if manual_image is not None:
            manual_image.close()
        thermal_overlay_source.close()

        alignment = auto_align_debug.get("feature_alignment", _default_feature_alignment_result())
        manual_summary = manual_debug.get("selected_model_summary", {}) if manual_debug is not None else {}
        manual_improvement = (
            None
            if calibration_profile is None
            else calibration_profile.get("rmse_improvement_vs_crop_only")
        )
        for candidate_index, candidate in enumerate(auto_align_debug.get("alignment_candidates", []), start=1):
            candidate_rows.append(
                {
                    "sample_index": sample_number,
                    "rgb_filename": pair["rgb"]["filename"],
                    "candidate_index": candidate_index,
                    "representation": candidate.get("representation", ""),
                    "transform_type": candidate.get("transform_type", ""),
                    "status": candidate.get("status", ""),
                    "confidence_level": candidate.get("confidence_level", ""),
                    "accepted": str(candidate.get("accepted", False)),
                    "raw_good_matches": candidate.get("raw_good_matches", ""),
                    "good_matches": candidate.get("good_matches", ""),
                    "match_grid_cells": candidate.get("match_grid_cells", ""),
                    "inliers": candidate.get("inliers", ""),
                    "inlier_grid_cells": candidate.get("inlier_grid_cells", ""),
                    "inlier_ratio": candidate.get("inlier_ratio", ""),
                    "mean_reprojection_error_px": (
                        ""
                        if candidate.get("mean_reprojection_error_px") is None
                        else f"{candidate['mean_reprojection_error_px']:.4f}"
                    ),
                    "max_reprojection_error_px": (
                        ""
                        if candidate.get("max_reprojection_error_px") is None
                        else f"{candidate['max_reprojection_error_px']:.4f}"
                    ),
                    "scale_x": f"{candidate.get('scale_x', 1.0):.6f}",
                    "scale_y": f"{candidate.get('scale_y', 1.0):.6f}",
                    "scale_ratio": f"{candidate.get('scale_ratio', 1.0):.6f}",
                    "rotation_degrees": f"{candidate.get('rotation_degrees', 0.0):.4f}",
                    "skew_dot": f"{candidate.get('skew_dot', 0.0):.6f}",
                    "determinant": f"{candidate.get('determinant', 1.0):.6f}",
                    "translation_x": f"{candidate.get('translation_x', 0.0):.4f}",
                    "translation_y": f"{candidate.get('translation_y', 0.0):.4f}",
                    "reasons": " | ".join(candidate.get("reasons", [])),
                }
            )
        row = {
            "sample_index": sample_number,
            "detected_camera": pair.get("detected_camera", ""),
            "rgb_filename": pair["rgb"]["filename"],
            "thermal_preview_filename": os.path.basename(thermal_preview_path),
            "visual_review_status": VISUAL_ALIGNMENT_REVIEW_DEFAULT,
            "base_crop_box": str(crop_only_debug["base_crop_box"]),
            "crop_only_shift": str(crop_only_debug["applied_shift"]),
            "crop_only_final_crop_box": str(crop_only_debug["final_crop_box"]),
            "final_shift": str(auto_align_debug["applied_shift"]),
            "final_final_crop_box": str(auto_align_debug["final_crop_box"]),
            "selected_model": auto_align_debug["selected_model"],
            "selected_model_rmse": (
                ""
                if auto_align_debug["selected_model_summary"]["rmse"] is None
                else f"{auto_align_debug['selected_model_summary']['rmse']:.4f}"
            ),
            "translation_x": f"{alignment.get('translation_x', 0.0):.4f}",
            "translation_y": f"{alignment.get('translation_y', 0.0):.4f}",
            "scale_x": f"{alignment.get('scale_x', 1.0):.6f}",
            "scale_y": f"{alignment.get('scale_y', 1.0):.6f}",
            "final_transform_matrix": json.dumps(auto_align_debug["final_transform_matrix"]),
            "alignment_status": alignment.get("status", ""),
            "alignment_confidence_level": alignment.get("confidence_level", ""),
            "alignment_fallback_used": alignment.get("fallback_used", ""),
            "alignment_good_matches": alignment.get("good_matches", ""),
            "alignment_inliers": alignment.get("inliers", ""),
            "alignment_inlier_ratio": alignment.get("inlier_ratio", ""),
            "alignment_mean_reprojection_error_px": (
                ""
                if alignment.get("mean_reprojection_error_px") is None
                else f"{alignment['mean_reprojection_error_px']:.4f}"
            ),
            "alignment_reasons": " | ".join(alignment.get("reasons", [])),
            "auto_align_questionable_reasons": " | ".join(
                alignment.get("auto_align_questionable_reasons", [])
            ),
            "manual_calibration_model": "" if manual_debug is None else manual_debug["selected_model"],
            "manual_calibration_rmse": (
                ""
                if manual_summary.get("rmse") is None
                else f"{manual_summary['rmse']:.4f}"
            ),
            "manual_calibration_improvement_vs_crop_only": (
                ""
                if manual_improvement is None
                else f"{manual_improvement:.4f}"
            ),
            "manual_calibration_transform_matrix": (
                ""
                if manual_debug is None
                else json.dumps(manual_debug["final_transform_matrix"])
            ),
            "calibration_profile_path": (
                ""
                if auto_align_debug["calibration_profile"] is None
                else auto_align_debug["calibration_profile"].get("profile_path", "")
            ),
        }
        rows.append(row)
        print(
            f"[Correction Validation] {dataset_name}/{burn_set_name} sample {sample_number}: "
            f"base_crop_box={row['base_crop_box']} crop_only_final_crop_box={row['crop_only_final_crop_box']} "
            f"final_model={row['selected_model']} translation=({row['translation_x']}, {row['translation_y']}) "
            f"scale=({row['scale_x']}, {row['scale_y']})"
        )

    with open(summary_path, "w", newline="", encoding="utf-8") as summary_file:
        writer = csv.DictWriter(summary_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    with open(candidate_summary_path, "w", newline="", encoding="utf-8") as candidate_file:
        writer = csv.DictWriter(candidate_file, fieldnames=candidate_fieldnames)
        writer.writeheader()
        writer.writerows(candidate_rows)

    return debug_root


def _discover_presorted_sets(root_folder):
    burn_sets = []

    for current_root, dirnames, _ in os.walk(root_folder):
        if PRESORTED_RGB_DIRNAME not in dirnames:
            continue

        rgb_dir = os.path.join(current_root, PRESORTED_RGB_DIRNAME)
        thermal_tiff_dir = os.path.join(current_root, PRESORTED_THERMAL_TIFF_DIRNAME)
        if not os.path.isdir(thermal_tiff_dir):
            continue

        burn_sets.append(
            {
                "source_root": current_root,
                "rgb_dir": rgb_dir,
                "thermal_jpg_dir": os.path.join(current_root, PRESORTED_THERMAL_JPG_DIRNAME),
                "thermal_tiff_dir": thermal_tiff_dir,
                "cal_tiff_dir": os.path.join(current_root, PRESORTED_CAL_TIFF_DIRNAME),
            }
        )

    burn_sets.sort(key=lambda item: item["source_root"])
    return burn_sets


def _safe_image_size(filepath):
    try:
        with Image.open(filepath) as image:
            return image.size
    except Exception:
        return None


def _extract_exif_camera_text(filepath):
    try:
        with Image.open(filepath) as image:
            exif = image.getexif()
            values = [
                exif.get(271),   # Make
                exif.get(272),   # Model
                exif.get(42036), # LensModel
                exif.get(305),   # Software
            ]
    except Exception:
        return ""

    text_parts = []
    for value in values:
        if not value:
            continue
        cleaned = str(value).replace("\x00", "").strip()
        if cleaned:
            text_parts.append(cleaned)
    return " | ".join(text_parts).upper()


def _camera_from_resolution(image_size):
    if image_size is None:
        return None

    width, height = image_size
    normalized = (max(width, height), min(width, height))
    for camera_name, hint in CAMERA_RESOLUTION_HINTS.items():
        target_width, target_height = max(hint["target"]), min(hint["target"])
        if (
            hint["width_range"][0] <= normalized[0] <= hint["width_range"][1]
            and hint["height_range"][0] <= normalized[1] <= hint["height_range"][1]
        ):
            return {
                "camera": camera_name,
                "reason": f"resolution:{width}x{height}",
                "target_resolution": f"{target_width}x{target_height}",
            }
    return None


def _camera_from_exif(filepath):
    exif_text = _extract_exif_camera_text(filepath)
    if not exif_text:
        return None

    for camera_name, hints in CAMERA_EXIF_HINTS.items():
        if any(hint in exif_text for hint in hints):
            return {
                "camera": camera_name,
                "reason": f"exif:{exif_text}",
                "exif_text": exif_text,
            }
    return {
        "camera": None,
        "reason": f"exif_unmapped:{exif_text}",
        "exif_text": exif_text,
    }


def detect_camera_from_rgb_file(filepath, fallback_camera=None):
    image_size = _safe_image_size(filepath)
    resolution_guess = _camera_from_resolution(image_size)
    exif_guess = _camera_from_exif(filepath)

    selected_camera = None
    reasons = []
    if resolution_guess is not None:
        selected_camera = resolution_guess["camera"]
        reasons.append(resolution_guess["reason"])
    if exif_guess is not None and exif_guess.get("camera") is not None:
        reasons.append(exif_guess["reason"])
        if selected_camera is None:
            selected_camera = exif_guess["camera"]
        elif selected_camera != exif_guess["camera"]:
            reasons.append(f"resolution_primary_over_exif:{exif_guess['camera']}")
    elif exif_guess is not None:
        reasons.append(exif_guess["reason"])

    if selected_camera is None:
        selected_camera = fallback_camera or CAMERA_USED
        reasons.append(f"fallback:{selected_camera}")

    return {
        "camera": selected_camera,
        "image_size": image_size,
        "resolution_guess": resolution_guess["camera"] if resolution_guess is not None else None,
        "exif_guess": exif_guess.get("camera") if exif_guess is not None else None,
        "exif_text": exif_guess.get("exif_text", "") if exif_guess is not None else "",
        "reason": " | ".join(reasons),
        "filepath": filepath,
    }


def detect_camera_from_rgb_records(rgb_records, fallback_camera=None, sample_size=8):
    sampled_records = []
    for record in rgb_records:
        filepath = record.get("filepath")
        if filepath and os.path.exists(filepath):
            sampled_records.append(record)
        if len(sampled_records) >= sample_size:
            break

    detections = [
        detect_camera_from_rgb_file(record["filepath"], fallback_camera=fallback_camera)
        for record in sampled_records
    ]
    if not detections:
        return {
            "camera": fallback_camera or CAMERA_USED,
            "image_size": None,
            "reason": f"fallback:{fallback_camera or CAMERA_USED}",
            "sample_count": 0,
            "profile_camera": fallback_camera or CAMERA_USED,
        }

    camera_counts = {}
    for detection in detections:
        camera_counts[detection["camera"]] = camera_counts.get(detection["camera"], 0) + 1
    selected_camera = max(camera_counts.items(), key=lambda item: (item[1], item[0]))[0]

    representative = next(
        (detection for detection in detections if detection["camera"] == selected_camera),
        detections[0],
    )
    reasons = []
    seen_reasons = set()
    for detection in detections:
        reason = detection["reason"]
        if reason in seen_reasons:
            continue
        seen_reasons.add(reason)
        reasons.append(reason)
    dimensions = [detection["image_size"] for detection in detections if detection["image_size"] is not None]
    dimension_summary = ""
    if dimensions:
        unique_dimensions = sorted({f"{width}x{height}" for width, height in dimensions})
        dimension_summary = ", ".join(unique_dimensions[:3])

    return {
        "camera": selected_camera,
        "profile_camera": selected_camera,
        "image_size": representative.get("image_size"),
        "dimension_summary": dimension_summary,
        "reason": " || ".join(reasons),
        "sample_count": len(detections),
        "samples": detections,
        "profile_path": "",
    }


def detect_camera_from_folder(folder_path, fallback_camera=None):
    rgb_candidates = []
    for entry in sorted(os.listdir(folder_path)):
        filepath = os.path.join(folder_path, entry)
        if not os.path.isfile(filepath):
            continue
        if os.path.splitext(entry)[1].lower() not in {".jpg", ".jpeg"}:
            continue
        image_size = _safe_image_size(filepath)
        if image_size is None:
            continue
        width, height = image_size
        if max(width, height) >= 1500:
            rgb_candidates.append({"filepath": filepath, "image_size": image_size})

    return detect_camera_from_rgb_records(rgb_candidates, fallback_camera=fallback_camera)


def _infer_standard_modality(filepath):
    filename = os.path.basename(filepath)
    name_upper = filename.upper()
    ext = os.path.splitext(filename)[1].lower()
    stem_upper = os.path.splitext(filename)[0].upper()

    if ext in {".tif", ".tiff"}:
        if "CAL" in stem_upper:
            return "cal_tiff"
        return "thermal_tiff"

    if ext not in {".jpg", ".jpeg"}:
        return None

    if name_upper.startswith("MAX_") or "_W" in stem_upper:
        return "rgb"
    if name_upper.startswith("IRX_") or "_T" in stem_upper:
        return "thermal_jpg"

    image_size = _safe_image_size(filepath)
    if image_size is None:
        return None

    width, height = image_size
    if max(width, height) >= 1500:
        return "rgb"
    if (
        abs(width - CORRECTED_FOV_OUTPUT_SIZE[0]) <= 48
        and abs(height - CORRECTED_FOV_OUTPUT_SIZE[1]) <= 48
    ) or (
        abs(width - CORRECTED_FOV_OUTPUT_SIZE[1]) <= 48
        and abs(height - CORRECTED_FOV_OUTPUT_SIZE[0]) <= 48
    ):
        return "thermal_jpg"
    return None


def _collect_flat_dataset_records(folder):
    if not os.path.isdir(folder):
        return None

    rgb_records = []
    thermal_jpg_records = []
    thermal_tiff_records = []
    cal_tiff_records = []

    for file in sorted(os.listdir(folder)):
        filepath = os.path.join(folder, file)
        if not os.path.isfile(filepath):
            continue

        ext = os.path.splitext(file)[1].lower()
        if ext not in {".jpg", ".jpeg", ".tif", ".tiff"}:
            continue

        modality = _infer_standard_modality(filepath)
        if modality is None:
            continue

        record = {
            "filename": file,
            "filepath": filepath,
            "datetime": _extract_capture_datetime(filepath),
            "index": _numeric_suffix(file),
            "image_size": _safe_image_size(filepath),
        }

        if modality == "rgb":
            rgb_records.append(record)
        elif modality == "cal_tiff":
            cal_tiff_records.append(record)
        elif modality == "thermal_tiff":
            thermal_tiff_records.append(record)
        elif modality == "thermal_jpg":
            thermal_jpg_records.append(record)

    if not rgb_records or not thermal_tiff_records:
        return None

    return {
        "source_root": folder,
        "rgb_records": rgb_records,
        "thermal_jpg_records": thermal_jpg_records,
        "thermal_tiff_records": thermal_tiff_records,
        "cal_tiff_records": cal_tiff_records,
        "layout": "flat_mixed",
    }


def _discover_presorted_datasets(root_folder):
    if not os.path.isdir(root_folder):
        return []

    datasets = []
    for entry in sorted(os.listdir(root_folder)):
        dataset_root = os.path.join(root_folder, entry)
        if not os.path.isdir(dataset_root):
            continue

        burn_sets = _discover_presorted_sets(dataset_root)
        seen_roots = {os.path.abspath(burn_set["source_root"]) for burn_set in burn_sets}

        for current_root, _, _ in os.walk(dataset_root):
            flat_dataset = _collect_flat_dataset_records(current_root)
            if flat_dataset is None:
                continue
            current_root_abs = os.path.abspath(flat_dataset["source_root"])
            if current_root_abs in seen_roots:
                continue
            burn_sets.append(flat_dataset)
            seen_roots.add(current_root_abs)

        burn_sets.sort(key=lambda item: item["source_root"])
        if burn_sets:
            datasets.append({"name": entry, "root": dataset_root, "burn_sets": burn_sets})

    return datasets


def _collect_media_records(folder):
    if not os.path.isdir(folder):
        return []

    records = []
    valid_exts = {".jpg", ".jpeg", ".tif", ".tiff"}
    for file in sorted(os.listdir(folder)):
        filepath = os.path.join(folder, file)
        if not os.path.isfile(filepath):
            continue
        if os.path.splitext(file)[1].lower() not in valid_exts:
            continue

        records.append(
            {
                "filename": file,
                "filepath": filepath,
                "datetime": _extract_capture_datetime(filepath),
                "index": _numeric_suffix(file),
                "image_size": _safe_image_size(filepath),
            }
        )

    return records


def _time_delta_seconds(first_dt, second_dt):
    if first_dt is None or second_dt is None:
        return None
    return abs((first_dt - second_dt).total_seconds())


def _unique_reasons(reasons):
    unique = []
    seen = set()
    for reason in reasons:
        if not reason or reason in seen:
            continue
        unique.append(reason)
        seen.add(reason)
    return unique


def _record_matches_expected_pattern(record, modality):
    if record is None:
        return False

    name_upper = record["filename"].upper()
    ext = os.path.splitext(record["filename"])[1].lower()
    if modality == "rgb":
        return name_upper.startswith("MAX_") and "_W" in name_upper and ext in {".jpg", ".jpeg"}
    if modality == "thermal_jpg":
        return (
            name_upper.startswith("IRX_")
            and "_T" in name_upper
            and "CAL" not in name_upper
            and ext in {".jpg", ".jpeg"}
        )
    if modality == "thermal_tiff":
        return (
            name_upper.startswith("IRX_")
            and "_T" in name_upper
            and "CAL" not in name_upper
            and ext in {".tif", ".tiff"}
        )
    if modality == "cal_tiff":
        return name_upper.startswith("IRX_") and "CAL" in name_upper and ext in {".tif", ".tiff"}
    return False


def _timestamp_score(time_delta):
    if time_delta is None:
        return 0.0, ["timestamp_unavailable"]

    if time_delta <= PAIR_TIME_TOLERANCE_SECONDS:
        closeness = 1.0 - (time_delta / max(PAIR_TIME_TOLERANCE_SECONDS, 0.001))
        return 18.0 + (closeness * 14.0), []

    soft_limit = PAIR_TIME_TOLERANCE_SECONDS * 3.0
    if time_delta <= soft_limit:
        closeness = 1.0 - (
            (time_delta - PAIR_TIME_TOLERANCE_SECONDS)
            / max((soft_limit - PAIR_TIME_TOLERANCE_SECONDS), 0.001)
        )
        return max(2.0, closeness * 12.0), [f"timestamp_delta_high:{time_delta:.3f}s"]

    return 0.0, [f"timestamp_delta_high:{time_delta:.3f}s"]


def _confidence_level(score):
    if score >= HIGH_CONFIDENCE_THRESHOLD:
        return "HIGH"
    if score >= MEDIUM_CONFIDENCE_THRESHOLD:
        return "MEDIUM"
    return "LOW"


def _candidate_sort_key(target_record, candidate_record):
    time_delta = _time_delta_seconds(target_record["datetime"], candidate_record["datetime"])
    return (
        float("inf") if time_delta is None else time_delta,
        candidate_record["filename"],
    )


def _score_candidate(target_record, candidate_record, modality, strategy):
    score = 0.0
    reasons = []

    numeric_match = (
        target_record["index"] is not None
        and candidate_record["index"] is not None
        and target_record["index"] == candidate_record["index"]
    )
    if numeric_match:
        score += 46.0
    else:
        reasons.append("numeric_suffix_mismatch")

    time_delta = _time_delta_seconds(target_record["datetime"], candidate_record["datetime"])
    timestamp_points, timestamp_reasons = _timestamp_score(time_delta)
    score += timestamp_points
    reasons.extend(timestamp_reasons)

    if _record_matches_expected_pattern(candidate_record, modality):
        score += 10.0
    else:
        reasons.append("filename_pattern_unexpected")

    if strategy == "suffix":
        score += 4.0
    elif strategy == "timestamp" and time_delta is not None and time_delta <= PAIR_TIME_TOLERANCE_SECONDS:
        score += 4.0
    elif strategy == "suffix+timestamp":
        score += 8.0

    return {
        "record": candidate_record,
        "strategy": strategy,
        "score": min(score, 100.0),
        "time_delta": time_delta,
        "numeric_match": numeric_match,
        "reasons": _unique_reasons(reasons),
    }


def _select_candidate(target_record, candidate_records, used_candidates, modality):
    available_candidates = [
        candidate for candidate in candidate_records if candidate["filepath"] not in used_candidates
    ]
    if not available_candidates:
        return {
            "record": None,
            "strategy": "missing",
            "score": 0.0,
            "time_delta": None,
            "numeric_match": False,
            "reasons": [f"{modality}_missing"],
        }

    suffix_candidate = None
    if target_record["index"] is not None:
        exact_matches = [
            candidate for candidate in available_candidates if candidate["index"] == target_record["index"]
        ]
        if exact_matches:
            suffix_candidate = min(
                exact_matches,
                key=lambda candidate: _candidate_sort_key(target_record, candidate),
            )

    timestamp_candidate = min(
        available_candidates,
        key=lambda candidate: _candidate_sort_key(target_record, candidate),
    )

    evaluations = {}
    if suffix_candidate is not None:
        strategy = "suffix+timestamp" if suffix_candidate["filepath"] == timestamp_candidate["filepath"] else "suffix"
        evaluations[suffix_candidate["filepath"]] = _score_candidate(
            target_record,
            suffix_candidate,
            modality,
            strategy,
        )

    if timestamp_candidate["filepath"] not in evaluations:
        evaluations[timestamp_candidate["filepath"]] = _score_candidate(
            target_record,
            timestamp_candidate,
            modality,
            "timestamp",
        )

    ranked = sorted(
        evaluations.values(),
        key=lambda evaluation: (
            evaluation["score"],
            1 if evaluation["numeric_match"] else 0,
            -(float("inf") if evaluation["time_delta"] is None else evaluation["time_delta"]),
        ),
        reverse=True,
    )
    best_evaluation = ranked[0]

    if len(ranked) > 1 and ranked[0]["record"]["filepath"] != ranked[1]["record"]["filepath"]:
        best_evaluation["reasons"] = _unique_reasons(
            best_evaluation["reasons"]
            + [f"preferred_{ranked[0]['strategy']}_over_{ranked[1]['strategy']}"]
        )

    return best_evaluation


def _pair_confidence(rgb_record, thermal_jpg_eval, thermal_tiff_eval, cal_tiff_eval):
    score = 10.0
    reasons = []

    if _record_matches_expected_pattern(rgb_record, "rgb"):
        score += 10.0
    else:
        reasons.append("rgb_filename_pattern_unexpected")

    for modality_name, evaluation, weight, missing_penalty in [
        ("thermal_tiff", thermal_tiff_eval, 50.0, 12.0),
        ("thermal_jpg", thermal_jpg_eval, 18.0, 5.0),
        ("cal_tiff", cal_tiff_eval, 12.0, 3.0),
    ]:
        if evaluation["record"] is None:
            reasons.append(f"{modality_name}_missing")
            score -= missing_penalty
            continue

        normalized_score = min(evaluation["score"], 100.0) / 100.0
        score += weight * normalized_score
        reasons.extend(evaluation["reasons"])

    score = max(0.0, min(score, 100.0))
    return {
        "score": round(score, 1),
        "level": _confidence_level(score),
        "reasons": _unique_reasons(reasons),
    }


def _apply_confidence_penalty(decision, penalty_points, reason):
    decision["confidence"]["score"] = round(max(0.0, decision["confidence"]["score"] - penalty_points), 1)
    decision["confidence"]["reasons"] = _unique_reasons(
        decision["confidence"]["reasons"] + [reason]
    )
    decision["confidence"]["level"] = _confidence_level(decision["confidence"]["score"])


def _nearest_timestamp_map(rgb_records, candidate_records):
    mapping = {}
    if not candidate_records:
        return mapping

    for rgb_record in rgb_records:
        best_candidate = min(
            candidate_records,
            key=lambda candidate: _candidate_sort_key(rgb_record, candidate),
        )
        mapping[rgb_record["filepath"]] = {
            "candidate_filepath": best_candidate["filepath"],
            "time_delta": _time_delta_seconds(rgb_record["datetime"], best_candidate["datetime"]),
        }
    return mapping


def _apply_neighbor_consistency(decisions, thermal_tiff_nearest_map):
    accepted_decisions = [decision for decision in decisions if decision["status"].startswith("accepted")]
    accepted_decisions.sort(
        key=lambda decision: (
            decision["rgb"]["index"] is None,
            float("inf") if decision["rgb"]["index"] is None else decision["rgb"]["index"],
            decision["rgb"]["datetime"],
            decision["rgb"]["filename"],
        )
    )

    for idx, decision in enumerate(accepted_decisions):
        tiff_evaluation = decision["evaluations"]["thermal_tiff"]
        if idx > 0 and idx < len(accepted_decisions) - 1:
            prev_decision = accepted_decisions[idx - 1]
            next_decision = accepted_decisions[idx + 1]
            prev_tiff_eval = prev_decision["evaluations"]["thermal_tiff"]
            next_tiff_eval = next_decision["evaluations"]["thermal_tiff"]

            current_delta = float("inf") if tiff_evaluation["time_delta"] is None else tiff_evaluation["time_delta"]
            prev_delta = float("inf") if prev_tiff_eval["time_delta"] is None else prev_tiff_eval["time_delta"]
            next_delta = float("inf") if next_tiff_eval["time_delta"] is None else next_tiff_eval["time_delta"]

            if (
                current_delta > PAIR_TIME_TOLERANCE_SECONDS
                and prev_delta <= PAIR_TIME_TOLERANCE_SECONDS
                and next_delta <= PAIR_TIME_TOLERANCE_SECONDS
            ):
                _apply_confidence_penalty(decision, 12.0, "neighbor_timestamp_jump")

            prev_rgb_index = prev_decision["rgb"]["index"]
            current_rgb_index = decision["rgb"]["index"]
            next_rgb_index = next_decision["rgb"]["index"]
            prev_tiff_index = prev_decision["thermal_tiff"]["index"]
            current_tiff_index = decision["thermal_tiff"]["index"]
            next_tiff_index = next_decision["thermal_tiff"]["index"]
            if all(
                index is not None
                for index in [
                    prev_rgb_index,
                    current_rgb_index,
                    next_rgb_index,
                    prev_tiff_index,
                    current_tiff_index,
                    next_tiff_index,
                ]
            ):
                prev_offset = prev_tiff_index - prev_rgb_index
                current_offset = current_tiff_index - current_rgb_index
                next_offset = next_tiff_index - next_rgb_index
                if prev_offset == next_offset and current_offset != prev_offset:
                    _apply_confidence_penalty(decision, 10.0, "neighbor_index_pattern_break")

            if (
                not tiff_evaluation["numeric_match"]
                and prev_tiff_eval["numeric_match"]
                and next_tiff_eval["numeric_match"]
            ):
                _apply_confidence_penalty(decision, 8.0, "neighbors_support_numeric_pattern")

    for current_decision, next_decision in zip(accepted_decisions, accepted_decisions[1:]):
        current_best = thermal_tiff_nearest_map.get(current_decision["rgb"]["filepath"])
        next_best = thermal_tiff_nearest_map.get(next_decision["rgb"]["filepath"])
        if not current_best or not next_best:
            continue
        if current_best["candidate_filepath"] != next_best["candidate_filepath"]:
            continue

        current_delta = current_decision["evaluations"]["thermal_tiff"]["time_delta"]
        next_delta = next_decision["evaluations"]["thermal_tiff"]["time_delta"]
        current_delta = float("inf") if current_delta is None else current_delta
        next_delta = float("inf") if next_delta is None else next_delta
        lower_confidence_decision = current_decision if current_delta >= next_delta else next_decision
        _apply_confidence_penalty(lower_confidence_decision, 8.0, "shared_best_timestamp_candidate_with_neighbor")


def _finalize_pair_status(decision):
    if decision["thermal_tiff"] is None:
        decision["status"] = "skipped_missing_thermal_tiff"
    elif decision["confidence"]["level"] == "HIGH":
        decision["status"] = "accepted_high"
    elif decision["confidence"]["level"] == "MEDIUM":
        decision["status"] = "accepted_medium_review"
    else:
        decision["status"] = "accepted_low_review"
        decision["confidence"]["reasons"] = _unique_reasons(
            decision["confidence"]["reasons"] + ["accepted_low_no_better_candidate"]
        )
    decision["review_required"] = decision["status"] != "accepted_high"


def _format_time_delta_for_csv(time_delta):
    if time_delta is None:
        return ""
    return f"{time_delta:.3f}"


def _pair_log_row(decision):
    alignment = decision.get("feature_alignment", _default_feature_alignment_result())
    return {
        "output_stem": decision.get("output_stem", ""),
        "status": decision["status"],
        "confidence_level": decision["confidence"]["level"],
        "confidence_score": f"{decision['confidence']['score']:.1f}",
        "detected_camera": decision.get("detected_camera", ""),
        "camera_dimension_summary": decision.get("camera_dimension_summary", ""),
        "camera_detection_reason": decision.get("camera_detection_reason", ""),
        "fov_correction_mode": decision.get("fov_correction_mode", _get_fov_correction_mode()),
        "thermal_source_used": decision.get("thermal_source_used", ""),
        "thermal_source_path": decision.get("thermal_source_path", ""),
        "final_transform_matrix": json.dumps(decision.get("final_transform_matrix", "")),
        "fallback_occurred": str(decision.get("fallback_occurred", "")),
        "final_crop_box": str(decision.get("final_crop_box", "")),
        "crop_shrink": str(decision.get("crop_shrink", "")),
        "calibration_profile_available": decision.get("calibration_profile_path", ""),
        "alignment_status": alignment.get("status", ""),
        "alignment_confidence_level": alignment.get("confidence_level", ""),
        "alignment_fallback_used": alignment.get("fallback_used", ""),
        "alignment_representation": alignment.get("representation", ""),
        "alignment_candidate_count": alignment.get("candidate_count", ""),
        "alignment_transform_type": alignment.get("transform_type", ""),
        "alignment_raw_good_matches": alignment.get("raw_good_matches", ""),
        "alignment_good_matches": alignment.get("good_matches", ""),
        "alignment_inliers": alignment.get("inliers", ""),
        "alignment_inlier_ratio": alignment.get("inlier_ratio", ""),
        "alignment_match_grid_cells": alignment.get("match_grid_cells", ""),
        "alignment_inlier_grid_cells": alignment.get("inlier_grid_cells", ""),
        "alignment_mean_reprojection_error_px": (
            ""
            if alignment.get("mean_reprojection_error_px") is None
            else f"{alignment['mean_reprojection_error_px']:.4f}"
        ),
        "alignment_max_reprojection_error_px": (
            ""
            if alignment.get("max_reprojection_error_px") is None
            else f"{alignment['max_reprojection_error_px']:.4f}"
        ),
        "alignment_scale_x": f"{alignment.get('scale_x', 1.0):.6f}",
        "alignment_scale_y": f"{alignment.get('scale_y', 1.0):.6f}",
        "alignment_scale_ratio": f"{alignment.get('scale_ratio', 1.0):.6f}",
        "alignment_rotation_degrees": f"{alignment.get('rotation_degrees', 0.0):.4f}",
        "alignment_skew_dot": f"{alignment.get('skew_dot', 0.0):.6f}",
        "alignment_determinant": f"{alignment.get('determinant', 1.0):.6f}",
        "alignment_translation_x": f"{alignment.get('translation_x', 0.0):.4f}",
        "alignment_translation_y": f"{alignment.get('translation_y', 0.0):.4f}",
        "alignment_reasons": " | ".join(alignment.get("reasons", [])),
        "auto_align_questionable_reasons": " | ".join(
            alignment.get("auto_align_questionable_reasons", [])
        ),
        "rgb_filename": decision["rgb"]["filename"],
        "rgb_index": "" if decision["rgb"]["index"] is None else decision["rgb"]["index"],
        "thermal_jpg_filename": "" if decision["thermal_jpg"] is None else decision["thermal_jpg"]["filename"],
        "thermal_tiff_filename": "" if decision["thermal_tiff"] is None else decision["thermal_tiff"]["filename"],
        "cal_tiff_filename": "" if decision["cal_tiff"] is None else decision["cal_tiff"]["filename"],
        "thermal_jpg_numeric_match": str(decision["evaluations"]["thermal_jpg"]["numeric_match"]),
        "thermal_tiff_numeric_match": str(decision["evaluations"]["thermal_tiff"]["numeric_match"]),
        "cal_tiff_numeric_match": str(decision["evaluations"]["cal_tiff"]["numeric_match"]),
        "thermal_jpg_timestamp_delta_seconds": _format_time_delta_for_csv(
            decision["evaluations"]["thermal_jpg"]["time_delta"]
        ),
        "thermal_tiff_timestamp_delta_seconds": _format_time_delta_for_csv(
            decision["evaluations"]["thermal_tiff"]["time_delta"]
        ),
        "cal_tiff_timestamp_delta_seconds": _format_time_delta_for_csv(
            decision["evaluations"]["cal_tiff"]["time_delta"]
        ),
        "thermal_jpg_match_strategy": decision["evaluations"]["thermal_jpg"]["strategy"],
        "thermal_tiff_match_strategy": decision["evaluations"]["thermal_tiff"]["strategy"],
        "cal_tiff_match_strategy": decision["evaluations"]["cal_tiff"]["strategy"],
        "downgrade_reasons": " | ".join(decision["confidence"]["reasons"]),
    }


def _write_pairing_logs(output_root, decisions):
    if not decisions:
        return

    fieldnames = list(_pair_log_row(decisions[0]).keys())
    log_rows = [_pair_log_row(decision) for decision in decisions]
    review_rows = [
        row
        for row in log_rows
        if row["confidence_level"] in {"MEDIUM", "LOW"} or row["status"].startswith("skipped")
    ]

    with open(
        os.path.join(output_root, PRESORTED_PAIRING_LOG_FILENAME),
        "w",
        newline="",
        encoding="utf-8",
    ) as log_file:
        writer = csv.DictWriter(log_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(log_rows)

    with open(
        os.path.join(output_root, PRESORTED_PAIRING_REVIEW_FILENAME),
        "w",
        newline="",
        encoding="utf-8",
    ) as review_file:
        writer = csv.DictWriter(review_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(review_rows)


def _pair_presorted_records(rgb_records, thermal_jpg_records, thermal_tiff_records, cal_tiff_records):
    decisions = []
    used_thermal_jpg = set()
    used_thermal_tiff = set()
    used_cal_tiff = set()
    thermal_tiff_nearest_map = _nearest_timestamp_map(rgb_records, thermal_tiff_records)

    ordered_rgb_records = sorted(
        rgb_records,
        key=lambda record: (
            record["index"] is None,
            float("inf") if record["index"] is None else record["index"],
            record["datetime"],
            record["filename"],
        ),
    )

    for rgb_record in ordered_rgb_records:
        thermal_tiff_evaluation = _select_candidate(
            rgb_record,
            thermal_tiff_records,
            used_thermal_tiff,
            "thermal_tiff",
        )
        thermal_jpg_evaluation = _select_candidate(
            rgb_record,
            thermal_jpg_records,
            used_thermal_jpg,
            "thermal_jpg",
        )
        cal_tiff_evaluation = _select_candidate(
            rgb_record,
            cal_tiff_records,
            used_cal_tiff,
            "cal_tiff",
        )

        if thermal_tiff_evaluation["record"] is not None:
            used_thermal_tiff.add(thermal_tiff_evaluation["record"]["filepath"])
        if thermal_jpg_evaluation["record"] is not None:
            used_thermal_jpg.add(thermal_jpg_evaluation["record"]["filepath"])
        if cal_tiff_evaluation["record"] is not None:
            used_cal_tiff.add(cal_tiff_evaluation["record"]["filepath"])

        decision = {
            "rgb": rgb_record,
            "thermal_jpg": thermal_jpg_evaluation["record"],
            "thermal_tiff": thermal_tiff_evaluation["record"],
            "cal_tiff": cal_tiff_evaluation["record"],
            "evaluations": {
                "thermal_jpg": thermal_jpg_evaluation,
                "thermal_tiff": thermal_tiff_evaluation,
                "cal_tiff": cal_tiff_evaluation,
            },
            "match_types": {
                "thermal_jpg": thermal_jpg_evaluation["strategy"],
                "thermal_tiff": thermal_tiff_evaluation["strategy"],
                "cal_tiff": cal_tiff_evaluation["strategy"],
            },
            "confidence": _pair_confidence(
                rgb_record,
                thermal_jpg_evaluation,
                thermal_tiff_evaluation,
                cal_tiff_evaluation,
            ),
            "output_stem": "",
        }
        _finalize_pair_status(decision)
        decisions.append(decision)

    _apply_neighbor_consistency(decisions, thermal_tiff_nearest_map)
    for decision in decisions:
        _finalize_pair_status(decision)

    accepted_pairs = [decision for decision in decisions if decision["status"].startswith("accepted")]
    confidence_counts = {
        "HIGH": sum(1 for decision in accepted_pairs if decision["confidence"]["level"] == "HIGH"),
        "MEDIUM": sum(1 for decision in accepted_pairs if decision["confidence"]["level"] == "MEDIUM"),
        "LOW": sum(1 for decision in accepted_pairs if decision["confidence"]["level"] == "LOW"),
    }

    return {
        "pairs": accepted_pairs,
        "decisions": decisions,
        "confidence_counts": confidence_counts,
        "review_count": sum(1 for decision in decisions if decision["review_required"]),
    }


def analyze_presorted_standard(input_folder=None):
    analysis_input_folder = os.path.abspath(input_folder if input_folder else INPUT_FOLDER)
    if not os.path.isdir(analysis_input_folder):
        raise FileNotFoundError(f"Input folder does not exist: {analysis_input_folder}")

    datasets = _discover_presorted_datasets(analysis_input_folder)
    analysis = []

    for dataset in datasets:
        dataset_entry = {
            "name": dataset["name"],
            "root": dataset["root"],
            "burn_sets": [],
        }

        for burn_set_id, burn_set in enumerate(dataset["burn_sets"], start=1):
            burn_set_name = f"burn_set_{burn_set_id:03d}"
            if burn_set.get("layout") == "flat_mixed":
                rgb_records = burn_set["rgb_records"]
                thermal_jpg_records = burn_set["thermal_jpg_records"]
                thermal_tiff_records = burn_set["thermal_tiff_records"]
                cal_tiff_records = burn_set["cal_tiff_records"]
            else:
                rgb_records = _collect_media_records(burn_set["rgb_dir"])
                thermal_jpg_records = _collect_media_records(burn_set["thermal_jpg_dir"])
                thermal_tiff_records = _collect_media_records(burn_set["thermal_tiff_dir"])
                cal_tiff_records = _collect_media_records(burn_set["cal_tiff_dir"])

            pairing_result = _pair_presorted_records(
                rgb_records, thermal_jpg_records, thermal_tiff_records, cal_tiff_records
            )
            pairs = pairing_result["pairs"]
            camera_detection = detect_camera_from_rgb_records(rgb_records)
            active_profile = load_calibration_profile(
                camera_used=camera_detection["profile_camera"],
                dataset_name=dataset["name"],
                burn_set_name=burn_set_name,
            )
            camera_detection["profile_path"] = (
                active_profile.get("profile_path", "") if active_profile is not None else ""
            )
            for pair in pairs:
                pair["dataset_name"] = dataset["name"]
                pair["burn_set_name"] = burn_set_name
                pair["detected_camera"] = camera_detection["camera"]
                pair["camera_detection_reason"] = camera_detection["reason"]
                pair["camera_image_size"] = camera_detection["image_size"]

            dataset_entry["burn_sets"].append(
                {
                    "name": burn_set_name,
                    "dataset_name": dataset["name"],
                    "source_root": burn_set["source_root"],
                    "layout": burn_set.get("layout", "nested"),
                    "rgb_count": len(rgb_records),
                    "thermal_jpg_count": len(thermal_jpg_records),
                    "thermal_tiff_count": len(thermal_tiff_records),
                    "cal_tiff_count": len(cal_tiff_records),
                    "pair_count": len(pairs),
                    "confidence_counts": pairing_result["confidence_counts"],
                    "review_count": pairing_result["review_count"],
                    "detected_camera": camera_detection["camera"],
                    "camera_image_size": camera_detection["image_size"],
                    "camera_dimension_summary": camera_detection.get("dimension_summary", ""),
                    "camera_detection_reason": camera_detection["reason"],
                    "correction_model": (
                        active_profile["selected_model"]
                        if active_profile and _get_fov_correction_mode() == "CALIBRATION_PROFILE"
                        else _get_fov_correction_mode().lower()
                    ),
                    "correction_rmse": (
                        active_profile.get("selected_model_summary", {}).get("rmse")
                        if active_profile is not None and _get_fov_correction_mode() == "CALIBRATION_PROFILE"
                        else None
                    ),
                    "calibration_profile_path": (
                        active_profile.get("profile_path")
                        if active_profile is not None
                        else ""
                    ),
                    "pairs": pairs,
                }
            )

        analysis.append(dataset_entry)

    return analysis


def detect_processing_mode(input_folder=None):
    effective_input_folder = os.path.abspath(input_folder if input_folder else INPUT_FOLDER)
    if not os.path.isdir(effective_input_folder):
        raise FileNotFoundError(f"Input folder does not exist: {effective_input_folder}")

    if _discover_presorted_datasets(effective_input_folder):
        return "PRESORTED_STANDARD"

    for current_root, _, filenames in os.walk(effective_input_folder):
        for filename in filenames:
            ext = os.path.splitext(filename)[1].lower()
            if ext in {".tif", ".tiff"}:
                return "PRESORTED_STANDARD"
            if ext in {".jpg", ".jpeg"} and _infer_standard_modality(os.path.join(current_root, filename)) is not None:
                return "PRESORTED_STANDARD"

    return "DJI_RAW"


def run_sort_pipeline(input_folder=None, output_folder=None, processing_mode=None, progress_callback=None):
    global INPUT_FOLDER
    global OUTPUT_FOLDER
    global PROCESSING_MODE

    effective_input_folder = os.path.abspath(input_folder if input_folder else INPUT_FOLDER)
    effective_output_folder = os.path.abspath(output_folder if output_folder else OUTPUT_FOLDER)
    selected_mode = processing_mode or PROCESSING_MODE
    if selected_mode == "AUTO":
        selected_mode = detect_processing_mode(effective_input_folder)

    INPUT_FOLDER = effective_input_folder
    OUTPUT_FOLDER = effective_output_folder
    PROCESSING_MODE = selected_mode

    print(f"Detected processing mode: {selected_mode}")
    if selected_mode == "PRESORTED_STANDARD":
        return process_presorted_standard(
            input_folder=effective_input_folder,
            output_folder=effective_output_folder,
            dry_run_only=False,
            progress_callback=progress_callback,
        )

    if not INPUT_FOLDER.endswith(os.sep):
        INPUT_FOLDER = INPUT_FOLDER + os.sep
    if not OUTPUT_FOLDER.endswith(os.sep):
        OUTPUT_FOLDER = OUTPUT_FOLDER + os.sep
    return raw_file_sorting()


def process_presorted_standard(input_folder=None, output_folder=None, dry_run_only=None, progress_callback=None):
    print("Program start. PRESORTED_STANDARD mode enabled.")

    effective_input_folder = os.path.abspath(input_folder if input_folder else INPUT_FOLDER)
    effective_output_folder = os.path.abspath(output_folder if output_folder else OUTPUT_FOLDER)
    effective_dry_run = DRY_RUN_ONLY if dry_run_only is None else dry_run_only

    if not os.path.isdir(effective_input_folder):
        print(f"Error: Input folder does not exist: {effective_input_folder}")
        sys.exit(1)

    if not os.path.exists(effective_output_folder):
        os.makedirs(effective_output_folder)
    _ensure_gitkeep(effective_output_folder)

    if len(_meaningful_directory_entries(effective_output_folder)) > 0 and not effective_dry_run and RESUME_ID == 0:
        print("Error: Output folder is not empty. Make sure old data is removed before use.")
        sys.exit(1)

    datasets = _discover_presorted_datasets(effective_input_folder)
    print(f"{len(datasets)} pre-sorted dataset folder(s) detected inside Input Folder.")
    if len(datasets) == 0:
        print(
            "No dataset folders were found inside Input Folder that contain pre-sorted "
            "RGB and thermal TIFF data."
        )
        sys.exit(1)

    for dataset in datasets:
        dataset_output_root = os.path.join(effective_output_folder, dataset["name"])
        print(f"Dataset: {dataset['name']} | burn sets detected: {len(dataset['burn_sets'])}")

        for burn_set_id, burn_set in enumerate(dataset["burn_sets"], start=1):
            burn_set_name = f"burn_set_{burn_set_id:03d}"
            if burn_set.get("layout") == "flat_mixed":
                rgb_records = burn_set["rgb_records"]
                thermal_jpg_records = burn_set["thermal_jpg_records"]
                thermal_tiff_records = burn_set["thermal_tiff_records"]
                cal_tiff_records = burn_set["cal_tiff_records"]
            else:
                rgb_records = _collect_media_records(burn_set["rgb_dir"])
                thermal_jpg_records = _collect_media_records(burn_set["thermal_jpg_dir"])
                thermal_tiff_records = _collect_media_records(burn_set["thermal_tiff_dir"])
                cal_tiff_records = _collect_media_records(burn_set["cal_tiff_dir"])

            pairing_result = _pair_presorted_records(
                rgb_records, thermal_jpg_records, thermal_tiff_records, cal_tiff_records
            )
            pairs = pairing_result["pairs"]
            camera_detection = detect_camera_from_rgb_records(rgb_records)
            active_profile = load_calibration_profile(
                camera_used=camera_detection["profile_camera"],
                dataset_name=dataset["name"],
                burn_set_name=burn_set_name,
            )
            camera_detection["profile_path"] = (
                active_profile.get("profile_path", "") if active_profile is not None else ""
            )
            selected_correction_model = (
                active_profile["selected_model"]
                if active_profile and _get_fov_correction_mode() == "CALIBRATION_PROFILE"
                else _get_fov_correction_mode().lower()
            )
            selected_correction_rmse = (
                active_profile.get("selected_model_summary", {}).get("rmse")
                if active_profile is not None and _get_fov_correction_mode() == "CALIBRATION_PROFILE"
                else None
            )
            print(
                f"  {burn_set_name}: source={burn_set['source_root']} | "
                f"rgb={len(rgb_records)} thermal_jpg={len(thermal_jpg_records)} "
                f"thermal_tiff={len(thermal_tiff_records)} cal_tiff={len(cal_tiff_records)} "
                f"paired={len(pairs)} high={pairing_result['confidence_counts']['HIGH']} "
                f"medium={pairing_result['confidence_counts']['MEDIUM']} "
                f"low={pairing_result['confidence_counts']['LOW']} "
                f"review={pairing_result['review_count']}"
            )
            print(
                "    Detected camera: "
                + camera_detection["camera"]
                + (
                    ""
                    if not camera_detection.get("dimension_summary")
                    else f" | image_dimensions={camera_detection['dimension_summary']}"
                )
            )
            print(
                "    Corrected FOV model: "
                + selected_correction_model
                + (
                    ""
                    if selected_correction_rmse is None
                    else f" | calibration_rmse={selected_correction_rmse:.4f}px"
                )
                + (
                    ""
                    if not camera_detection.get("profile_path")
                    else f" | calibration_profile_available={camera_detection['profile_path']}"
                )
            )

            if effective_dry_run:
                continue

            if len(dataset["burn_sets"]) == 1:
                burn_output_root = dataset_output_root
            else:
                burn_output_root = os.path.join(dataset_output_root, burn_set_name)

            images_root_dir = os.path.join(burn_output_root, "Images")
            rgb_corrected_output_dir = os.path.join(images_root_dir, "RGB", "Corrected FOV")
            rgb_raw_output_dir = os.path.join(images_root_dir, "RGB", "Raw")
            thermal_jpg_output_dir = os.path.join(images_root_dir, "Thermal", "JPG")
            thermal_tiff_output_dir = os.path.join(images_root_dir, "Thermal", "Celsius TIFF")

            os.makedirs(rgb_corrected_output_dir, exist_ok=True)
            os.makedirs(rgb_raw_output_dir, exist_ok=True)
            os.makedirs(thermal_jpg_output_dir, exist_ok=True)
            os.makedirs(thermal_tiff_output_dir, exist_ok=True)
            total_pairs = len(pairs)
            progress_step = max(1, total_pairs // 100) if total_pairs else 1

            if progress_callback:
                progress_callback(
                    {
                        "dataset": dataset["name"],
                        "burn_set": burn_set_name,
                        "current": 0,
                        "total": total_pairs,
                        "message": f"Starting {dataset['name']} / {burn_set_name}",
                    }
                )

            for pair_index, pair in enumerate(pairs, start=1):
                pair["dataset_name"] = dataset["name"]
                pair["burn_set_name"] = burn_set_name
                pair["detected_camera"] = camera_detection["camera"]
                pair["camera_detection_reason"] = camera_detection["reason"]
                pair["camera_image_size"] = camera_detection["image_size"]
                output_stem = f'{"0" * (OUTPUT_FILENAME_DIGITS - len(str(pair_index))) + str(pair_index)}'
                pair["output_stem"] = output_stem
                rgb_output_name = f"{output_stem}.JPG"
                thermal_jpg_output_name = f"{output_stem}.JPG"
                thermal_tiff_output_name = f"{output_stem}.TIFF"

                shutil.copy(pair["rgb"]["filepath"], os.path.join(rgb_raw_output_dir, rgb_output_name))

                corrected_rgb, correction_debug = generate_corrected_fov(
                    pair,
                    mode="AUTO_ALIGN",
                    dataset_name=dataset["name"],
                    burn_set_name=burn_set_name,
                    calibration_profile=active_profile,
                    camera_used=camera_detection["camera"],
                    return_debug_info=True,
                )
                pair["fov_correction_mode"] = correction_debug["fov_correction_mode"]
                pair["final_crop_box"] = correction_debug["final_crop_box"]
                pair["crop_shrink"] = correction_debug["crop_shrink"]
                pair["feature_alignment"] = correction_debug["feature_alignment"]
                pair["thermal_source_used"] = correction_debug["thermal_source_used"]
                pair["thermal_source_path"] = correction_debug["thermal_source_path"]
                pair["final_transform_matrix"] = correction_debug["final_transform_matrix"]
                pair["fallback_occurred"] = correction_debug["fallback_occurred"]
                if "exif" in corrected_rgb.info:
                    corrected_rgb.save(
                        os.path.join(rgb_corrected_output_dir, rgb_output_name),
                        exif=corrected_rgb.info["exif"],
                    )
                else:
                    corrected_rgb.save(os.path.join(rgb_corrected_output_dir, rgb_output_name))
                corrected_rgb.close()

                _copy_if_exists(
                    pair["thermal_jpg"]["filepath"] if pair["thermal_jpg"] is not None else None,
                    os.path.join(thermal_jpg_output_dir, thermal_jpg_output_name),
                )
                selected_tiff_source = (
                    pair["cal_tiff"]["filepath"]
                    if pair["cal_tiff"] is not None
                    else pair["thermal_tiff"]["filepath"]
                )
                shutil.copy(
                    selected_tiff_source,
                    os.path.join(thermal_tiff_output_dir, thermal_tiff_output_name),
                )

                if progress_callback and (
                    pair_index == total_pairs
                    or pair_index == 1
                    or pair_index % progress_step == 0
                ):
                    progress_callback(
                        {
                            "dataset": dataset["name"],
                            "burn_set": burn_set_name,
                            "current": pair_index,
                            "total": total_pairs,
                            "message": f"Processing {dataset['name']} / {burn_set_name}: {pair_index}/{total_pairs}",
                        }
                    )

            for decision in pairing_result["decisions"]:
                decision["detected_camera"] = camera_detection["camera"]
                decision["camera_dimension_summary"] = camera_detection.get("dimension_summary", "")
                decision["camera_detection_reason"] = camera_detection["reason"]
                decision["calibration_profile_path"] = camera_detection.get("profile_path", "")
                decision["fov_correction_mode"] = _get_fov_correction_mode()
            _write_pairing_logs(burn_output_root, pairing_result["decisions"])
            if EXPORT_ALIGNMENT_DEBUG_SAMPLES:
                export_alignment_debug_samples(
                    burn_output_root,
                    dataset["name"],
                    burn_set_name,
                    pairs,
                    calibration_profile=active_profile,
                )

    print("PRESORTED_STANDARD processing complete.")

def raw_file_sorting():
    if EXIF is None:
        print("The 'exif' package is required for DJI_RAW mode.")
        sys.exit(1)

    _load_dji_dependencies()

    # get the timestamp at the start of the program
    print('Program start. All listed times are in reference to program start. -- time = 0.000 seconds')
    t_start = time.time_ns()
    # Initialize DJI environment
    print(
        f'Initializing DJI environment -- time = {(time.time_ns()-t_start)/1e9:4.3f} seconds')
    DJI.dji_init()
    if DJI._libdirp == "":
        print('DJI environment failed to initialize.') 
        sys.exit(1)

    # Ensure that the output directory exists and is empty, if not, create the output directory
    print(f'Validating output filestructure -- time = {(time.time_ns()-t_start)/1e9:4.3f} seconds')
    if not os.path.exists(OUTPUT_FOLDER):
        os.makedirs(OUTPUT_FOLDER)
    _ensure_gitkeep(OUTPUT_FOLDER)
    # check to see that the output directory is empty
    if len(_meaningful_directory_entries(OUTPUT_FOLDER)) > 0 and RESUME_ID == 0:
        print(
            'Error: Output folder is not empty. Make sure old data is removed before use.')
        sys.exit(1)
    #If the output folder contains files and the resume ID is set to 0 or higher
    elif len(_meaningful_directory_entries(OUTPUT_FOLDER)) > 0 and RESUME_ID >= 0:
        print(f'WARNING: Output dir not empty and Resume ID set to {RESUME_ID}. Proceed with caution.')

    # Loop through input folder, then loop through subfolders
    print(f'{len(os.listdir(INPUT_FOLDER))} subfolders detected! Starting processing now. -- time = {(time.time_ns()-t_start)/1e9:4.3f} seconds')
    for id_subfolder, subfolder in enumerate(os.listdir(INPUT_FOLDER)):
        subfolder_path = f"{INPUT_FOLDER}{subfolder}/"
        print(f'For subfolder {subfolder} [{id_subfolder+1}/{len(os.listdir(INPUT_FOLDER))}], {len(os.listdir(subfolder_path))} files detected. Starting processing. -- time = {(time.time_ns()-t_start)/1e9:4.3f} seconds')
        camera_detection = detect_camera_from_folder(subfolder_path, fallback_camera=CAMERA_USED)
        local_camera_used = camera_detection["camera"]
        calibration_profile = load_calibration_profile(
            camera_used=local_camera_used,
            dataset_name=subfolder,
            burn_set_name="burn_set_001",
        )
        print(
            f'\tDetected camera: {local_camera_used}'
            + (f' | image_dimensions={camera_detection.get("dimension_summary", "")}' if camera_detection.get("dimension_summary") else '')
            + (f' | calibration_profile={calibration_profile.get("profile_path", "")}' if calibration_profile else '')
            + f' -- time = {(time.time_ns()-t_start)/1e9:4.3f} seconds'
        )

        # create filename and datetime lists
        rgb_image_filenames = []
        rgb_image_datetimes = []
        ir_image_filenames = []
        ir_image_datetimes = []
        rgb_video_filenames = []
        rgb_video_datetimes = []
        ir_video_filenames = []
        ir_video_datetimes = []

        # iterate over all files in the input subfolders
        for id_file, file in enumerate(os.listdir(subfolder_path)):
            # M30T Camera section
            if local_camera_used == "M30T":
                # check for .mp4 video file(s)
                if file.endswith('.MP4'):
                    # Distinguish between RGB (W) and Thermal (T) labeled videos
                    if 'T' in file:
                        # Add the Thermal (T) video filename and timestamp to the respective lists
                        ir_video_filenames.append(file)
                        ir_video_datetimes.append(datetime.datetime.fromtimestamp(
                            os.path.getmtime(f'{INPUT_FOLDER}{subfolder}/{file}')))
                    elif 'W' in file:
                        # Add the RGB (W) labeled video filename and timestamp to the respective lists
                        rgb_video_filenames.append(file)
                        rgb_video_datetimes.append(datetime.datetime.fromtimestamp(
                            os.path.getmtime(f'{INPUT_FOLDER}{subfolder}/{file}')))
                    # else: video is either screen or zoom, which are discarded for now
                # check for .jpg image files
                elif file.endswith('.JPG'):
                    # open image file in binary read mode and extract metadata using EXIF
                    with open(f'{INPUT_FOLDER}{subfolder}/{file}', 'rb') as src:
                        img = EXIF.Image(src)
                        # If image does not have EXIF metadata it is excluded
                        if not img.has_exif:
                            print(
                                f'Image {file} does not have exif data and will be excluded. NOTE: THIS CAN CAUSE DUPLICATE PAIRINGS')
                            continue
                    # Distinguish between RGB (W) and Thermal (T) labeled images
                    if 'T' in file:
                        # Add the Thermal (T) image filename and timestamp to the respective lists
                        ir_image_filenames.append(file)
                        ir_image_datetimes.append(datetime.datetime.strptime(
                            img.datetime, "%Y:%m:%d %H:%M:%S"))
                    elif 'W' in file:
                        # Add the RGB (W) image filename and timestamp to the respective lists
                        rgb_image_filenames.append(file)
                        rgb_image_datetimes.append(datetime.datetime.strptime(
                            img.datetime, "%Y:%m:%d %H:%M:%S"))
                    # delete the img object after getting filename and timestamp to save memory
                    # does not delete the original image file, just the img object in code
                    del img
                    # else: image is either screen or zoom, which are discarded for now.
                # else: file is not a video or image and will be excluded
            # M2EA Camera section
            elif local_camera_used == "M2EA":
                # check for .mp4 video file(s)
                if file.endswith('.MP4'):
                    # extract various video properties using get_video_properties()
                    vid_props = get_video_properties(
                        f'{INPUT_FOLDER}{subfolder}/{file}')

                    # separate thermal/rgb videos based on resolution
                    if vid_props['height'] == 512:
                        # Add the Thermal video filename and timestamp to the respective lists
                        ir_video_filenames.append(file)
                        ir_video_datetimes.append(datetime.datetime.fromtimestamp(
                            os.path.getmtime(f'{INPUT_FOLDER}{subfolder}/{file}')))
                    else: # Assumes that only rgb/ir videos exist in input folder
                        # Add the RGB video filename and timestamp to the respective lists
                        rgb_video_filenames.append(file)
                        rgb_video_datetimes.append(datetime.datetime.fromtimestamp(
                            os.path.getmtime(f'{INPUT_FOLDER}{subfolder}/{file}')))
                # check for .jpg image files
                elif file.endswith('.JPG'):
                    # try to open the image and extract metadata with EXIF, if it cannot be opened it is excluded
                    try:
                        with open(f'{INPUT_FOLDER}{subfolder}/{file}', 'rb') as src:
                            img = EXIF.Image(src)
                    except:
                        print(
                            f'Image {file} cannot be opened and will be excluded! This can cause duplicate/missing pairings!')
                        continue
                    # If image does not have EXIF metadata it is excluded
                    if not img.has_exif:
                        print(
                            f'Image {file} does not have exif data and will be excluded. NOTE: THIS CAN CAUSE DUPLICATE PAIRINGS')
                        continue


                   #check for image height equal to 512 pixels or not
                    if img.image_height != 512:
                        print('Thermal image height must be 512 pixels, exiting program.')
                        sys.exit(1)

                    # separate thermal/rgb images based on resolution
                    if img.image_height == 512:
                        # Add the Thermal image filename and timestamp to the respective lists
                        ir_image_filenames.append(file)
                        ir_image_datetimes.append(datetime.datetime.strptime(
                            img.datetime, "%Y:%m:%d %H:%M:%S"))
                    else:  # Assumes that only rgb/ir images exist in input folder
                        # Add the RGB image filename and timestamp to the respective lists
                        rgb_image_filenames.append(file)
                        rgb_image_datetimes.append(datetime.datetime.strptime(
                            img.datetime, "%Y:%m:%d %H:%M:%S"))
                    # delete the img object after getting filename and timestamp to save memory
                    # does not delete the original image file, just the img object in code
                    del img
                # else: file is not a video or image and will be excluded

        # print number images/videos that have been categorized as RGB / IR and the time it took to process
        print(f'\tAll {len(os.listdir(f"{INPUT_FOLDER}{subfolder}"))} files in subfolder [{id_subfolder+1}/{len(os.listdir(INPUT_FOLDER))}] have been categorized as rgb/ir. -- time = {(time.time_ns()-t_start)/1e9:4.3f} seconds')

        # Go through datetime/filename lists and pair rgb media to the corresponding ir media (timestamps)
        image_pairs = []
        video_pairs = []
        for id, rgb_datetime in enumerate(rgb_image_datetimes):
            image_pairs.append((rgb_image_filenames[id], ir_image_filenames[min(range(len(
                ir_image_datetimes)), key=lambda j: abs(ir_image_datetimes[j]-rgb_datetime))]))

        for id, rgb_datetime in enumerate(rgb_video_datetimes):
            video_pairs.append((rgb_video_filenames[id], ir_video_filenames[min(range(len(
                ir_video_datetimes)), key=lambda j: abs(ir_video_datetimes[j]-rgb_datetime))]))

        # print the number of paired images / videos and the time it took to process
        print(f'\tFiles have been paired. {len(image_pairs)} image pairs and {len(video_pairs)} video pairs created. -- time = {(time.time_ns()-t_start)/1e9:4.3f} seconds')

        # create output folder for videos and images
        os.makedirs(f'{OUTPUT_FOLDER}{subfolder}/Videos/Thermal', exist_ok=True)
        os.makedirs(f'{OUTPUT_FOLDER}{subfolder}/Videos/RGB', exist_ok=True)
        os.makedirs(f'{OUTPUT_FOLDER}{subfolder}/Images/Thermal/JPG', exist_ok=True)
        os.makedirs(f'{OUTPUT_FOLDER}{subfolder}/Images/Thermal/Celsius TIFF', exist_ok=True)
        os.makedirs(f'{OUTPUT_FOLDER}{subfolder}/Images/RGB/Corrected FOV', exist_ok=True)
        os.makedirs(f'{OUTPUT_FOLDER}{subfolder}/Images/RGB/Raw', exist_ok=True)

        # print the current state of the code, start copying videos to output folder
        print(f'\tOutput directories created. Now copying videos to output -- time = {(time.time_ns()-t_start)/1e9:4.3f} seconds')

        # Rename all ir media to rgb media filenames for pairing
        # copy videos to output folders
        for ix, (rgb_filename, ir_filename) in enumerate(video_pairs):
            rgb_filename_n = rgb_filename
            if RENAME_FILES:
                # create new filename and pad with 0's
                rgb_filename_n = f'{"0"*(OUTPUT_FILENAME_DIGITS-len(str(ix+1))) + str(ix+1)}.{rgb_filename.split(".")[1]}'
            # copy the RGB / IR video to the output folder with the new filename
            shutil.copy(f'{INPUT_FOLDER}{subfolder}/{rgb_filename}',
                        f'{OUTPUT_FOLDER}{subfolder}/Videos/RGB/{rgb_filename_n}')
            shutil.copy(f'{INPUT_FOLDER}{subfolder}/{ir_filename}',
                        f'{OUTPUT_FOLDER}{subfolder}/Videos/Thermal/{rgb_filename_n}')

        # print the number of video pairs that have been copied and the time it took to process
        print(f'\tAll {len(video_pairs)} video pairs have been coppied to output dir. -- time = {(time.time_ns()-t_start)/1e9:4.3f} seconds')
        print(f'\tNow beginning image pair processing')
        # continue processing images
        for pair_id, (rgb_filename, ir_filename) in enumerate(image_pairs):
            try:
                # checkpoint for first image processed (start)
                if pair_id == 0:
                    checkpoint_time = time.time_ns()
                    print(f'\t[0/{len(image_pairs)}] processed.')
                # print information about processing every 50 images
                if pair_id % 50 == 0 and not pair_id == 0:
                    print(f'\t[{pair_id}/{len(image_pairs)}] processed. Avg time per pair was {(time.time_ns()-checkpoint_time)/1e9/50:4.3f} s, Current Mem Usage: {psutil.Process(os.getpid()).memory_info().rss / 1024 ** 2 :.2f} MiB -- time = {(time.time_ns()-t_start)/1e9:4.3f} seconds')
                    checkpoint_time = time.time_ns()

                # resume processing from specified ID
                if pair_id + 1 <= RESUME_ID:
                    continue
                
                # reset new filename variable
                rgb_filename_n = rgb_filename
                if RENAME_FILES:
                    # set variable for new image filename
                    rgb_filename_n = f'{"0"*(OUTPUT_FILENAME_DIGITS-len(str(pair_id+1))) + str(pair_id+1)}.{rgb_filename.split(".")[1]}'

                # create log entry
                with open('log.txt', 'a+') as f:
                    f.write(f'pair {pair_id}: ({rgb_filename, ir_filename}) -> ({rgb_filename_n})\n')

                # extract thermal vals from ir images:
                temp_arr = rjpeg_to_heatmap(
                    f'{INPUT_FOLDER}{subfolder}/{ir_filename}', dtype='float32')
                # recreate thermal jpg from heatmap. This gets rid of any DJI superresolution or digital zoom. Also removes watermark and changes color mapping.
                fig = plt.figure(dpi=72, figsize=(
                    640/72, 512/72), frameon=False)
                fig.add_axes([0, 0, 1, 1])
                ax = sns.heatmap(temp_arr, cmap='inferno', cbar=False)  # NOTE: this appears to have a minor memory leak! ax.cla + gc.collect appears to help, though isnt perfect
                ax.set_xticks([])
                ax.set_yticks([])
                plt.savefig(
                    f'{OUTPUT_FOLDER}{subfolder}/Images/Thermal/JPG/{rgb_filename_n}', dpi=72)
                ax.cla()
                del ax
                plt.cla()
                plt.clf()
                plt.close('all')
                del fig

                # grab exif from original thermal image.
                original_ir_img = Image.open(
                    f'{INPUT_FOLDER}{subfolder}/{ir_filename}')

                # copy exif to newly created thermal jpg
                ir_img = Image.open(
                    f'{OUTPUT_FOLDER}{subfolder}/Images/Thermal/JPG/{rgb_filename_n}')
                ir_img.save(f'{OUTPUT_FOLDER}{subfolder}/Images/Thermal/JPG/{rgb_filename_n}',
                            exif=original_ir_img.info['exif'])
                ir_img.close()
                original_ir_img.close()
                # Save heatmap as TIFF
                tiff = Image.fromarray(temp_arr)
                tiff.save(
                    f'{OUTPUT_FOLDER}{subfolder}/Images/Thermal/Celsius TIFF/{rgb_filename_n.split(".")[0]}.TIFF')
                tiff.close()
                del temp_arr

                thermal_alignment_source = f'{OUTPUT_FOLDER}{subfolder}/Images/Thermal/Celsius TIFF/{rgb_filename_n.split(".")[0]}.TIFF'
                production_pair = {
                    "rgb": {
                        "filepath": f'{INPUT_FOLDER}{subfolder}/{rgb_filename}',
                        "filename": rgb_filename,
                    },
                    "cal_tiff": None,
                    "thermal_tiff": {
                        "filepath": thermal_alignment_source,
                        "filename": f'{rgb_filename_n.split(".")[0]}.TIFF',
                    },
                    "thermal_jpg": {
                        "filepath": f'{OUTPUT_FOLDER}{subfolder}/Images/Thermal/JPG/{rgb_filename_n}',
                        "filename": rgb_filename_n,
                    },
                    "dataset_name": subfolder,
                    "burn_set_name": "burn_set_001",
                    "detected_camera": local_camera_used,
                }
                corrected_rgb, correction_debug = generate_corrected_fov(
                    production_pair,
                    mode="AUTO_ALIGN",
                    dataset_name=subfolder,
                    burn_set_name="burn_set_001",
                    camera_used=local_camera_used,
                    calibration_profile=calibration_profile,
                    return_debug_info=True,
                )
                with open('log.txt', 'a+') as f:
                    f.write(
                        "corrected_fov "
                        f"mode={correction_debug['correction_mode_used']} "
                        f"thermal_source={correction_debug['thermal_source_used']} "
                        f"fallback={correction_debug['fallback_occurred']} "
                        f"transform={correction_debug['final_transform_matrix']}\n"
                    )

                # Copy cropped/aligned rgb image to output w/ original exif data when available
                corrected_rgb_output_path = f'{OUTPUT_FOLDER}{subfolder}/Images/RGB/Corrected FOV/{rgb_filename_n}'
                if "exif" in corrected_rgb.info:
                    corrected_rgb.save(
                        corrected_rgb_output_path,
                        exif=corrected_rgb.info["exif"],
                    )
                else:
                    corrected_rgb.save(corrected_rgb_output_path)
                corrected_rgb.close()

                # Now copy original rgb image to output
                shutil.copy(f'{INPUT_FOLDER}{subfolder}/{rgb_filename}',
                            f'{OUTPUT_FOLDER}{subfolder}/Images/RGB/Raw/{rgb_filename_n}')

                gc.collect()

            # exception if a file pair failed
            except Exception as e:
                import traceback
                print(f'FAILED at file pair sf={subfolder}, pid={pair_id}, rgbf={rgb_filename}, irf={ir_filename}')
                traceback.print_exc()
                exit(1)
        # print status when the processing is complete for a certain folder
        print(f'\tImage processing complete for folder [{id_subfolder +1}/{len(os.listdir(INPUT_FOLDER))}]. -- time = {(time.time_ns()-t_start)/1e9:4.3f} seconds')
    # print status when all processing is complete
    print(f'All processing complete. Program finished successfully. -- time = {(time.time_ns()-t_start)/1e9:4.3f} seconds')

#main function, run the raw_file_sorting() function
if __name__ == '__main__':
    configure_runtime()
    run_sort_pipeline(
        input_folder=INPUT_FOLDER,
        output_folder=OUTPUT_FOLDER,
        processing_mode=PROCESSING_MODE,
    )
