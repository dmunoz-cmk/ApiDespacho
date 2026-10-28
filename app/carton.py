"""Cartonización del simulador CDD. El kilo es el volumen externo / 4000."""
import math

from app.nombres import es_cubeta_azul, js_round

UTIL_CARTON = 0.70
DIVISOR = 4000
VOL_UN_MAX = 0.004500

CAP_M3 = {
    "CAJA CHICA": (20 * 16 * 15.5) / 1e6,
    "CAJA MEDIA": (31.5 * 24 * 31.5) / 1e6,
    "CAJA": (52 * 37 * 23) / 1e6,
    "BANDEJA": (50 * 35 * 30) / 1e6,
}
CAP_FRIO_M3 = {
    "NEVERA 12": ((20 * 15 * 15) / 1e6) * 0.80,
    "NEVERA 25": ((22 * 22 * 22) / 1e6) * 0.80,
}
KG_EXTERNO = {
    "CAJA CHICA": (20 * 16 * 15.5) / DIVISOR,
    "CAJA MEDIA": (31.5 * 24 * 31.5) / DIVISOR,
    "CAJA": (52 * 37 * 23) / DIVISOR,
    "NEVERA 12": (35 * 25 * 28) / DIVISOR,
    "NEVERA 25": (38 * 40 * 34) / DIVISOR,
    "BANDEJA": (50 * 35 * 30) / DIVISOR,
}

FACTURAS = (
    ("MEZZ", "Mezz"),
    ("REF", "Refrigerado"),
    ("FARMA", "Farma"),
    ("CONTROLADO", "Controlado"),
    ("CREF", "Controlado refrigerado"),
    ("SIN_FAMILIA", "Sin familia"),
)
REFRIGERADAS = {"REF", "CREF"}


def sku_key(valor):
    texto = str(valor or "").strip().upper()
    if not texto:
        return ""
    return texto.lstrip("0") or "0"


def tipo_de_linea(prtfam, lngdsc, rut=""):
    fam = str(prtfam or "").strip().upper()
    dsc = str(lngdsc or "").upper()
    if fam == "CONTROLADO":
        return "CREF" if "(REF)" in dsc else "CONTROLADO"
    if fam == "VETREFRIG":
        return "VREF"
    if fam == "REFRIGERAD":
        return "REFR"
    if fam in ("VETERINARI", "COSMETICO", "NUTRICIONA"):
        return "MEZZ"
    if fam in ("MEDI APROB", "ONCOLOGICO"):
        return "CUBETA" if es_cubeta_azul(rut) else "FARMA"
    return "SIN_FAMILIA"


def factura_de(tipo):
    if tipo == "MEZZ":
        return "MEZZ"
    if tipo in ("REFR", "VREF"):
        return "REF"
    if tipo in ("FARMA", "CUBETA"):
        return "FARMA"
    if tipo == "CONTROLADO":
        return "CONTROLADO"
    if tipo == "CREF":
        return "CREF"
    return "SIN_FAMILIA"


def grupo_de(tipo, prtfam):
    if tipo in ("REFR", "VREF", "CREF", "CUBETA", "FARMA", "SIN_FAMILIA"):
        return tipo
    fam = str(prtfam or "").strip() or "SIN FAMILIA"
    return f"{tipo} | FAM: {fam}"


def _caja(nombre, cantidad, kg_unit):
    return {"nombre": nombre, "cantidad": cantidad, "kg": kg_unit}


def empacar_ambiente(vol):
    cap_grande = CAP_M3["CAJA"] * UTIL_CARTON
    n_grande = math.floor(vol / cap_grande + 1e-12)
    resto = vol - n_grande * cap_grande
    out = []
    if n_grande > 0:
        out.append(_caja("CAJA", n_grande, KG_EXTERNO["CAJA"]))
    if resto > 1e-9:
        orden = ("CAJA CHICA", "CAJA MEDIA", "CAJA")
        nombre = next((n for n in orden if CAP_M3[n] * UTIL_CARTON + 1e-12 >= resto), "CAJA")
        out.append(_caja(nombre, 1, KG_EXTERNO[nombre]))
    return out


def empacar_frio(vol):
    cap25 = CAP_FRIO_M3["NEVERA 25"]
    cap_chica = CAP_FRIO_M3["NEVERA 12"]
    n25 = math.floor(vol / cap25 + 1e-12)
    resto = vol - n25 * cap25
    out = []
    if n25 > 0:
        out.append(_caja("NEVERA 25", n25, KG_EXTERNO["NEVERA 25"]))
    if resto > 1e-9:
        nombre = "NEVERA 12" if resto <= cap_chica + 1e-12 else "NEVERA 25"
        out.append(_caja(nombre, 1, KG_EXTERNO[nombre]))
    return out


def empacar_cubeta(vol):
    cap = CAP_M3["BANDEJA"] * UTIL_CARTON
    n = math.ceil(vol / cap - 1e-12)
    return [_caja("BANDEJA", n, KG_EXTERNO["BANDEJA"])] if n > 0 else []


def empacar_suelto(tipo, vol):
    if not (vol > 1e-12):
        return []
    if tipo == "CUBETA":
        return empacar_cubeta(vol)
    if tipo in ("REFR", "VREF", "CREF"):
        return empacar_frio(vol)
    return empacar_ambiente(vol)


def _sumar_cajas(items):
    mapa = {}
    for item in items:
        prev = mapa.setdefault(item["nombre"], {"nombre": item["nombre"], "cantidad": 0, "kg": 0.0, "sin_kilo": 0})
        prev["cantidad"] += item["cantidad"]
        if item["kg"] is None:
            prev["sin_kilo"] += item["cantidad"]
        else:
            prev["kg"] += item["kg"] * item["cantidad"]
    return list(mapa.values())


def simular_lineas(lineas):
    avisos = []
    grupos = {}
    for ln in lineas or []:
        qty = math.floor(float(ln.get("qty") or 0))
        sku = str(ln.get("sku") or "").strip()
        if not sku or qty <= 0:
            continue
        tipo = tipo_de_linea(ln.get("prtfam"), ln.get("lngdsc"), ln.get("rut") or "")
        grupo_id = grupo_de(tipo, ln.get("prtfam"))
        g = grupos.setdefault(grupo_id, {"tipo": tipo, "vol": 0.0, "cajas": [], "un_sin_medida": 0})
        factor = float(ln.get("factor") or 0)
        masters = math.floor(qty / factor) if factor > 1 else 0
        sueltas = qty - masters * (factor if factor > 1 else 0)
        if masters > 0:
            cm3 = float(ln.get("cj_cm3") or 0)
            if cm3 > 0:
                g["cajas"].append(_caja("Master", masters, cm3 / DIVISOR))
            else:
                g["cajas"].append(_caja("Master", masters, None))
                avisos.append(f"{sku}: {masters} master sin medida de caja. Entran al conteo y no al kilo.")
        un_vol = 0 if ln.get("un_vol") is None else float(ln.get("un_vol") or 0)
        if sueltas > 0:
            if un_vol > 0:
                g["vol"] += sueltas * un_vol
            else:
                g["un_sin_medida"] += sueltas
                avisos.append(f"{sku}: {sueltas} unidades sueltas sin medida usable. No entran al volumen.")

    por_factura = {fid: [] for fid, _nombre in FACTURAS}
    for g in grupos.values():
        cajas = [*g["cajas"], *empacar_suelto(g["tipo"], g["vol"])]
        if g["un_sin_medida"] > 0 and not (g["vol"] > 1e-12) and not cajas:
            cajas.append(_caja("Sin medida", 1, None))
        por_factura[factura_de(g["tipo"])].extend(cajas)

    facturas = []
    for fid, nombre in FACTURAS:
        contenedores = _sumar_cajas(por_factura[fid])
        if not contenedores:
            continue
        bultos = sum(c["cantidad"] for c in contenedores)
        kg_exacto = sum(c["kg"] for c in contenedores)
        facturas.append({
            "id": fid,
            "nombre": nombre,
            "bultos": bultos,
            "contenedores": [
                {
                    "nombre": c["nombre"],
                    "cantidad": c["cantidad"],
                    "kg": None if c["sin_kilo"] else round_mil(c["kg"]),
                }
                for c in contenedores
            ],
            "kg_exacto": round_mil(kg_exacto),
        })
    return {"facturas": facturas, "avisos": list(dict.fromkeys(avisos))}


def round_mil(numero):
    return js_round(float(numero) * 1000) / 1000
