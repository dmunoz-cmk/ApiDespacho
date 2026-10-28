"""Lectura de WMS, cliente SAP y tarifario. Solo consultas."""
import pyodbc

from app.config import cargar_entorno, entorno

cargar_entorno()


class ErrorDatos(Exception):
    pass


def _driver():
    preferidos = (
        "ODBC Driver 18 for SQL Server",
        "ODBC Driver 17 for SQL Server",
        "SQL Server",
    )
    instalados = set(pyodbc.drivers())
    for nombre in preferidos:
        if nombre in instalados:
            return nombre
    raise ErrorDatos("No hay un controlador ODBC de SQL Server instalado en este PC.")


def _conectar(host, port, database, user, password):
    driver = _driver()
    ultimo = None
    for extra in ("Encrypt=yes;TrustServerCertificate=yes;", "Encrypt=no;"):
        cadena = (
            f"DRIVER={{{driver}}};SERVER={host},{port};DATABASE={database};"
            f"UID={user};PWD={password};{extra}Connection Timeout=15;"
        )
        try:
            return pyodbc.connect(cadena)
        except pyodbc.Error as exc:
            ultimo = exc
    raise ErrorDatos(f"No se pudo conectar a SQL Server ({host}).") from ultimo


def conectar_wms():
    return _conectar(
        entorno("BLUEYONDER_IP"),
        entorno("BLUEYONDER_PORT", "1433"),
        entorno("BLUEYONDER_DATABASE"),
        entorno("BLUEYONDER_USER"),
        entorno("BLUEYONDER_PASSWORD"),
    )


def conectar_ccl():
    return _conectar(
        entorno("CCL_MSSQL_SERVER"),
        entorno("CCL_MSSQL_PORT", "1433"),
        entorno("CCL_MSSQL_DATABASE"),
        entorno("CCL_MSSQL_USER"),
        entorno("CCL_MSSQL_PASSWORD"),
    )


def _filas(conexion, sql, params=()):
    cur = conexion.cursor()
    cur.execute(sql, params)
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def leer_matriz():
    with conectar_ccl() as con:
        return _filas(
            con,
            """
            SELECT [Courier], [Via], [Comuna], [Region], [Kg_Desde], [Kg_Hasta],
                   [Tipo_Precio], [Precio_Neto]
            FROM [TRP].[matriz_costos]
            """,
        )


def leer_correcciones():
    with conectar_ccl() as con:
        return _filas(
            con,
            """
            SELECT [Localidad], [Comuna_Corregida]
            FROM [TRP].[Matriz_Comuna_Correccion]
            """,
        )


def _holding(tabla):
    base = entorno("HOLDING_DATABASE", "dw_holding") or "dw_holding"
    if not base.replace("_", "").isalnum():
        raise ErrorDatos("HOLDING_DATABASE no es un nombre válido.")
    return f"[{base}].[CMK].[{tabla}]"


def leer_cliente(cardcode):
    codigo = str(cardcode or "").strip()
    with conectar_ccl() as con:
        clientes = _filas(
            con,
            f"""
            SELECT TOP 1
                LTRIM(RTRIM(CAST(CardCode AS NVARCHAR(50)))) AS cardcode,
                LTRIM(RTRIM(CAST(ISNULL(CardName, '') AS NVARCHAR(200)))) AS nombre,
                LTRIM(RTRIM(CAST(ISNULL(RUT, '') AS NVARCHAR(50)))) AS rut,
                LTRIM(RTRIM(CAST(ISNULL(NOMBRE_ESTRATIFICACION, '') AS NVARCHAR(80)))) AS estratificacion,
                LTRIM(RTRIM(CAST(ISNULL(Comuna_de_Despacho, '') AS NVARCHAR(100)))) AS comuna_despacho,
                LTRIM(RTRIM(CAST(ISNULL(Direccion_de_Despacho, '') AS NVARCHAR(300)))) AS direccion_despacho
            FROM {_holding('clientes')}
            WHERE LTRIM(RTRIM(CAST(CardCode AS NVARCHAR(50)))) = ?
            """,
            (codigo,),
        )
        direcciones = _filas(
            con,
            f"""
            SELECT
                LTRIM(RTRIM(CAST(ISNULL(Calle, '') AS NVARCHAR(300)))) AS calle,
                LTRIM(RTRIM(CAST(ISNULL(Comuna, '') AS NVARCHAR(100)))) AS comuna,
                LTRIM(RTRIM(CAST(ISNULL(Nombre_Region, '') AS NVARCHAR(100)))) AS region,
                LTRIM(RTRIM(CAST(ISNULL(Ruta, '') AS NVARCHAR(100)))) AS ruta
            FROM {_holding('despacho_direcciones')}
            WHERE LTRIM(RTRIM(CAST(CardCode AS NVARCHAR(50)))) = ?
            """,
            (codigo,),
        )
    if not clientes:
        return None
    cliente = clientes[0]
    cliente["direcciones"] = direcciones
    return cliente


def leer_productos(skus):
    lista = []
    vistos = set()
    for sku in skus:
        texto = str(sku or "").strip()
        if texto and texto not in vistos:
            vistos.add(texto)
            lista.append(texto)
    if not lista:
        return {}
    marcas = ", ".join("?" for _ in lista)
    with conectar_wms() as con:
        maestro = _filas(
            con,
            f"""
            SELECT
                LTRIM(RTRIM(CAST(prtnum AS NVARCHAR(40)))) AS sku,
                LTRIM(RTRIM(CAST(prtfam AS NVARCHAR(40)))) AS prtfam,
                LTRIM(RTRIM(CAST(lngdsc AS NVARCHAR(200)))) AS lngdsc
            FROM dbo.v_maestro_productos
            WHERE wh_id_tmpl = '----'
              AND prt_client_id = 'CLINICAL MARKET'
              AND prtnum IN ({marcas})
            """,
            lista,
        )
        footprints = _filas(
            con,
            f"""
            SELECT
                LTRIM(RTRIM(CAST(prtnum AS NVARCHAR(40)))) AS sku,
                LTRIM(RTRIM(CAST(uomcod AS NVARCHAR(10)))) AS uomcod,
                LTRIM(RTRIM(CAST(ISNULL(ftpcod, '') AS NVARCHAR(40)))) AS ftpcod,
                len, wid, hgt, untqty
            FROM dbo.v_footprint
            WHERE wh_id = '----'
              AND uomcod IN ('UN', 'CJ')
              AND prtnum IN ({marcas})
            """,
            lista,
        )
    from app.carton import VOL_UN_MAX, sku_key

    mapa = {}
    for fila in maestro:
        clave = sku_key(fila["sku"])
        if not clave:
            continue
        prev = mapa.get(clave)
        fam = str(fila["prtfam"] or "").strip()
        prefiere_frio = fam.upper() == "REFRIGERAD" and str((prev or {}).get("prtfam") or "").upper() != "REFRIGERAD"
        if prev is None or prefiere_frio:
            mapa[clave] = {
                "sku": str(fila["sku"]).strip(),
                "prtfam": fam,
                "lngdsc": str(fila["lngdsc"] or "").strip(),
                "un_vol": None if prev is None else prev.get("un_vol"),
                "factor": 0 if prev is None else prev.get("factor") or 0,
                "cj_cm3": None if prev is None else prev.get("cj_cm3"),
            }
    por_sku = {}
    for fila in footprints:
        clave = sku_key(fila["sku"])
        if clave:
            por_sku.setdefault(clave, []).append(fila)
    for clave, filas in por_sku.items():
        uns = sorted(
            (f for f in filas if str(f["uomcod"]).upper() == "UN"),
            key=lambda f: str(f["ftpcod"]),
        )
        if not uns:
            continue
        un = uns[0]
        cjs = sorted(
            (
                f for f in filas
                if str(f["uomcod"]).upper() == "CJ" and str(f["ftpcod"]) == str(un["ftpcod"])
            ),
            key=lambda f: str(f["ftpcod"]),
        )
        cj = cjs[0] if cjs else None
        largo = float(un["len"] or 0)
        ancho = float(un["wid"] or 0)
        alto = float(un["hgt"] or 0)
        un_vol = None
        if largo > 0 and ancho > 0 and alto > 0:
            m3 = (largo * ancho * alto) / 1e6
            if 0 < m3 < VOL_UN_MAX:
                un_vol = m3
        cj_l = float(cj["len"] or 0) if cj else 0
        cj_w = float(cj["wid"] or 0) if cj else 0
        cj_h = float(cj["hgt"] or 0) if cj else 0
        prev = mapa.get(clave) or {"sku": str(un["sku"]).strip(), "prtfam": "", "lngdsc": ""}
        mapa[clave] = {
            **prev,
            "un_vol": un_vol,
            "factor": float(cj["untqty"] or 0) if cj else 0,
            "cj_cm3": cj_l * cj_w * cj_h if cj_l > 0 and cj_w > 0 and cj_h > 0 else None,
        }
    return mapa
