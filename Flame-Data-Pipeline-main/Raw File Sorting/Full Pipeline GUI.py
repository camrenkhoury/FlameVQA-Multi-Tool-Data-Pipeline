import importlib.util
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
LEGACY_GUI_PATH = SCRIPT_DIR / "Raw File Sorting GUI.py"


def load_gui_module():
    spec = importlib.util.spec_from_file_location("flame_full_pipeline_gui", LEGACY_GUI_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    module = load_gui_module()
    module.main()


if __name__ == "__main__":
    main()
