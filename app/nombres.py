"""Normalización de comuna, región y courier. Misma clave que el tarifario del CCL."""
import math
import unicodedata

COURIERS = ("Newtrans", "Transfarma", "Cargoex", "Chibra")
RUTS_CUBETA = ("767005822", "967701009")
REGIONES_EXTREMAS = ("arica", "tarapaca", "antofagasta", "aysen", "aisen", "magallanes")


def sin_tildes(valor):
    texto = unicodedata.normalize("NFD", str(valor or ""))
    return "".join(c for c in texto if unicodedata.category(c) != "Mn")


def norm_nombre(valor):
    texto = sin_tildes(valor).upper().replace("-", " ")
    texto = " ".join(texto.split())
    return (
        texto.replace("POZO AL MONTE", "POZO ALMONTE")
        .replace("TAL TAL", "TALTAL")
        .replace("CON CON", "CONCON")
        .replace("SAN FRANCISCO DE MOSTAZAL", "SAN FRANCISCO MOSTAZAL")
    )


def js_round(numero):
    n = float(numero)
    if not math.isfinite(n):
        return None
    if n >= 0:
        return int(math.floor(n + 0.5))
    return int(math.ceil(n - 0.5))


def redondear_kg(kg):
    n = float(kg)
    if not math.isfinite(n) or n <= 0:
        return n
    return js_round(n * 10) / 10


def region_extrema(region):
    clave = sin_tildes(region).lower()
    return any(marca in clave for marca in REGIONES_EXTREMAS)


def canon_courier(valor):
    n = str(valor or "").strip().lower()
    for courier in COURIERS:
        if courier.lower() == n:
            return courier
    return ""


def courier_nt(ruta):
    """Ruta por defecto del cliente. Courier N es Newtrans y Courier T es Transfarma."""
    r = sin_tildes(ruta).upper().replace(" ", "").replace("_", "-")
    if r in ("N", "COURIER-N"):
        return "Newtrans"
    if r in ("T", "COURIER-T"):
        return "Transfarma"
    return ""


def es_retail(valor):
    k = sin_tildes(valor).lower().replace(".", " ").replace("_", " ")
    k = " ".join(k.split())
    if not k:
        return False
    return k == "retail" or k.startswith("retail ") or "dispensing model" in k


def es_cubeta_azul(rut):
    compacto = "".join(ch for ch in str(rut or "").upper() if ch.isalnum())
    digitos = "".join(ch for ch in str(rut or "").upper() if ch.isdigit() or ch == "K")
    for candidato in (compacto, digitos):
        if not candidato:
            continue
        for conocido in RUTS_CUBETA:
            if candidato == conocido or candidato.endswith(conocido):
                return True
    return False
