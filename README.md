# FlameVQA-Multi-Tool-Data-Pipeline

---

## Project Credits

FlameVQA Dataset Builder is part of a wildfire research effort at Clemson University within the IS-WiN Lab.

**Project Leadership**  
Mobin Habibpour, Niloufar Alipour Talemi

**Undergraduate Researchers**  
John Spodnik, Camren J. Khoury

**Project Oversight**  
Dr. Fatemeh Afghah

**Foundational Work**  
Bryce Hopkins, Michael Marinaccio (Flame-Data-Pipeline)

This repository documents **Camren J. Khoury's contributions**, focusing on improving dataset workflows, GUI tooling, usability, raw-file pairing, and RGB-thermal FOV alignment validation.

---

## Current Development

The primary code currently under active development is:

**Flame-Data-Pipeline-main -> Raw File Sorting Tool (GUI and pipeline)**

The active files are:

- `Flame-Data-Pipeline-main/Raw File Sorting/Raw File Sorting.py`
- `Flame-Data-Pipeline-main/Raw File Sorting/Raw File Sorting GUI.py`

Other tools in the pipeline remain available:

- `Flame-Data-Pipeline-main/Image GPS Tracing/Image GPS Tracing.py`
- `Flame-Data-Pipeline-main/Labeling/FLAME Image Labeling Tool.py`

### How to Run

From within the **Raw File Sorting** directory:

```
python "Raw File Sorting GUI.py"
```

The GUI reads from `Input Folder` and writes to `Output Folder` by default.

### What It Does

The GUI and pipeline perform automated preprocessing by:

- Reading files from the **Input Folder**
- Detecting whether the input is DJI raw-style data or pre-sorted standard image/TIFF data
- Pairing RGB images, thermal JPG images, thermal TIFF data, and calibrated thermal TIFF data when available
- Detecting camera type from RGB resolution and EXIF hints
- Producing FLAME-compatible output folders
- Preserving raw RGB files for traceability
- Producing `Corrected FOV` RGB outputs
- Writing pairing logs and review logs
- Providing visual validation tools for RGB-thermal alignment

Each dataset is processed and reorganized into a consistent format for downstream labeling and analysis.

### Output Structure

```
Output Folder/
+-- <Dataset_Name>/
    +-- Images/
    |   +-- RGB/
    |   |   +-- Corrected FOV/
    |   |   +-- Raw/
    |   +-- Thermal/
    |       +-- Celsius TIFF/
    |       +-- JPG/
    +-- pairing_log.csv
    +-- pairing_review.csv
```

If a dataset contains multiple burn sets, each burn set may be written under:

```
Output Folder/
+-- <Dataset_Name>/
    +-- burn_set_###/
        +-- Images/
```

---

## Overview

FlameVQA Dataset Builder is a **GUI-based system** for transforming raw wildfire imagery into structured multimodal datasets.

### Key Improvements

- Improved dataset organization and structure
- Metadata preservation and traceability
- Removal of strict DJI/RJPEG dependency for standard RGB/TIFF workflows
- Support for mixed, flat, and nested input folders
- Robust suffix-first pairing with timestamp and sequence consistency checks
- Pairing confidence scoring: `HIGH`, `MEDIUM`, and `LOW`
- Pairing logs: `pairing_log.csv` and `pairing_review.csv`
- Camera detection for M30T and M2EA-style RGB resolutions
- Safe crop-only FOV correction baseline
- Experimental and reviewable SIFT-based AUTO_ALIGN workflow
- Shared Corrected FOV generation path used by both GUI AUTO_ALIGN preview and production export
- Visual validation exports for comparing crop-only vs AUTO_ALIGN
- GUI viewer for side-by-side RGB/thermal overlay review
- Strict validation for saved calibration profiles

This extends the original Flame-Data-Pipeline into a **more unified dataset construction workflow**.

---

## Purpose

Wildfire datasets are often:

- Large-scale
- Multimodal (RGB + thermal)
- Inconsistently structured
- Captured by cameras with different RGB and thermal fields of view
- Difficult to label unless image pairs are correctly organized and aligned

This tool addresses those issues by:

- Centralizing preprocessing
- Reducing manual sorting steps
- Standardizing outputs
- Making RGB-thermal pairing traceable
- Separating safe production output from experimental alignment validation

**Goal:** Convert raw or semi-structured data into clean, research-ready datasets without requiring normal users to manually prepare folders or select modes.

---

## Foundation

Built on the original **Flame-Data-Pipeline**, which includes:

- Raw File Sorting Tool
- FLAME Image Labeling Tool
- Image GPS Tracing Tool

The original pipeline was designed around DJI radiometric JPG data and used a fixed camera crop for `Corrected FOV`. The current work expands this into a more automatic dataset-building workflow while preserving the original FLAME labeling output structure.

---

## Dependencies

### Recommended Python Version

Use **Python 3.11**.

Python 3.13 is not recommended for this repository because several pinned scientific packages, especially older `contourpy` / `matplotlib` dependencies, may not have compatible wheels and may try to build from source.

Install Python 3.11 on Windows:

```
winget install Python.Python.3.11
```

Check installation:

```
py -3.11 --version
```

### Virtual Environment

From inside:

```
Flame-Data-Pipeline-main/Raw File Sorting
```

run:

```
py -3.11 -m venv .venv
.\.venv\Scripts\activate
python -m pip install "pip<25"
```

### Install Requirements

Install Raw File Sorting and GPS dependencies:

```
python -m pip install -r ".\requirements.txt" -r "..\Image GPS Tracing\requirements.txt"
```

Install Labeling dependencies. The original labeling requirements pin `PySimpleGUI==5.0.2`, which may not be available from the normal package index. If that fails, use the available PySimpleGUI version below:

```
python -m pip install numpy==1.26.4 opencv-python==4.9.0.80 pillow==10.2.0 pyasn1==0.5.1 rsa==4.9 PySimpleGUI==4.60.5.1
```

### Core Libraries

- `numpy`
- `opencv-python`
- `pillow`
- `matplotlib`
- `pandas`
- `psutil`
- `exif`
- `get-video-properties`
- `PySimpleGUI` for the labeling tool

### Dependency Notes

- `opencv-python` is required for SIFT, affine estimation, homography estimation, and optional ECC refinement.
- `pillow` is used for image loading, RGB crops, overlays, EXIF preservation, and debug image exports.
- `exif` is required by DJI raw-style processing and GPS tracing.
- `matplotlib` is used for the legacy DJI thermal JPG `inferno` colormap. The thermal JPG render path no longer uses `seaborn` or `matplotlib.pyplot`.
- DJI thermal SDK DLLs remain in `Raw File Sorting/dji_thermal_sdk` for legacy DJI raw workflows.

---

## Usage (High-Level)

Typical workflow:

1. Put a dataset folder into `Raw File Sorting/Input Folder`
2. Run `python "Raw File Sorting GUI.py"`
3. Click `Run Sort`
4. Inspect results with `Check Results`
5. Use the output with the FLAME Image Labeling Tool

Normal users should not need to manually pre-sort files or select a processing mode. The pipeline attempts to detect the correct workflow from the input folder.

---

## Pairing Workflow

The current pre-sorted standard workflow supports datasets containing:

- RGB JPG files
- Thermal JPG files
- Thermal TIFF files
- Calibrated thermal TIFF files

Pairing is based on:

- Numeric suffix matching, such as `0001 -> 0001`
- Capture timestamps when available
- Expected modality presence
- Sequence consistency across neighboring pairs

Pairing outputs:

- `pairing_log.csv`: full pairing and confidence record
- `pairing_review.csv`: `MEDIUM`, `LOW`, or skipped/review-needed records

Pair confidence levels:

- `HIGH`: likely correct automatic pair
- `MEDIUM`: accepted but should be reviewed
- `LOW`: accepted only when no better candidate exists, should be reviewed

---

## FOV Correction and Alignment

### Current Production Default

The production default is:

```
FOV_CORRECTION_MODE = "AUTO_ALIGN"
```

`AUTO_ALIGN` means:

- Use the camera's fixed coarse RGB crop
- Resize that crop to the thermal output size, usually `640x512`
- Estimate a guarded SIFT/RANSAC transform against the selected thermal source
- Apply the accepted transform to the original color RGB crop
- Fall back to crop-only if AUTO_ALIGN fails validation

The saved `Images/RGB/Corrected FOV/<number>.JPG` is generated through the same `generate_corrected_fov(..., mode="AUTO_ALIGN")` path used by the GUI AUTO_ALIGN preview. When thermal opacity is set to 0%, the RGB shown in the AUTO_ALIGN overlay is the same Corrected FOV image source used for production export, aside from JPG compression.

### Why Crop-Only Is Not the Final Goal

Crop-only is not true geometric alignment. It does not fully solve:

- RGB/thermal lens differences
- Different sensor fields of view
- Scale mismatch
- Slight rotation or shear
- Parallax between RGB and thermal sensors
- Misalignment that changes across the image

The long-term goal is better `Corrected FOV` alignment than fixed crop alone, while ensuring the output is never worse than crop-only by default.

### Alignment Modes

Available FOV correction modes in `Raw File Sorting.py`:

- `CROP_ONLY`: safe production baseline
- `CALIBRATION_PROFILE`: applies a saved calibration profile if valid
- `EXPERIMENTAL_SIFT`: developer feature-alignment mode
- `AUTO_ALIGN`: improved SIFT-based candidate alignment mode
- `AUTO_SIFT_CALIBRATED`: AUTO_ALIGN-style mode that can use validated calibration fallback

The GUI preview and production export now share one Corrected FOV generation function. Thermal source selection follows this priority: calibrated TIFF, thermal TIFF, then thermal JPG.

### AUTO_ALIGN Pipeline

AUTO_ALIGN does the following:

1. Load RGB and thermal pair
2. Apply camera coarse crop
3. Optionally tighten the crop before feature matching
4. Create temporary grayscale/CLAHE/edge representations
5. Run SIFT on temporary representations only
6. Match features with Lowe ratio filtering
7. Spatially balance matches across a grid
8. Test multiple transform models
9. Validate the selected transform
10. Apply the final transform to the original color RGB crop
11. Fall back to crop-only if validation fails

The final saved RGB output is never grayscale. Grayscale/edge images are temporary working images only.

AUTO_ALIGN is slower than crop-only because each exported pair runs feature extraction, feature matching, RANSAC validation, and image warping. Crop-only only crops and resizes.

### Crop Tightening

AUTO_ALIGN uses tunable crop shrink parameters to avoid matching RGB content outside the thermal field of view:

```
CROP_SHRINK_LEFT = 0.06
CROP_SHRINK_RIGHT = 0.02
CROP_SHRINK_TOP = 0.00
CROP_SHRINK_BOTTOM = 0.00
```

This was added because extra scene content, such as road visible in RGB but not thermal, can mislead feature matching.

### Transform Models

AUTO_ALIGN compares candidates from:

- Similarity / partial affine transform
- Full affine transform
- Homography, optional and disabled by default

Homography is intentionally not trusted by default because it can overfit feature matches and produce visually bad warps.

### Preprocessing Variants

AUTO_ALIGN tests multiple temporary structural representations:

- `clahe`
- `edge_blend`
- `sobel`
- `canny`
- `thermal_inverted_clahe`

These are used only for feature detection and matching.

### Validation Metrics

Each AUTO_ALIGN candidate is evaluated with:

- Good match count
- RANSAC inlier count
- Inlier ratio
- Match grid cell coverage
- Inlier grid cell coverage
- Mean reprojection error / RMSE
- Max reprojection error
- `scale_x`
- `scale_y`
- Scale ratio
- Rotation
- Skew / shear
- Translation
- Determinant
- Confidence level

Transforms are rejected if they have:

- Too few good matches
- Too few RANSAC inliers
- Poor inlier ratio
- Inliers clustered near the center
- High reprojection error
- Unrealistic scale
- Unrealistic translation
- Excessive skew
- Orientation flip

Important: high numerical confidence does not automatically mean visual correctness. AUTO_ALIGN results remain marked as needing visual review.

---

## Visual Validation

AUTO_ALIGN debug validation exports are available through:

```
export_alignment_debug_samples(...)
```

By default, validation exports sample:

```
CORRECTION_VALIDATION_SAMPLE_COUNT = 20
```

### Exported Debug Files

For each sampled pair, the tool exports:

- Crop-only `Corrected FOV`
- Best AUTO_ALIGN RGB result
- Thermal preview
- Crop-only vs thermal overlay
- AUTO_ALIGN vs thermal overlay
- Per-candidate warped RGB images
- Combined comparison image

### Exported CSV Files

Validation exports include:

- `correction_validation_summary.csv`
- `alignment_candidate_metrics.csv`

The summary includes:

- Chosen model
- Preprocessing mode
- Scale values
- Translation values
- Skew
- Rotation
- Inlier count
- Inlier ratio
- Inlier grid cells
- RMSE / reprojection error
- Confidence level
- Fallback reason
- `visual_review_status`
- `auto_align_questionable_reasons`

The default visual review flag is:

```
visual_review_status = visually_better_unknown
```

AUTO_ALIGN is now the production Corrected FOV path. If AUTO_ALIGN fails validation, the pipeline falls back to crop-only and records the fallback in the pairing log.

### GUI Review

The output viewer now supports side-by-side visual comparison:

- Crop-only Corrected FOV
- Thermal image
- Crop-only vs thermal overlay
- AUTO_ALIGN vs thermal overlay

It also includes:

- Overlay opacity slider
- AUTO_ALIGN metrics for the selected pair
- Confidence, transform, scale, translation, skew, rotation, inlier, grid-cell, RMSE, fallback, and questionable-reason display

This is for review and for validating the same AUTO_ALIGN RGB image source used by production export.

---

## Calibration Profiles

Saved calibration profiles are now validated before use.

Invalid profiles are ignored when loaded. Profiles are considered invalid if they contain unrealistic transform values, such as:

- Extreme `scale_x` or `scale_y`
- Large translation relative to output size
- Excessive skew
- Orientation flip
- Missing matrix
- Missing or high RMSE

The existing `payson_test` profile was identified as invalid because it contained an extreme `scale_y = 5.0`, which visibly distorted the output. The loader now ignores profiles with this kind of transform.

New profiles are also validated before saving. Invalid profiles raise an error instead of silently becoming part of the pipeline.

---

## Definitions

**RGB Raw**
The original RGB image copied into the output for traceability.

**Thermal JPG**
A displayable thermal image used for visual comparison.

**Thermal Celsius TIFF**
Thermal TIFF data, often used for temperature-aware labeling or analysis.

**Calibrated Thermal TIFF**
Thermal TIFF already calibrated by an upstream source. Used preferentially when available.

**Corrected FOV**
The RGB image cropped and/or transformed to better correspond to the thermal field of view.

**CROP_ONLY**
Safe baseline FOV correction. Uses only fixed camera crop and resize.

**AUTO_ALIGN**
Production guarded alignment mode. Tests SIFT-based transform candidates and falls back if validation fails.

**SIFT**
Scale-Invariant Feature Transform. Used here only on temporary grayscale/edge images to estimate RGB-to-thermal alignment.

**RANSAC**
Robust model fitting used to reject bad feature matches.

**Similarity Transform**
Translation, rotation, and uniform scale. Less flexible and less likely to overfit.

**Affine Transform**
Translation, rotation, nonuniform scale, and shear. More flexible than similarity.

**Homography**
Perspective transform. Powerful but risky for this problem because it can overfit.

**Inlier**
A feature match that agrees with the estimated transform after RANSAC.

**Inlier Ratio**
The fraction of matched features accepted as inliers.

**Inlier Grid Cells**
How many spatial grid cells contain inlier matches. Used to detect center-biased matching.

**RMSE / Reprojection Error**
Pixel error between transformed RGB feature points and matching thermal feature points.

**visually_better_unknown**
Default validation status meaning AUTO_ALIGN has not been visually confirmed as better than crop-only.

---

## Known Issues

- The previously documented `seaborn` heatmap memory leak in legacy DJI thermal JPG rendering may be fixed. That path now renders thermal JPGs directly with NumPy, the matplotlib `inferno` colormap, and PIL instead of `sns.heatmap(...)` / `matplotlib.pyplot` figures.
- Large batches should still be monitored for memory use because AUTO_ALIGN and DJI thermal extraction create temporary image arrays per pair.
- AUTO_ALIGN can produce numerically strong candidates that still need visual review
- Center landmarks may align while edges remain scaled or offset
- Crop shrink settings may need camera-specific tuning
- Homography is disabled by default because it can overfit
- `PySimpleGUI==5.0.2` may not be available from the normal package index; use `PySimpleGUI==4.60.5.1` if needed

---

## Scope

This repository focuses on:

- Dataset preparation tooling
- File sorting and pairing
- RGB-thermal FOV correction experiments
- Visual validation of alignment
- Workflow improvements for FlameVQA / FireSense dataset construction

It does **not include** internal research methods or restricted project details.

---

## Acknowledgment

Developed at Clemson University - IS-WiN Lab.

**Contributors**

- Mobin Habibpour
- Niloufar Alipour Talemi
- John Spodnik
- Camren J. Khoury
- Dr. Fatemeh Afghah
- Bryce Hopkins
- Michael Marinaccio
