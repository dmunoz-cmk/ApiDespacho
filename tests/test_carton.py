import unittest

from app.carton import KG_EXTERNO, simular_lineas
from app.cotizar import PedidoInvalido, cotizar_factura, resolver_destino, via_de_factura
from app.nombres import es_retail, js_round
from app.tarifas import armar_correcciones, armar_tarifas, cotizar_tramo


def linea(**partial):
    base = {
        "sku": "1",
        "qty": 1,
        "prtfam": "VETERINARI",
        "lngdsc": "Producto",
        "un_vol": 0.001,
        "factor": 0,
        "cj_cm3": None,
        "rut": "",
    }
    base.update(partial)
    return base


class CartonTest(unittest.TestCase):
    def test_mezz_en_una_factura(self):
        r = simular_lineas([
            linea(sku="A", prtfam="VETERINARI"),
            linea(sku="B", prtfam="COSMETICO"),
        ])
        self.assertEqual(len(r["facturas"]), 1)
        self.assertEqual(r["facturas"][0]["id"], "MEZZ")
        self.assertEqual(r["facturas"][0]["bultos"], 2)
        esperado = js_round(KG_EXTERNO["CAJA CHICA"] * 2 * 1000) / 1000
        self.assertEqual(r["facturas"][0]["kg_exacto"], esperado)

    def test_no_junta_farma_con_mezz(self):
        r = simular_lineas([
            linea(sku="A", prtfam="VETERINARI"),
            linea(sku="B", prtfam="MEDI APROB"),
        ])
        self.assertEqual([f["id"] for f in r["facturas"]], ["MEZZ", "FARMA"])

    def test_controlado_refrigerado_en_nevera(self):
        r = simular_lineas([
            linea(sku="C", prtfam="CONTROLADO", lngdsc="ZOLPIDEM (REF)"),
        ])
        self.assertEqual(r["facturas"][0]["id"], "CREF")
        self.assertEqual(r["facturas"][0]["contenedores"][0]["nombre"], "NEVERA 12")
        self.assertEqual(r["facturas"][0]["kg_exacto"], js_round(KG_EXTERNO["NEVERA 12"] * 1000) / 1000)

    def test_master_y_suelto(self):
        r = simular_lineas([
            linea(sku="M", prtfam="NUTRICIONA", qty=25, factor=10, cj_cm3=8000, un_vol=0.001),
        ])
        nombres = [f"{c['cantidad']} {c['nombre']}" for c in r["facturas"][0]["contenedores"]]
        self.assertEqual(nombres, ["2 Master", "1 CAJA MEDIA"])
        esperado = js_round(((8000 / 4000) * 2 + KG_EXTERNO["CAJA MEDIA"]) * 1000) / 1000
        self.assertEqual(r["facturas"][0]["kg_exacto"], esperado)

    def test_cubeta_azul(self):
        r = simular_lineas([
            linea(sku="F", prtfam="ONCOLOGICO", rut="76.700.582-2"),
        ])
        self.assertEqual(r["facturas"][0]["id"], "FARMA")
        self.assertEqual(r["facturas"][0]["contenedores"][0]["nombre"], "BANDEJA")


class ViaTest(unittest.TestCase):
    def test_refrigerado_extremo_es_aereo(self):
        self.assertEqual(via_de_factura("REF", "Arica y Parinacota"), "Aerea")
        self.assertEqual(via_de_factura("CREF", "Magallanes"), "Aerea")

    def test_ambiente_y_refrigerado_central_son_terrestres(self):
        self.assertEqual(via_de_factura("FARMA", "Arica y Parinacota"), "Terrestre")
        self.assertEqual(via_de_factura("REF", "Biobío"), "Terrestre")
        self.assertEqual(via_de_factura("MEZZ", "Metropolitana"), "Terrestre")

    def test_isla_de_pascua_siempre_aereo(self):
        self.assertEqual(via_de_factura("FARMA", "Valparaíso", "ISLA DE PASCUA"), "Aerea")
        self.assertEqual(via_de_factura("MEZZ", "Valparaíso", "Isla De Pascua"), "Aerea")
        self.assertEqual(via_de_factura("FARMA", "Valparaíso", "Valparaíso"), "Terrestre")


def tramo(courier, via, comuna, precio):
    return {"Courier": courier, "Via": via, "Comuna": comuna, "Region": "R",
            "Kg_Desde": 0, "Kg_Hasta": 10, "Tipo_Precio": "fijo", "Precio_Neto": precio}


class TarifaTest(unittest.TestCase):
    def test_comuna_corregida(self):
        tarifas = armar_tarifas([tramo("Newtrans", "Terrestre", "Tiltil", 5000)])
        correcciones = armar_correcciones([{"Localidad": "TIL TIL", "Comuna_Corregida": "Tiltil"}])
        self.assertEqual(cotizar_tramo(tarifas, "TIL TIL", "Newtrans", "Terrestre", 1.0), (1.0, None))
        self.assertEqual(
            cotizar_tramo(tarifas, "TIL TIL", "Newtrans", "Terrestre", 1.0, correcciones), (1.0, 5000)
        )

    def test_respaldo_en_el_otro_courier(self):
        tarifas = armar_tarifas([tramo("Transfarma", "Terrestre", "Chillan Viejo", 4000)])
        self.assertEqual(
            cotizar_factura(tarifas, {}, "CHILLAN VIEJO", "Newtrans", "Terrestre", 1.0),
            (1.0, 4000, "Transfarma", True),
        )

    def test_sin_respaldo_si_el_propio_tiene_tramo(self):
        tarifas = armar_tarifas([
            tramo("Newtrans", "Terrestre", "Talca", 3000),
            tramo("Transfarma", "Terrestre", "Talca", 2000),
        ])
        self.assertEqual(
            cotizar_factura(tarifas, {}, "Talca", "Newtrans", "Terrestre", 1.0),
            (1.0, 3000, "Newtrans", False),
        )

    def test_sin_tramo_en_ninguno(self):
        tarifas = armar_tarifas([tramo("Transfarma", "Terrestre", "Talca", 2000)])
        self.assertEqual(
            cotizar_factura(tarifas, {}, "Mejillones", "Transfarma", "Aerea", 1.0),
            (1.0, None, "Transfarma", False),
        )


def ficha(**partial):
    base = {
        "estratificacion": "RETAIL",
        "comuna_despacho": "Arica",
        "direccion_despacho": "Calle 1",
        "direcciones": [
            {"calle": "Calle 1", "comuna": "Arica", "region": "Arica y Parinacota", "ruta": "COURIER-N"},
            {"calle": "Otra", "comuna": "Santiago", "region": "Metropolitana", "ruta": "RUTA-A1"},
        ],
    }
    base.update(partial)
    return base


class DestinoTest(unittest.TestCase):
    def test_retail_usa_la_comuna_y_courier_n(self):
        d = resolver_destino(ficha())
        self.assertEqual(d["comuna"], "Arica")
        self.assertEqual(d["courier"], "Newtrans")
        self.assertEqual(d["ruta"], "COURIER-N")
        self.assertTrue(es_retail("RETAIL"))
        self.assertFalse(es_retail("CLINICAS y HOSPITALES"))

    def test_courier_t_es_transfarma(self):
        d = resolver_destino(ficha(direcciones=[
            {"calle": "Calle 1", "comuna": "Arica", "region": "Arica y Parinacota", "ruta": "COURIER-T"},
        ]))
        self.assertEqual(d["courier"], "Transfarma")

    def test_rechaza_otro_canal(self):
        with self.assertRaises(PedidoInvalido):
            resolver_destino(ficha(estratificacion="CENABAST"))

    def test_rechaza_ruta_que_no_es_courier(self):
        with self.assertRaises(PedidoInvalido):
            resolver_destino(ficha(direcciones=[
                {"calle": "Calle 1", "comuna": "Arica", "region": "Arica y Parinacota", "ruta": "RUTA-A1"},
            ]))


if __name__ == "__main__":
    unittest.main()
