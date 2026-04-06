# FlameVQA-Multi-Tool-Data-Pipeline

---

## Project Credits

FlameVQA Dataset Builder is part of a broader wildfire research effort at Clemson University within the IS-WiN Lab.

**Project Leadership**  
Mobin Habibpour, Niloufar Alipour Talemi  

**Undergraduate Researchers**  
John Spodnik, Camren J. Khoury  

**Project Oversight**  
Dr. Fatemeh Afghah  

**Foundational Work**  
Bryce Hopkins, Michael Marinaccio (Flame-Data-Pipeline)

---

This repository specifically documents **Camren J. Khoury’s contributions**, focusing on:

- GUI-based tooling  
- Workflow integration  
- Structured dataset preparation  
- Improved usability for wildfire imagery pipelines  

While the overall research effort is collaborative, this repository isolates and presents the dataset-building and tooling improvements.

---

## Overview

FlameVQA Dataset Builder is a **GUI-based system** designed to transform raw wildfire imagery into structured, usable multimodal datasets.

### Improvements include:
- Improved imagery organization  
- Metadata preservation  
- Better handling of intermediate outputs  
- Structured dataset preparation for downstream workflows  
- Removal of DJI dependency for non-RJPEG data  
- Attempted mitigation of memory leak issues  
- New GUI for comparison and user input  

This project builds on the **Flame-Data-Pipeline**, extending it from separate preprocessing tools into a more unified dataset construction workflow.

---

## Purpose

Wildfire datasets are often:

- Large-scale  
- Multi-modal (RGB + thermal)  
- Inconsistently structured  
- Difficult to preprocess reliably  

### This tool addresses those issues by:

- Centralizing dataset preparation  
- Reducing manual preprocessing  
- Improving consistency and traceability  

**Goal:**  
Convert raw or semi-structured data into clean, standardized, research-ready datasets.

---

## Foundation

This repository builds on the original:

### Flame-Data-Pipeline

Core tools from that work include:

- Raw File Sorting Tool  
- FLAME Image Labeling Tool  
- Image GPS Tracing Tool  

These tools established the initial pipeline for:

- Organizing wildfire imagery  
- Pairing RGB and thermal data  
- Extracting metadata  

FlameVQA Dataset Builder extends this into a more integrated workflow.

---

## What This Repository Covers

This repository focuses on dataset workflow improvements:

- GUI development  
- Workflow integration  
- Improved dataset organization  
- Handling real-world (non-ideal) data structures  
- Reusable and standardized output formats  
- Support for multimodal dataset construction  

---

## Acknowledgment

This work is associated with:

- Clemson University  
- IS-WiN Lab  

### Contributors

- Mobin Habibpour (Project Lead)  
- Niloufar Alipour Talemi (Project Lead)  
- John Spodnik (Undergraduate Researcher)  
- Camren J. Khoury (Undergraduate Researcher, Tooling Development)  
- Dr. Fatemeh Afghah (Project Oversight)  
- Bryce Hopkins (Original Pipeline Development)  
- Michael Marinaccio (Original Contributions & Support)  
