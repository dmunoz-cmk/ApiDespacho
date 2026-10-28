"""Tarifario de lista desde [TRP].[matriz_costos]."""
import math

from app.nombres import js_round, norm_nombre, redondear_kg

_CACHE = None
_CORRECCIONES = None


def limpiar_cache():
    global _CACHE, _CORRECCIONES
    _CACHE = None
    _CORRECCIONES = None


def _bucket(courier, via):
    c = str(courier or "")
    v = str(via or "")
    if c == "Newtrans" and v == "Aerea":
        return "Newtrans|Aerea"
    if c == "Newtrans" and v == "Terrestre":
        return "Newtrans|Terrestre"
    if c == "Cargoex":
        return "Cargoex|Aerea"
    if c == "Chibra":
        return "Chibra|Aerea"
    if c == "Transfarma" and v == "Aerea":
        return "Transfarma|Aerea"
    if c == "Transfarma":
        return "Transfarma|Terrestre"
    return ""


def armar_tarifas(filas):
    mapas = {}
    for fila in filas or []:
        comuna = str(fila.get("Comuna") or fila.get("comuna") or "").strip()
        clave = norm_nombre(comuna)
        cubo = _bucket(fila.get("Courier") or fila.get("courier"), fila.get("Via") or fila.get("via"))
        if not clave or not cubo:
            continue
        item = mapas.setdefault(cubo, {}).setdefault(clave, {
            "destino": comuna,
            "region": str(fila.get("Region") or fila.get("region") or "").strip(),
            "tramos": [],
        })
        hasta = fila.get("Kg_Hasta")
        if hasta is None:
            hasta = fila.get("kg_hasta")
        maximo = math.inf if hasta is None or hasta == "" else float(hasta)
        item["tramos"].append({
            "min": float(fila.get("Kg_Desde") if fila.get("Kg_Desde") is not None else fila.get("kg_desde") or 0),
            "max": maximo,
            "valor": float(fila.get("Precio_Neto") if fila.get("Precio_Neto") is not None else fila.get("precio_neto")),
            "por_kg": str(fila.get("Tipo_Precio") or fila.get("tipo_precio") or "").strip().lower() == "por_kg",
        })
    return mapas


def precio_generico(tramos, kg):
    if not (kg > 0) or not tramos:
        return None
    planos = sorted((t for t in tramos if not t["por_kg"]), key=lambda t: t["max"])
    extras = sorted((t for t in tramos if t["por_kg"]), key=lambda t: t["min"])
    if not extras:
        techo = next((t for t in planos if kg <= t["max"]), None)
        if techo:
            return techo["valor"]
        if not planos:
            return None
        ultimo = planos[-1]
        if ultimo["max"] > 0:
            return ultimo["valor"] + (kg - ultimo["max"]) * (ultimo["valor"] / ultimo["max"])
        return ultimo["valor"]
    if not planos:
        return None
    ultimo = planos[-1]
    if kg <= ultimo["max"]:
        encontrado = next((t for t in planos if kg <= t["max"]), None)
        return encontrado["valor"] if encontrado else ultimo["valor"]
    costo = ultimo["valor"]
    cubierto = ultimo["max"]
    for extra in extras:
        if kg <= cubierto:
            break
        techo = extra["max"] if math.isfinite(extra["max"]) else kg
        desde = max(cubierto, extra["min"])
        hasta = min(kg, techo)
        if hasta > desde:
            costo += (hasta - desde) * extra["valor"]
        cubierto = max(cubierto, hasta)
    return costo


def cargar_tarifas(leer_filas):
    global _CACHE
    if _CACHE is None:
        _CACHE = armar_tarifas(leer_filas())
    return _CACHE


def armar_correcciones(filas):
    mapa = {}
    for fila in filas or []:
        localidad = norm_nombre(fila.get("Localidad"))
        corregida = str(fila.get("Comuna_Corregida") or "").strip()
        if localidad and corregida:
            mapa[localidad] = corregida
    return mapa


def cargar_correcciones(leer_filas):
    global _CORRECCIONES
    if _CORRECCIONES is None:
        _CORRECCIONES = armar_correcciones(leer_filas())
    return _CORRECCIONES


def claves_comuna(comuna, correcciones=None):
    """La comuna tal como viene de SAP y, si existe, su nombre corregido en el tarifario."""
    claves = [norm_nombre(comuna)]
    corregida = (correcciones or {}).get(claves[0])
    if corregida and norm_nombre(corregida) not in claves:
        claves.append(norm_nombre(corregida))
    return [c for c in claves if c]


def _item(tarifas, cubo, comuna, correcciones=None):
    mapa = tarifas.get(cubo) or {}
    for clave in claves_comuna(comuna, correcciones):
        if clave in mapa:
            return mapa[clave]
    return None


def region_de(tarifas, comuna, correcciones=None):
    for cubo in tarifas:
        item = _item(tarifas, cubo, comuna, correcciones)
        if item and str(item.get("region") or "").strip():
            return str(item["region"]).strip()
    return ""


def cotizar_tramo(tarifas, comuna, courier, via, kg, correcciones=None):
    kg_ok = redondear_kg(kg)
    if not (kg_ok > 0):
        return None, None
    item = _item(tarifas, _bucket(courier, via), comuna, correcciones)
    if not item:
        return kg_ok, None
    bruto = precio_generico(item["tramos"], kg_ok)
    if bruto is None or not math.isfinite(bruto):
        return kg_ok, None
    return kg_ok, js_round(bruto)
