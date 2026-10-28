"""Carga la configuración local. No imprime claves."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
ENV_LOCAL = ROOT / ".env"
ENV_CCL = Path(r"c:\DEV\CMK\CCL\backend\.env")


def cargar_entorno():
    if ENV_LOCAL.exists():
        load_dotenv(ENV_LOCAL)
        return "local"
    if ENV_CCL.exists():
        load_dotenv(ENV_CCL)
        return "ccl"
    return ""


def entorno(nombre, defecto=""):
    return os.environ.get(nombre, defecto).strip()


def puerto():
    try:
        return int(entorno("PORT", "4190") or "4190")
    except ValueError:
        return 4190
