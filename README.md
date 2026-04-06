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

This repository documents **Camren J. Khoury’s contributions**, focusing on improving dataset workflows, GUI tooling, and usability.

---

## Current Development

The primary code currently under active development is:

**Flame-Data-Pipeline-main → Raw File Sorting Tool (GUI)**  

Other tools in the pipeline remain unchanged at this stage.

### How to Run

From within the **Raw File Sorting Tool** directory:

```
python "Raw File Sorting Tool GUI.py"
```

### What It Does

The GUI performs automated preprocessing by:

- Reading files from the **Input Folder**
- Pairing:
  - RGB images  
  - Thermal images  
  - Thermal TIFF data  
- Generating structured outputs in the **Output Folder**

Each dataset is processed and reorganized into a consistent format for downstream use.

### Output Structure

```
Output Folder/
└── <Dataset_Name>/
    ├── Images/
    │   ├── RGB/
    │   │   ├── Corrected FOV/
    │   │   └── Raw/
    │   └── Thermal/
    │       ├── Celsius TIFF/
    │       └── JPG/
    └── Videos/
        ├── RGB/
        └── Thermal/
```

---

## Overview

FlameVQA Dataset Builder is a **GUI-based system** for transforming raw wildfire imagery into structured multimodal datasets.

### Key Improvements
- Improved dataset organization and structure  
- Metadata preservation and traceability  
- Improved intermediate processing pipeline  
- Removal of strict DJI/RJPEG dependency  
- Partial mitigation of known memory issues  
- New GUI for comparison and user-driven workflow control  

This extends the original Flame-Data-Pipeline into a **more unified dataset construction workflow**.

---

## Purpose

Wildfire datasets are often:
- Large-scale  
- Multimodal (RGB + thermal)  
- Inconsistently structured  

This tool addresses those issues by:
- Centralizing preprocessing  
- Reducing manual steps  
- Standardizing outputs  

**Goal:** Convert raw or semi-structured data into clean, research-ready datasets.

---

## Foundation

Built on the original **Flame-Data-Pipeline**, which includes:

- Raw File Sorting Tool  
- FLAME Image Labeling Tool  
- Image GPS Tracing Tool  

These established the baseline for pairing imagery and extracting metadata.

---

## Dependencies

### Core Environment
- Python 3.9+  
- pip 24.0+  

### Libraries
- opencv-python  
- pillow  
- numpy  
- matplotlib  
- seaborn  
- psutil  
- exif  

Optional:
- PySimpleGUI  
- videoprops  
- Jupyter Notebook  

---

## Usage (High-Level)

Typical workflow:

1. Load dataset into Input Folder  
2. Run GUI tool  
3. Automatically pair and structure data  
4. Use output for labeling or downstream processing  

---

## Known Issues

- Original pipeline memory leak (seaborn-related) still partially present  
- Large batches (>3000 image pairs) may cause high memory usage  

---

## Scope

This repository focuses on:
- Dataset preparation tooling  
- Workflow improvements  

It does **not include** internal research methods or restricted project details.

---

## Acknowledgment

Developed at Clemson University – IS-WiN Lab.

**Contributors**
- Mobin Habibpour  
- Niloufar Alipour Talemi  
- John Spodnik  
- Camren J. Khoury  
- Dr. Fatemeh Afghah  
- Bryce Hopkins  
- Michael Marinaccio  
