import json
import os
import sys
from pathlib import Path

if getattr(sys, 'frozen', False):
    CONFIG_PATH = str(Path(sys.executable).parent / "config.json")
else:
    CONFIG_PATH = str(Path(__file__).parent / "config.json")


def cargar_config():
    if not os.path.exists(CONFIG_PATH):
        return {}
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def guardar_config(data):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def cargar_horarios_paro():
    config = cargar_config()
    return config.get("horarios_paro", {})


def guardar_horarios_paro(data):
    config = cargar_config()
    config["horarios_paro"] = data
    guardar_config(config)