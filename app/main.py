"""API local de costo de despacho. Escucha solo en este PC."""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.cotizar import PedidoInvalido, cotizar
from app.datos import ErrorDatos

app = FastAPI(title="API Despacho", version="0.1.0")


class LineaIn(BaseModel):
    sku: str
    cantidad: int = Field(gt=0)


class CotizarIn(BaseModel):
    cliente: str = Field(min_length=1)
    lineas: list[LineaIn] = Field(min_length=1)


@app.get("/salud")
def salud():
    return {"estado": "ok", "servicio": "api-despacho"}


@app.post("/cotizar")
def post_cotizar(pedido: CotizarIn):
    try:
        return cotizar(pedido.model_dump())
    except PedidoInvalido as exc:
        raise HTTPException(status_code=400, detail={"mensaje": str(exc), **exc.extra}) from exc
    except ErrorDatos as exc:
        raise HTTPException(status_code=503, detail={"mensaje": str(exc)}) from exc
