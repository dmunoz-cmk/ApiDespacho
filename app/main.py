"""API local de costo de despacho. Escucha solo en este PC."""
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.cotizar import PedidoInvalido, cotizar
from app.datos import ErrorDatos

def _version():
    archivo = Path(__file__).resolve().parents[1] / "VERSION"
    if archivo.exists():
        return archivo.read_text(encoding="utf-8").strip() or "0.0.0"
    return "0.0.0"


VERSION = _version()
app = FastAPI(title="API Despacho", version=VERSION)


class LineaIn(BaseModel):
    sku: str
    cantidad: int = Field(gt=0)


class CotizarIn(BaseModel):
    cliente: str = Field(min_length=1)
    lineas: list[LineaIn] = Field(min_length=1)


@app.get("/salud")
def salud():
    return {"estado": "ok", "servicio": "api-despacho", "version": VERSION}


@app.post("/cotizar")
def post_cotizar(pedido: CotizarIn):
    try:
        return cotizar(pedido.model_dump())
    except PedidoInvalido as exc:
        raise HTTPException(status_code=400, detail={"mensaje": str(exc), **exc.extra}) from exc
    except ErrorDatos as exc:
        raise HTTPException(status_code=503, detail={"mensaje": str(exc)}) from exc
