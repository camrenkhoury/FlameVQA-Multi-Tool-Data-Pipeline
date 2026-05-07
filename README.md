# FlameVQA-Multi-Tool-Data-Pipeline

FlameVQA Dataset Builder is a GUI-based wildfire dataset pipeline for converting raw or semi-structured RGB/thermal data into FLAME-compatible dataset folders.

The current workflow is centered on the **FLAME Full Pipeline GUI**. Raw sorting still runs first, then optional temperature-based labeling, GPS tracing, and manual label review run from the same interface.

**Tool Author and Primary Developer**  
Camren J. Khoury

This repository documents **Camren J. Khoury's Full Pipeline GUI and dataset-pipeline work**, focusing on GUI integration, usability, raw-file pairing, RGB-thermal FOV correction, temperature-based labeling, GPS workflow integration, and full-pipeline automation.

---

## Project Credits

FlameVQA Dataset Builder is part of a wildfire research effort at Clemson University within the IS-WiN Lab.

**Project Leadership**  
Mobin Habibpour, Niloufar Alipour Talemi

**Undergraduate Researchers**  
Camren J. Khoury

**Project Oversight**  
Dr. Fatemeh Afghah

**Foundational Work**  
Bryce Hopkins, Michael Marinaccio (Flame-Data-Pipeline)

---

## Active Tools

The main entry point is:

- `Full Pipeline GUI.cmd`

The active implementation files are:

- `Flame-Data-Pipeline-main/Raw File Sorting/Full Pipeline GUI.py`
- `Flame-Data-Pipeline-main/Raw File Sorting/Full Pipeline GUI.cmd`
- `Flame-Data-Pipeline-main/Raw File Sorting/Raw File Sorting GUI.py`
- `Flame-Data-Pipeline-main/Raw File Sorting/Raw File Sorting.py`

The supporting tools remain available and are integrated into the GUI workflow:

- `Flame-Data-Pipeline-main/Image GPS Tracing/Image GPS Tracing.py`
- `Flame-Data-Pipeline-main/Labeling/FLAME Image Labeling Tool.py`

---

## Quick Start

Double-click the launcher at the repository root:

```text
Full Pipeline GUI.cmd
```

The launcher:

1. Enters the Raw File Sorting tool folder.
2. Creates `.venv` with Python 3.11 if needed.
3. Activates the virtual environment.
4. Installs the known working dependencies on first run.
5. Starts the **FLAME Full Pipeline GUI**.

You can also run directly from:

```text
Flame-Data-Pipeline-main/Raw File Sorting/Full Pipeline GUI.cmd
```

Or from an already activated environment:

```powershell
python "Full Pipeline GUI.py"
```

---

## Full Pipeline Workflow

Typical user workflow:

1. Put a dataset folder into `Flame-Data-Pipeline-main/Raw File Sorting/Input Folder`.
2. Open `Full Pipeline GUI.cmd`.
3. Confirm the Input Folder and Output Folder.
4. Choose pipeline automation options.
5. Click `Run Full Pipeline`.
6. If temperature labeling is enabled, enter the Fire temperature threshold in Celsius.
7. Let the pipeline complete the selected stages.
8. Review the final dataset folders in `Output Folder`.

The normal user does not need to manually pre-sort files or choose a processing mode. The GUI auto-detects whether the input looks like DJI raw-style data or standard pre-sorted RGB/thermal data.

---

## Pipeline Stages

The GUI displays separate progress meters for each stage.

### 1. Raw Sorting / Export

This stage reads the input dataset, detects file types, pairs RGB and thermal data, detects camera type, generates Corrected FOV RGB images, and writes the base FLAME-style `Images` folder.

Supported input data includes:

- RGB JPG images
- Thermal JPG images
- Thermal TIFF images
- Calibrated thermal TIFF images when available
- DJI-style raw thermal workflows when applicable

Pairing uses:

- Numeric suffix matching, such as `0001` to `0001`
- Capture timestamps when available
- Modality presence
- Sequence consistency across nearby files

### 2. GPS Traces

If `Generate GPS traces from RGB/Raw` is enabled, the GUI runs the GPS tracing tool after sorting.

The GPS trace source is:

```text
Images/RGB/Raw/
```

The GPS output is:

```text
GPS_Traces.csv
```

This CSV is the expected output of the Image GPS Tracing Tool. If GPS traces are not needed for a dataset generation run, leave the GPS checkbox unchecked.

### 3. Temperature Labeling

If `Temperature label Fire/No Fire` is enabled, the GUI asks for a Celsius threshold before processing starts.

The labeling rule is:

```text
max thermal TIFF temperature >= threshold -> Fire
max thermal TIFF temperature < threshold  -> No Fire
```

The suggested threshold is `150 C`, matching the original labeling tool's temperature-threshold workflow.

Temperature labeling happens after raw sorting because it uses the sorted thermal TIFF files. The output is written directly into the completed dataset structure under each `Images` folder:

```text
Images/
+-- Fire/
|   +-- RGB/
|   |   +-- Corrected FOV/
|   |   +-- Raw/
|   +-- Thermal/
|       +-- Celsius TIFF/
|       +-- JPG/
+-- No Fire/
    +-- RGB/
    |   +-- Corrected FOV/
    |   +-- Raw/
    +-- Thermal/
        +-- Celsius TIFF/
        +-- JPG/
```

Example completed paths:

```text
Shoetank/Images/Fire/RGB/Raw/
Shoetank/Images/No Fire/RGB/Raw/
```

### 4. Manual Label Review

If `Open manual labeler after auto labels` is enabled, the FLAME Image Labeling Tool opens after automatic temperature labeling.

Manual review is optional. It is useful when a dataset needs human inspection after the automated Fire/No Fire split.

The manual labeler still supports:

- Arrow-key navigation
- Number-key labeling
- Fire / No Fire / Unlabeled labels
- Temperature-threshold labeling inside the manual tool
- Exporting reviewed labels

---

## Output Structure

For a single dataset, the base sorted output is:

```text
Output Folder/
+-- <Dataset_Name>/
    +-- Images/
        +-- RGB/
        |   +-- Corrected FOV/
        |   +-- Raw/
        +-- Thermal/
            +-- Celsius TIFF/
            +-- JPG/
```

When temperature labeling is enabled, the completed labeled output is:

```text
Output Folder/
+-- <Dataset_Name>/
    +-- Images/
        +-- Fire/
        |   +-- RGB/
        |   |   +-- Corrected FOV/
        |   |   +-- Raw/
        |   +-- Thermal/
        |       +-- Celsius TIFF/
        |       +-- JPG/
        +-- No Fire/
        |   +-- RGB/
        |   |   +-- Corrected FOV/
        |   |   +-- Raw/
        |   +-- Thermal/
        |       +-- Celsius TIFF/
        |       +-- JPG/
        +-- RGB/
        |   +-- Corrected FOV/
        |   +-- Raw/
        +-- Thermal/
            +-- Celsius TIFF/
            +-- JPG/
```

If a dataset contains multiple burn sets, each burn set may be written under:

```text
Output Folder/
+-- <Dataset_Name>/
    +-- burn_set_###/
        +-- Images/
```

If GPS tracing is enabled, `GPS_Traces.csv` is written at the dataset or burn-set root.

---

## Corrected FOV and RGB-Thermal Alignment

The production default is:

```text
FOV_CORRECTION_MODE = "AUTO_ALIGN"
```

`Corrected FOV` means the RGB image has been cropped and/or transformed so it better corresponds to the thermal field of view.

The saved production RGB output is:

```text
Images/RGB/Corrected FOV/<image>.JPG
```

The final saved image is always color RGB. Temporary grayscale, CLAHE, edge, and feature images are used only internally to estimate alignment.

### Thermal Source Priority

For alignment, the pipeline automatically uses the best available thermal source per pair:

1. Calibrated thermal TIFF
2. Thermal TIFF
3. Thermal JPG

If a pair does not have all thermal formats, the pipeline still processes it with the best available source.

### AUTO_ALIGN Summary

`AUTO_ALIGN` performs:

1. Camera-aware coarse RGB crop.
2. Temporary grayscale/contrast/edge preprocessing for alignment only.
3. SIFT feature matching with RANSAC.
4. Guarded transform validation.
5. Color RGB warp/crop into thermal-size output.
6. Safe fallback when a transform is not reliable.

The output size is normally:

```text
640 x 512
```

AUTO_ALIGN is slower than crop-only because it performs feature extraction, matching, transform validation, and image warping.

### Current Crop Tightening Values

AUTO_ALIGN uses crop tightening to avoid matching RGB content that is outside the thermal FOV:

```text
CROP_SHRINK_LEFT = 0.06
CROP_SHRINK_RIGHT = 0.02
CROP_SHRINK_TOP = 0.00
CROP_SHRINK_BOTTOM = 0.00
```

### Parallel Corrected FOV Export

Corrected FOV generation can run in parallel with a bounded worker pool:

```text
PARALLEL_CORRECTED_FOV_EXPORT = True
PARALLEL_CORRECTED_FOV_WORKERS = "AUTO"
PARALLEL_CORRECTED_FOV_MAX_WORKERS = 4
PARALLEL_CORRECTED_FOV_MIN_FREE_RAM_GB = 6.0
PARALLEL_CORRECTED_FOV_ESTIMATED_RAM_PER_WORKER_GB = 2.0
```

The automatic worker count reserves memory first, then limits by CPU.

---

## GUI Review Tools

The Full Pipeline GUI includes review tools for inspecting output pairs.

The image review window can show:

- Corrected FOV RGB
- Thermal image
- Crop-only comparison
- AUTO_ALIGN comparison
- RGB/thermal overlay with adjustable opacity
- Alignment metrics for the selected pair

Developer calibration and validation tools remain available inside the GUI for alignment development and calibration work. Normal production dataset generation does not require those tools.

---

## Dependencies

### Recommended Python Version

Use **Python 3.11**.

Python 3.13 is not recommended because several pinned scientific packages may not have compatible wheels and may try to build from source.

Install Python 3.11 on Windows:

```powershell
winget install Python.Python.3.11
```

Check installation:

```powershell
py -3.11 --version
```

### Launcher Installation

The recommended launcher handles the environment automatically:

```text
Full Pipeline GUI.cmd
```

### Manual Environment Setup

From:

```text
Flame-Data-Pipeline-main/Raw File Sorting
```

run:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\activate
python -m pip install "pip<25"
python -m pip install -r ".\requirements.txt" -r "..\Image GPS Tracing\requirements.txt"
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
- `PySimpleGUI`

### Dependency Notes

- `opencv-python` is required for SIFT, affine estimation, optional homography experimentation, and image warping.
- `pillow` is used for image loading, EXIF preservation, RGB crops, overlays, TIFF reading, and output writing.
- `exif` is required by DJI raw-style processing and GPS tracing.
- `matplotlib` is used for legacy DJI thermal JPG rendering.
- DJI thermal SDK DLLs remain in `Raw File Sorting/dji_thermal_sdk` for legacy DJI raw workflows.

---

## Definitions

**Full Pipeline GUI**  
The main GUI that runs sorting, Corrected FOV generation, optional GPS tracing, optional temperature labeling, and optional manual review.

**RGB Raw**  
The original RGB image copied into the output for traceability.

**Corrected FOV**  
The RGB image cropped and/or transformed to better match the thermal field of view.

**Thermal JPG**  
A displayable thermal image used for visual comparison and labeling context.

**Thermal Celsius TIFF**  
Thermal TIFF data used for temperature-based labeling and analysis.

**Calibrated Thermal TIFF**  
Thermal TIFF already calibrated by an upstream process. Used preferentially when available.

**Temperature Labeling**  
Automatic Fire / No Fire splitting based on the maximum value in the thermal TIFF.

**AUTO_ALIGN**  
Production RGB-to-thermal alignment mode. It estimates guarded SIFT/RANSAC alignment candidates and falls back safely when confidence is low.

**SIFT**  
Scale-Invariant Feature Transform. Used internally on temporary grayscale/edge images to estimate alignment.

**RANSAC**  
Robust model fitting used to reject bad feature matches.

**Affine Transform**  
Transform model that can represent translation, rotation, scale, and shear.

**Homography**  
Perspective transform used for developer calibration experiments when affine alignment is not sufficient.

**GPS_Traces.csv**  
Optional GPS tracing output containing image datetime, latitude, longitude, altitude, filename, and path.

---

## Known Notes

- Large batches should still be monitored for memory use because AUTO_ALIGN and thermal extraction create temporary image arrays per pair.
- AUTO_ALIGN can be slower on large datasets than crop-only processing.
- Smoke, low texture, repeated branches, and weak thermal structure can make per-image alignment harder.
- Crop shrink settings may need camera-specific tuning.
- `PySimpleGUI==5.0.2` may not be available from the normal package index; `PySimpleGUI==4.60.5.1` is the current fallback used by the launcher.

---

## Scope

This repository focuses on:

- Dataset preparation tooling
- File sorting and pairing
- RGB-thermal FOV correction
- Temperature-based Fire / No Fire labeling
- Optional GPS trace extraction
- Workflow improvements for FlameVQA / FireSense dataset construction

It does **not include** internal research methods or restricted project details.

---

## Acknowledgment

Developed at Clemson University - IS-WiN Lab.

**Contributors**

- Camren J. Khoury
- Mobin Habibpour
- Niloufar Alipour Talemi
- Dr. Fatemeh Afghah
- Bryce Hopkins
- Michael Marinaccio
