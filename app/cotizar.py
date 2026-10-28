"""Arma el costo de despacho de una orden para SAP."""
from app.carton import REFRIGERADAS, simular_lineas, sku_key
from app.datos import ErrorDatos, leer_cliente, leer_correcciones, leer_matriz, leer_productos
from app.nombres import courier_nt, es_isla_de_pascua, es_retail, norm_nombre, region_extrema
from app.tarifas import cargar_correcciones, cargar_tarifas, cotizar_tramo, region_de

CRITERIO = "retail-2026-10"
RESPALDO = {"Newtrans": "Transfarma", "Transfarma": "Newtrans"}


class PedidoInvalido(Exception):
    def __init__(self, mensaje, extra=None):
        super().__init__(mensaje)
        self.extra = extra or {}


def via_de_factura(factura_id, region, comuna=""):
    if es_isla_de_pascua(comuna):
        return "Aerea"
    if factura_id in REFRIGERADAS and region_extrema(region):
        return "Aerea"
    return "Terrestre"


def cotizar_factura(tarifas, correcciones, comuna, courier, via, kg):
    """Usa el tarifario del courier del cliente; si no tiene tramo, el del otro courier."""
    kg_ok, precio = cotizar_tramo(tarifas, comuna, courier, via, kg, correcciones)
    if precio is not None:
        return kg_ok, precio, courier, False
    respaldo = RESPALDO.get(courier)
    if respaldo:
        kg_r, precio_r = cotizar_tramo(tarifas, comuna, respaldo, via, kg, correcciones)
        if precio_r is not None:
            return kg_r, precio_r, respaldo, True
    return kg_ok, None, courier, False


def resolver_destino(cliente):
    """Comuna, región, ruta y courier salen de la ficha del cliente. No se piden en el input."""
    estrat = str(cliente.get("estratificacion") or "").strip()
    if not es_retail(estrat):
        raise PedidoInvalido(
            f"El cliente es {estrat or 'sin estratificación'}. Esta API calcula solo Retail."
        )
    comuna = str(cliente.get("comuna_despacho") or "").strip()
    if not comuna:
        raise PedidoInvalido("El cliente Retail no tiene comuna de despacho.")
    calle = str(cliente.get("direccion_despacho") or "").strip()
    misma_comuna = [
        d for d in (cliente.get("direcciones") or [])
        if norm_nombre(d.get("comuna")) == norm_nombre(comuna)
    ]
    misma_calle = [
        d for d in misma_comuna
        if calle and norm_nombre(d.get("calle")) == norm_nombre(calle)
    ]
    candidatas = misma_calle or misma_comuna
    if not candidatas:
        raise PedidoInvalido("La comuna de despacho del cliente no está en sus direcciones.")
    por_courier = {}
    for d in candidatas:
        courier = courier_nt(d.get("ruta"))
        if courier and courier not in por_courier:
            por_courier[courier] = d
    if len(por_courier) > 1:
        raise PedidoInvalido(
            "La dirección de despacho tiene Courier N y Courier T. No se puede elegir el tarifario."
        )
    if len(por_courier) == 1:
        courier, direccion = next(iter(por_courier.items()))
        return {
            "comuna": comuna,
            "region": str(direccion.get("region") or "").strip(),
            "ruta": str(direccion.get("ruta") or "").strip(),
            "courier": courier,
        }
    rutas = sorted({str(d.get("ruta") or "").strip() or "(sin ruta)" for d in candidatas})
    raise PedidoInvalido(
        f"La ruta por defecto del cliente es {rutas[0] if len(rutas) == 1 else ', '.join(rutas)}. "
        "Esta API cotiza Courier N (Newtrans) y Courier T (Transfarma)."
    )


def cotizar(pedido):
    lineas = []
    for ln in pedido.get("lineas") or []:
        sku = str(ln.get("sku") or "").strip()
        try:
            cantidad = int(ln.get("cantidad"))
        except (TypeError, ValueError):
            cantidad = 0
        if sku and cantidad > 0:
            lineas.append({"sku": sku, "cantidad": cantidad})
    if not lineas:
        raise PedidoInvalido("Indique al menos un SKU con cantidad.")

    cliente_codigo = str(pedido.get("cliente") or "").strip()
    if not cliente_codigo:
        raise PedidoInvalido("Indique el CardCode del cliente.")
    try:
        cliente = leer_cliente(cliente_codigo)
    except ErrorDatos:
        raise
    if cliente is None:
        raise PedidoInvalido("El cliente no está en la maestra.")
    destino = resolver_destino(cliente)
    comuna = destino["comuna"]
    region = destino["region"]
    ruta = destino["ruta"]
    courier = destino["courier"]
    rut = cliente.get("rut") or ""

    try:
        meta = leer_productos([ln["sku"] for ln in lineas])
    except ErrorDatos:
        raise
    avisos = []
    resueltas = []
    for ln in lineas:
        m = meta.get(sku_key(ln["sku"]))
        if not m:
            avisos.append(f"{ln['sku']}: no está en el maestro de Clinical Market.")
            continue
        resueltas.append({**m, "qty": ln["cantidad"], "rut": rut})
    if not resueltas:
        raise PedidoInvalido("Ningún producto está en el maestro.")

    armado = simular_lineas(resueltas)
    avisos.extend(armado["avisos"])
    try:
        tarifas = cargar_tarifas(leer_matriz)
        correcciones = cargar_correcciones(leer_correcciones)
    except ErrorDatos:
        raise
    if not str(region or "").strip():
        region = region_de(tarifas, comuna, correcciones)

    facturas = []
    total = 0
    completas = 0
    for fac in armado["facturas"]:
        via = via_de_factura(fac["id"], region, comuna)
        kg, precio = (None, None)
        usado, respaldo = courier, False
        motivo = None
        if not comuna or not courier:
            motivo = "Falta la comuna o el courier de la ruta del cliente para buscar el tramo."
        elif not (fac["kg_exacto"] > 0):
            motivo = "Sin kilo volumétrico para buscar el tramo."
        else:
            kg, precio, usado, respaldo = cotizar_factura(
                tarifas, correcciones, comuna, courier, via, fac["kg_exacto"]
            )
            if precio is None:
                motivo = "No hay tramo para esta comuna y vía en Newtrans ni en Transfarma."
            elif respaldo:
                avisos.append(
                    f"{fac['nombre']}: {courier} no tiene tramo {via} para {comuna}. "
                    f"Se cotizó con el tarifario de {usado} como respaldo."
                )
        if precio is not None:
            total += precio
            completas += 1
        facturas.append({
            "factura": fac["nombre"],
            "courier": usado,
            "respaldo": respaldo,
            "via": via,
            "bultos": fac["bultos"],
            "kilos": kg,
            "kilos_exactos": fac["kg_exacto"],
            "costo": precio,
            "contenedores": fac["contenedores"],
            "motivo": motivo,
        })

    vias = {f["via"] for f in facturas}
    return {
        "criterio": CRITERIO,
        "cliente": cliente_codigo or None,
        "cliente_nombre": (cliente or {}).get("nombre") or None,
        "comuna": comuna or None,
        "region": region or None,
        "estratificacion": str(cliente.get("estratificacion") or "").strip() or None,
        "ruta": ruta or None,
        "courier": courier or None,
        "via": next(iter(vias)) if len(vias) == 1 else ("Mixta" if vias else None),
        "costo": total if completas else None,
        "costo_completo": completas == len(facturas) and completas > 0,
        "facturas": facturas,
        "avisos": avisos,
    }
