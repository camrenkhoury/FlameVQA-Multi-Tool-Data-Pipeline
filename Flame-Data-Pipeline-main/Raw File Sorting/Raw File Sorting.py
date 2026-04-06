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

# specify the input and output folder filenames
INPUT_FOLDER = "./Input Folder/"
OUTPUT_FOLDER = "./Output Folder/"
# Current valid options:
# - "DJI_RAW": original workflow for M30T/M2EA RJPG inputs
# - "PRESORTED_STANDARD": existing RGB JPG + thermal JPG/TIFF/Cal TIFF folders
PROCESSING_MODE = "DJI_RAW"
# Current valid options: "M2EA", "M30T"
CAMERA_USED = 'M30T'
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
PRESORTED_METADATA_FILENAME = "pairs.csv"
PAIR_TIME_TOLERANCE_SECONDS = 3.0
DRY_RUN_ONLY = False
ALLOW_INDEX_FALLBACK_WHEN_TIMESTAMP_FAILS = True


def _prompt_yes_no(prompt_text, default=False):
    suffix = " [Y/n]: " if default else " [y/N]: "
    response = input(prompt_text + suffix).strip().lower()
    if response == "":
        return default
    return response in {"y", "yes"}


def configure_runtime():
    global INPUT_FOLDER
    global OUTPUT_FOLDER
    global PROCESSING_MODE
    global DRY_RUN_ONLY

    script_dir = os.path.dirname(os.path.abspath(__file__))
    default_input = os.path.abspath(os.path.join(script_dir, INPUT_FOLDER))
    default_output = os.path.abspath(os.path.join(script_dir, OUTPUT_FOLDER))

    print("Runtime configuration")
    print(f"Script directory: {script_dir}")
    print("Select processing mode:")
    print("  1. DJI_RAW")
    print("  2. PRESORTED_STANDARD")

    mode_choice = input("Enter 1 or 2 [default: 1]: ").strip()
    if mode_choice == "2":
        PROCESSING_MODE = "PRESORTED_STANDARD"
    else:
        PROCESSING_MODE = "DJI_RAW"

    INPUT_FOLDER = default_input
    OUTPUT_FOLDER = default_output

    if PROCESSING_MODE == "PRESORTED_STANDARD":
        DRY_RUN_ONLY = _prompt_yes_no("Run as dry-run only?", default=True)
    else:
        DRY_RUN_ONLY = False

    print(f"Selected mode: {PROCESSING_MODE}")
    print(f"Input folder: {INPUT_FOLDER}")
    print(f"Output folder: {OUTPUT_FOLDER}")
    if PROCESSING_MODE == "PRESORTED_STANDARD":
        print(f"Dry run only: {DRY_RUN_ONLY}")

# import required dependencies
import os
import sys
from PIL import Image
import datetime
import shutil
import time
import gc
import csv
import json

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
    digits = ""
    for char in reversed(stem):
        if char.isdigit():
            digits = char + digits
        else:
            break

    return int(digits) if digits else None


def _copy_if_exists(src, dst):
    if src and os.path.exists(src):
        shutil.copy(src, dst)


def _apply_rgb_fov_correction(rgb_source_path):
    rgb_img = Image.open(rgb_source_path)

    if CAMERA_USED == "M30T":
        rgb_img = rgb_img.crop(
            (640 + 40 - 60, 412 + 30 + 12, 4000 - 640 - 40 - 40 - 40 - 16 - 16 + 40, 3000 - 412 - 30 - 30 - 30 - 12)
        )
        rgb_img = rgb_img.resize((640, 512))
    elif CAMERA_USED == "M2EA":
        rgb_img = rgb_img.crop((1280 + 80, 824, 8000 - 1280 + 80, 6000 - 824))
        rgb_img = rgb_img.resize((640, 512))

    return rgb_img


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

        record = {
            "filename": file,
            "filepath": filepath,
            "datetime": _extract_capture_datetime(filepath),
            "index": _numeric_suffix(file),
        }

        name_upper = file.upper()
        if name_upper.startswith("MAX_") and "_W" in name_upper and ext in {".jpg", ".jpeg"}:
            rgb_records.append(record)
        elif name_upper.startswith("IRX_") and "CAL" in name_upper and ext in {".tif", ".tiff"}:
            cal_tiff_records.append(record)
        elif name_upper.startswith("IRX_") and "_T" in name_upper and ext in {".tif", ".tiff"}:
            thermal_tiff_records.append(record)
        elif name_upper.startswith("IRX_") and "_T" in name_upper and ext in {".jpg", ".jpeg"}:
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
        flat_dataset = _collect_flat_dataset_records(dataset_root)
        if flat_dataset is not None:
            burn_sets = [flat_dataset]
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
            }
        )

    return records


def _match_record(target_record, candidate_records, used_candidates):
    if not candidate_records:
        return None, "missing"

    # Prefer nearest timestamp within tolerance.
    available_candidates = [
        candidate for candidate in candidate_records if candidate["filepath"] not in used_candidates
    ]
    if not available_candidates:
        return None, "missing"

    best_candidate = min(
        available_candidates,
        key=lambda candidate: abs((candidate["datetime"] - target_record["datetime"]).total_seconds()),
    )
    time_delta = abs((best_candidate["datetime"] - target_record["datetime"]).total_seconds())
    if time_delta <= PAIR_TIME_TOLERANCE_SECONDS:
        return best_candidate, "timestamp"

    # Only fall back to index matching if timestamp matching fails.
    if ALLOW_INDEX_FALLBACK_WHEN_TIMESTAMP_FAILS and target_record["index"] is not None:
        exact_matches = [
            candidate
            for candidate in available_candidates
            if candidate["index"] == target_record["index"]
        ]
        if exact_matches:
            return exact_matches[0], f"index_fallback_after_time_delta:{time_delta:0.3f}"

    return None, f"time_delta_exceeded:{time_delta:0.3f}"


def _pair_presorted_records(rgb_records, thermal_jpg_records, thermal_tiff_records, cal_tiff_records):
    pairs = []
    used_thermal_jpg = set()
    used_thermal_tiff = set()
    used_cal_tiff = set()

    for rgb_record in rgb_records:
        thermal_tiff_record, tiff_match_type = _match_record(
            rgb_record, thermal_tiff_records, used_thermal_tiff
        )
        if thermal_tiff_record is None:
            continue

        thermal_jpg_record, jpg_match_type = _match_record(
            rgb_record, thermal_jpg_records, used_thermal_jpg
        )
        cal_tiff_record, cal_match_type = _match_record(
            rgb_record, cal_tiff_records, used_cal_tiff
        )

        used_thermal_tiff.add(thermal_tiff_record["filepath"])
        if thermal_jpg_record is not None:
            used_thermal_jpg.add(thermal_jpg_record["filepath"])
        if cal_tiff_record is not None:
            used_cal_tiff.add(cal_tiff_record["filepath"])

        pairs.append(
            {
                "rgb": rgb_record,
                "thermal_jpg": thermal_jpg_record,
                "thermal_tiff": thermal_tiff_record,
                "cal_tiff": cal_tiff_record,
                "match_types": {
                    "thermal_jpg": jpg_match_type,
                    "thermal_tiff": tiff_match_type,
                    "cal_tiff": cal_match_type,
                },
            }
        )

    return pairs


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

            pairs = _pair_presorted_records(
                rgb_records, thermal_jpg_records, thermal_tiff_records, cal_tiff_records
            )

            dataset_entry["burn_sets"].append(
                {
                    "name": f"burn_set_{burn_set_id:03d}",
                    "source_root": burn_set["source_root"],
                    "layout": burn_set.get("layout", "nested"),
                    "rgb_count": len(rgb_records),
                    "thermal_jpg_count": len(thermal_jpg_records),
                    "thermal_tiff_count": len(thermal_tiff_records),
                    "cal_tiff_count": len(cal_tiff_records),
                    "pair_count": len(pairs),
                    "pairs": pairs,
                }
            )

        analysis.append(dataset_entry)

    return analysis


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

    if len(os.listdir(effective_output_folder)) > 0 and not effective_dry_run and RESUME_ID == 0:
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

            pairs = _pair_presorted_records(
                rgb_records, thermal_jpg_records, thermal_tiff_records, cal_tiff_records
            )

            burn_set_name = f"burn_set_{burn_set_id:03d}"
            print(
                f"  {burn_set_name}: source={burn_set['source_root']} | "
                f"rgb={len(rgb_records)} thermal_jpg={len(thermal_jpg_records)} "
                f"thermal_tiff={len(thermal_tiff_records)} cal_tiff={len(cal_tiff_records)} "
                f"paired={len(pairs)}"
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
                output_stem = f'{"0" * (OUTPUT_FILENAME_DIGITS - len(str(pair_index))) + str(pair_index)}'
                rgb_output_name = f"{output_stem}.JPG"
                thermal_jpg_output_name = f"{output_stem}.JPG"
                thermal_tiff_output_name = f"{output_stem}.TIFF"

                shutil.copy(pair["rgb"]["filepath"], os.path.join(rgb_raw_output_dir, rgb_output_name))

                corrected_rgb = _apply_rgb_fov_correction(pair["rgb"]["filepath"])
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
    # check to see that the output directory is empty
    if len(os.listdir(OUTPUT_FOLDER)) > 0 and RESUME_ID == 0:
        print(
            'Error: Output folder is not empty. Make sure old data is removed before use.')
        sys.exit(1)
    #If the output folder contains files and the resume ID is set to 0 or higher
    elif len(os.listdir(OUTPUT_FOLDER)) > 0 and RESUME_ID >= 0:
        print(f'WARNING: Output dir not empty and Resume ID set to {RESUME_ID}. Proceed with caution.')

    # Loop through input folder, then loop through subfolders
    print(f'{len(os.listdir(INPUT_FOLDER))} subfolders detected! Starting processing now. -- time = {(time.time_ns()-t_start)/1e9:4.3f} seconds')
    for id_subfolder, subfolder in enumerate(os.listdir(INPUT_FOLDER)):
        print(f'For subfolder {subfolder} [{id_subfolder+1}/{len(os.listdir(INPUT_FOLDER))}], {len(os.listdir(f"{INPUT_FOLDER}{subfolder}/"))} files detected. Starting processing. -- time = {(time.time_ns()-t_start)/1e9:4.3f} seconds')

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
        for id_file, file in enumerate(os.listdir(f'{INPUT_FOLDER}{subfolder}/')):
            # M30T Camera section
            if CAMERA_USED == "M30T":
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
            elif CAMERA_USED == "M2EA":
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

                # FOV CORRECTIONS HERE
                rgb_img = Image.open(
                    f'{INPUT_FOLDER}{subfolder}/{rgb_filename}')
                # M30T camera images
                if CAMERA_USED == "M30T":
                    # NOTE: The following crop transform seems to work fairly well, though cannot deal w/ lens distortions.
                    #       Crop params were found through iterative improvement (hence the many + & - terms). Aspect ratio must be preserved or a resize operation must occur to preserve 1:1 correlation.
                    # Left, Upper, Right, Lower
                    # crop image
                    rgb_img = rgb_img.crop(
                        (640+40-(60), 412+30+12, 4000-640-40-40-40-16-16+(40), 3000-412-30-30-30-12))
                    # resize image
                    rgb_img = rgb_img.resize((640, 512))
                # M2EA camera images
                elif CAMERA_USED == "M2EA":
                    # rgb_img = rgb_img.crop((640+40-(60), 412+30+12, 4000-640-40-40-40-16-16+(40), 3000-412-30-30-30-12))
                    #crop image
                    rgb_img = rgb_img.crop(
                        (1280+80, 824, 8000-1280+80, 6000-824))
                    #resize image
                    rgb_img = rgb_img.resize((640, 512))

                # Copy cropped rgb image to output w/ orginal exif data
                rgb_img.save(
                    f'{OUTPUT_FOLDER}{subfolder}/Images/RGB/Corrected FOV/{rgb_filename_n}', exif=rgb_img.info['exif'])
                rgb_img.close()

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
    if PROCESSING_MODE == "PRESORTED_STANDARD":
        process_presorted_standard()
    else:
        raw_file_sorting()
