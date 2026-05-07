#### File name:     Image GPS Tracing.py
#### Last Updated:          02/19/2024
#### Creator:       Bryce Hopkins
#### Purpose:       Sorts a directory of images by date-time and returns a csv of filenames, GPS coords, and datetime for each image found in the directory
#### Instructions:  Specify source image folder as well as output csv filename.

'''
Create source and output directory variables

Source Directory may be any directory where images are stored.
Image GPS Tracing tool will iterate through all images in the
specified directory.
'''

SOURCE_DIR = './Images/Fire/RGB/'
OUTPUT_CSV_PATH = './GPS_Traces.csv'

#import required libraries
import csv
from datetime import datetime
import os
from pathlib import Path

from exif import Image

'''
Function that will convert latitude or longitude in hours-minutes-seconds (HMS) format 
to decimal degrees format 

Variable coords is expected to be a list with three values
    1.) Hours
    2.) Minutes
    3.) Seconds

Variable ref is expected to be a 'W' or 'S' character representing 
West or South direction
'''


def decimal_coords_from_HMS(coords, ref):
    decimal_degrees = coords[0] + coords[1] / 60 + coords[2] / 3600
    if ref == 'W' or ref == 'S':
        decimal_degrees = -decimal_degrees
    return decimal_degrees


'''
Function that will take in a path to an image file, read EXIF metadata, 
and return the filename, datetime, decimal degrees latitude and longitude, 
and the GPS altitude
'''


def image_coordinates(image_path):
    # open image file in binary read mode
    with open(image_path, 'rb') as src:
        # create Image object from the file
        img = Image(src)
    # check to see if the image contains EXIF metadata
    if img.has_exif:
        try:
            img.gps_longitude
            # Conver the latitude and longitude from HMS to decimal degrees
            coords = (decimal_coords_from_HMS(img.gps_latitude,
                                              img.gps_latitude_ref),
                      decimal_coords_from_HMS(img.gps_longitude,
                                              img.gps_longitude_ref))
            # return tuple: name, datetime, coords, and altitude
            return (src.name, img.datetime_original, coords, img.gps_altitude)

        # error if GPS coordinates not found in EXIF metadata
        except AttributeError:
            print('Image lacks GPS coordinates in exif')
    # error if there is no EXIF metadata in Image file
    else:
        print('The Image has no EXIF information')


def _image_paths(source_dir, recursive=False):
    source_path = Path(source_dir)
    pattern_iter = source_path.rglob("*") if recursive else source_path.iterdir()
    valid_extensions = {".jpg", ".jpeg", ".tif", ".tiff"}
    return sorted(
        path for path in pattern_iter
        if path.is_file() and path.suffix.lower() in valid_extensions
    )


def trace_images(source_dir=SOURCE_DIR, output_csv_path=OUTPUT_CSV_PATH, recursive=False):
    """Extract GPS EXIF records from a directory of images and write a sorted CSV."""
    source_path = Path(source_dir)
    output_path = Path(output_csv_path)
    if not source_path.exists() or not source_path.is_dir():
        raise FileNotFoundError(f"GPS source directory does not exist: {source_path}")

    print('Starting Image GPS Tracing Tool.')
    print(f'Extracting EXIF metadata from images in {source_path}')

    records = []
    skipped = []
    for path in _image_paths(source_path, recursive=recursive):
        try:
            img_stats = image_coordinates(str(path))
            if img_stats is None:
                skipped.append((str(path), "missing_exif_or_gps"))
                continue
            dt = datetime.strptime(img_stats[1], "%Y:%m:%d %H:%M:%S")
            records.append(
                {
                    "datetime": dt,
                    "latitude": img_stats[2][0],
                    "longitude": img_stats[2][1],
                    "altitude": img_stats[3],
                    "filename": path.name,
                    "path": img_stats[0],
                }
            )
        except Exception as exc:
            skipped.append((str(path), str(exc)))

    print('Sorting images by datetime.')
    records.sort(key=lambda record: record["datetime"])

    output_path.parent.mkdir(parents=True, exist_ok=True)
    print(f'Logging data to {output_path}')
    with open(output_path, 'w', newline='') as log:
        log_writer = csv.writer(log)
        header = ['Datetime', 'Latitude', 'Longitude', 'Altitude [m ASL]', 'Image Filename', 'Image Path']
        log_writer.writerow(header)
        for record in records:
            log_writer.writerow([
                datetime.strftime(record["datetime"], "%Y:%m:%d %H:%M:%S"),
                record["latitude"],
                record["longitude"],
                record["altitude"],
                record["filename"],
                record["path"],
            ])

    print(
        f'Image GPS Tracing Tool completed. '
        f'Wrote {len(records)} record(s), skipped {len(skipped)} image(s).'
    )
    return {
        "source_dir": str(source_path),
        "output_csv_path": str(output_path),
        "processed": len(records) + len(skipped),
        "written": len(records),
        "skipped": len(skipped),
        "skipped_details": skipped,
    }


if __name__ == "__main__":
    trace_images(SOURCE_DIR, OUTPUT_CSV_PATH)
