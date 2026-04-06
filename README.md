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

The current code being worked on: Flame-Data-Pipline-Main -> Raw File Sorting Tool GUI (other tools are currently unchanged)

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

Optional (depending on usage):
- PySimpleGUI (GUI components)  
- videoprops (video metadata handling)  
- Jupyter Notebook (GPS tracing tool)  

---

## Usage (High-Level)

Typical workflow:

1. Load raw or semi-structured dataset  
2. Pair RGB and thermal imagery  
3. Process and organize into structured format  
4. Generate outputs for labeling or downstream tasks  

---

## Known Issues

- Original pipeline memory leak (seaborn-related) still partially present  
- Large batches (>3000 image pairs) may cause high memory usage  

---

## Scope

This repository focuses only on:
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
