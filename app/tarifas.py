"""Tarifario vigente desde [TRP].[tarifarios] + coberturas. Sin descuento por tramo."""
import math
from datetime import date

from app.nombres import js_round, norm_nombre, redondear_kg

_CACHE = {}
_CORRECCIONES = None

FACTURAS_CONTROLADO = {"CONTROLADO", "CREF"}
FACTURAS_REFRIGERADO = {"REF", "CREF"}
CRYO_NOMBRES = {"NEVERA 12", "NEVERA 25", "CRYOPACK"}


def limpiar_cache():
    global _CACHE, _CORRECCIONES
    _CACHE = {}
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


def _num(v, defecto=0):
    if v is None or v == "":
        return defecto
    try:
        n = float(v)
    except (TypeError, ValueError):
        return defecto
    return n if math.isfinite(n) else defecto


def _celda(fila, *nombres):
    if not fila:
        return None
    for n in nombres:
        if n in fila and fila[n] is not None and fila[n] != "":
            return fila[n]
    lower = {str(k).lower(): v for k, v in fila.items()}
    for n in nombres:
        v = lower.get(str(n).lower())
        if v is not None and v != "":
            return v
    return None


def fecha_iso(valor=None):
    if not valor:
        return date.today().isoformat()
    texto = str(valor).strip()
    if len(texto) >= 10 and texto[4] == "-" and texto[7] == "-":
        return texto[:10]
    return date.today().isoformat()


def armar_tarifas(filas):
    """Forma de prueba (filas tipo matriz). La API viva no la usa."""
    mapas = {}
    for fila in filas or []:
        comuna = str(_celda(fila, "Comuna", "comuna") or "").strip()
        clave = norm_nombre(comuna)
        cubo = _bucket(_celda(fila, "Courier", "courier"), _celda(fila, "Via", "via"))
        if not clave or not cubo:
            continue
        item = mapas.setdefault(cubo, {}).setdefault(clave, {
            "destino": comuna,
            "region": str(_celda(fila, "Region", "region") or "").strip(),
            "tramos": [],
        })
        hasta = _celda(fila, "Kg_Hasta", "kg_hasta")
        maximo = math.inf if hasta is None or hasta == "" else float(hasta)
        item["tramos"].append({
            "min": float(_celda(fila, "Kg_Desde", "kg_desde") or 0),
            "max": maximo,
            "valor": float(_celda(fila, "Precio_Neto", "precio_neto", "Precio", "precio")),
            "por_kg": str(_celda(fila, "Tipo_Precio", "tipo_precio") or "").strip().lower() == "por_kg",
        })
    mapas["_reglas"] = {}
    mapas["_fuente"] = "prueba"
    return mapas


def _agrupar_precios(filas):
    by_hub = {}
    for fila in filas or []:
        hub = norm_nombre(_celda(fila, "Hub", "hub"))
        if not hub:
            continue
        hasta = _celda(fila, "Kg_hasta", "Kg_Hasta", "kg_hasta")
        zona = _celda(fila, "Zona", "zona")
        by_hub.setdefault(hub, []).append({
            "zona": str(zona).strip().upper() if zona else None,
            "min": float(_celda(fila, "Kg_desde", "Kg_Desde", "kg_desde") or 0),
            "max": math.inf if hasta is None or hasta == "" else float(hasta),
            "valor": float(_celda(fila, "Precio", "precio", "Precio_Neto") or 0),
            "por_kg": str(_celda(fila, "Tipo_precio", "Tipo_Precio") or "").strip().lower() == "por_kg",
        })
    return by_hub


def _elegir_filas(by_hub, dest, hub, zona):
    for clave in (dest, hub):
        if not clave:
            continue
        arr = by_hub.get(clave)
        if not arr:
            continue
        if zona:
            z = [t for t in arr if t.get("zona") == zona]
            if z:
                return z
        sin = [t for t in arr if not t.get("zona")]
        if sin:
            return sin
        return arr
    return None


def _filas_a_tramos(filas, factor):
    out = []
    for t in filas or []:
        valor = _num(t.get("valor")) * factor
        if not math.isfinite(valor):
            continue
        out.append({
            "min": _num(t.get("min")),
            "max": t.get("max") if t.get("max") is not None else math.inf,
            "valor": valor,
            "por_kg": bool(t.get("por_kg")),
        })
    return out


def _reglas_mapa(filas):
    out = {}
    for fila in filas or []:
        clave = str(_celda(fila, "Clave", "clave") or "").strip()
        if clave:
            out[clave] = _num(_celda(fila, "Valor", "valor"), None)
    return out


def armar_tarifas_trp(stack):
    """Expande hubs a destinos con coberturas y zona. Aplica ramal de la regla, no descuento comercial."""
    mapas = {}
    reglas = {}
    cob_por = {}
    for fila in (stack or {}).get("coberturas") or []:
        courier = str(_celda(fila, "Courier", "courier") or "").strip()
        dest = norm_nombre(_celda(fila, "Destino", "destino"))
        if not courier or not dest:
            continue
        cob_por.setdefault(courier, []).append({
            "destino": dest,
            "hub": norm_nombre(_celda(fila, "Hub", "hub")),
            "zona": str(_celda(fila, "Zona", "zona") or "").strip().upper() or None,
            "es_hub": bool(_celda(fila, "Es_Hub", "es_hub")),
            "comuna": str(_celda(fila, "Comuna", "comuna") or "").strip(),
        })

    for (courier, via), bloque in ((stack or {}).get("tarifarios") or {}).items():
        cubo = _bucket(courier, via)
        if not cubo:
            continue
        reglas[cubo] = _reglas_mapa((bloque or {}).get("reglas"))
        ramal_pct = _num((reglas[cubo] or {}).get("ramal_pct"))
        by_hub = _agrupar_precios((bloque or {}).get("precios"))
        destinos = mapas.setdefault(cubo, {})
        seen = set()

        def push(destino, filas, es_hub, hub_key):
            clave = norm_nombre(destino)
            if not clave or clave in seen or not filas:
                return
            factor = (1 + ramal_pct / 100) if (not es_hub and ramal_pct > 0) else 1
            tramos = _filas_a_tramos(filas, factor)
            if not tramos:
                return
            seen.add(clave)
            destinos[clave] = {
                "destino": clave,
                "region": "",
                "tramos": tramos,
                "ramal_aplicado": factor > 1,
                "hub": hub_key,
            }

        for cob in cob_por.get(courier) or []:
            filas = _elegir_filas(by_hub, cob["destino"], cob["hub"], cob["zona"])
            if not filas:
                continue
            es_hub = cob["es_hub"] or cob["destino"] == cob["hub"]
            push(cob["destino"], filas, es_hub, cob["hub"])
        for hub, filas in by_hub.items():
            if hub in seen:
                continue
            sin = [t for t in filas if not t.get("zona")]
            push(hub, sin or filas, True, hub)

    mapas["_reglas"] = reglas
    mapas["_fuente"] = "trp-tarifarios"
    mapas["_fecha"] = (stack or {}).get("fecha")
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


def cargar_tarifas(fecha=None):
    from app.datos import leer_stack_tarifarios

    f = fecha_iso(fecha)
    if f not in _CACHE:
        _CACHE[f] = armar_tarifas_trp(leer_stack_tarifarios(f))
    return _CACHE[f]


def armar_correcciones(filas):
    mapa = {}
    for fila in filas or []:
        localidad = norm_nombre(_celda(fila, "Localidad"))
        corregida = str(_celda(fila, "Comuna_Corregida") or "").strip()
        if localidad and corregida:
            mapa[localidad] = corregida
    return mapa


def cargar_correcciones(leer_filas=None):
    global _CORRECCIONES
    if _CORRECCIONES is None:
        if leer_filas is None:
            from app.datos import leer_correcciones
            leer_filas = leer_correcciones
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
        if cubo.startswith("_"):
            continue
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


def reglas_de(tarifas, courier, via):
    cubo = _bucket(courier, via)
    raw = ((tarifas or {}).get("_reglas") or {}).get(cubo) or {}
    ter = ((tarifas or {}).get("_reglas") or {}).get(_bucket(courier, "Terrestre")) or {}
    if courier == "Newtrans":
        return {
            "cedible": _num(raw.get("cedible"), _num(ter.get("cedible"), 590)),
            "cedible_controlado": _num(raw.get("cedible_controlado"), 0),
            "controlado": _num(raw.get("controlado"), _num(ter.get("controlado"), 11270)),
            "refrigerado": _num(raw.get("refrigerado"), _num(ter.get("refrigerado"), 11270)),
            "cryo_retorno": _num(raw.get("cryo_retorno"), _num(ter.get("cryo_retorno"), 0)),
            "cryo_retorno_factor": 0,
            "combustible_pct": _num(raw.get("combustible_pct"), _num(ter.get("combustible_pct"), 0)),
        }
    return {
        "cedible": _num(raw.get("cedible"), _num(ter.get("cedible"), 500)),
        "cedible_controlado": _num(raw.get("cedible_controlado"), _num(ter.get("cedible_controlado"), 1500)),
        "controlado": 0,
        "refrigerado": 0,
        "cryo_retorno": None,
        "cryo_retorno_factor": _num(raw.get("cryo_retorno_factor"), _num(ter.get("cryo_retorno_factor"), 0.7)),
        "combustible_pct": _num(raw.get("combustible_pct"), 0),
    }


def kilos_cryo(factura):
    total = 0
    hay = False
    for c in factura.get("contenedores") or []:
        if str(c.get("nombre") or "").strip().upper() not in CRYO_NOMBRES:
            continue
        hay = True
        kg = c.get("kg")
        cant = _num(c.get("cantidad"), 1)
        if kg is not None:
            total += float(kg) * cant
        else:
            total += cant
    return total if hay and total > 0 else None


def aplicar_reglas(tarifas, correcciones, factura, comuna, courier, via, kg, flete):
    """Cedible, controlado/refrigerado solo de ida y crios. Sin descuento por tramo."""
    r = reglas_de(tarifas, courier, via)
    fid = str(factura.get("id") or "")
    bultos = max(int(factura.get("bultos") or 1), 1)
    es_ctrl = fid in FACTURAS_CONTROLADO
    es_ref = fid in FACTURAS_REFRIGERADO
    flete_n = js_round(flete) or 0
    combustible = js_round(flete_n * r["combustible_pct"] / 100) if r["combustible_pct"] else 0
    if courier == "Transfarma" and es_ctrl and r["cedible_controlado"]:
        cedible = js_round(r["cedible_controlado"])
    else:
        cedible = js_round(r["cedible"])
    extras_ida = 0
    if courier == "Newtrans":
        if es_ref:
            extras_ida += js_round(r["refrigerado"] * bultos)
        elif es_ctrl:
            extras_ida += js_round(r["controlado"] * bultos)
    cryo = 0
    if es_ref:
        if courier == "Newtrans":
            cryo = js_round(r["cryo_retorno"] or 0)
        else:
            kg_vuelta = kilos_cryo(factura) or kg
            _kg, ter = cotizar_tramo(tarifas, comuna, courier, "Terrestre", kg_vuelta, correcciones)
            if ter is not None:
                cryo = js_round(ter * r["cryo_retorno_factor"])
    costo = js_round(flete_n + combustible + cedible + extras_ida + cryo)
    return {
        "flete": flete_n,
        "combustible": combustible,
        "cedible": cedible,
        "extras_ida": extras_ida,
        "cryo_retorno": cryo,
        "costo": costo,
    }
