import unittest

from app.tarifas import aplicar_reglas, armar_tarifas, armar_tarifas_trp, cotizar_tramo


def fac(fid="FARMA", bultos=1, kg=1.2, contenedores=None):
    return {
        "id": fid,
        "bultos": bultos,
        "contenedores": contenedores or [{"nombre": "CAJA CHICA", "cantidad": 1, "kg": kg}],
    }


def stack_basico():
    return {
        "fecha": "2026-10-31",
        "coberturas": [
            {"Courier": "Newtrans", "Destino": "ANTOFAGASTA", "Hub": "ANTOFAGASTA", "Zona": None, "Es_Hub": 1, "Comuna": "Antofagasta"},
            {"Courier": "Newtrans", "Destino": "TOCOPILLA", "Hub": "ANTOFAGASTA", "Zona": None, "Es_Hub": 0, "Comuna": "Tocopilla"},
            {"Courier": "Transfarma", "Destino": "SANTIAGO", "Hub": "SANTIAGO", "Zona": "Z1", "Es_Hub": 1, "Comuna": "Santiago"},
        ],
        "tarifarios": {
            ("Newtrans", "Terrestre"): {
                "id": 5,
                "precios": [
                    {"Hub": "ANTOFAGASTA", "Zona": None, "Kg_desde": 0, "Kg_hasta": 2, "Tipo_precio": "plano", "Precio": 4000},
                ],
                "reglas": [
                    {"Clave": "ramal_pct", "Valor": 80},
                    {"Clave": "combustible_pct", "Valor": 9},
                    {"Clave": "cedible", "Valor": 590},
                    {"Clave": "controlado", "Valor": 11270},
                    {"Clave": "refrigerado", "Valor": 11270},
                    {"Clave": "cryo_retorno", "Valor": 0},
                ],
            },
            ("Transfarma", "Terrestre"): {
                "id": 3,
                "precios": [
                    {"Hub": "SANTIAGO", "Zona": "Z1", "Kg_desde": 0, "Kg_hasta": 2, "Tipo_precio": "plano", "Precio": 3000},
                ],
                "reglas": [
                    {"Clave": "cedible", "Valor": 500},
                    {"Clave": "cedible_controlado", "Valor": 1500},
                    {"Clave": "cryo_retorno_factor", "Valor": 0.7},
                ],
            },
        },
    }


class ReglasTest(unittest.TestCase):
    def setUp(self):
        self.t = armar_tarifas_trp(stack_basico())

    def test_nt_farma_sin_descuento_de_tramo(self):
        kg, flete = cotizar_tramo(self.t, "ANTOFAGASTA", "Newtrans", "Terrestre", 1.2)
        self.assertEqual(flete, 4000)
        r = aplicar_reglas(self.t, {}, fac("FARMA"), "ANTOFAGASTA", "Newtrans", "Terrestre", kg, flete)
        self.assertEqual(r["flete"], 4000)
        self.assertEqual(r["combustible"], 360)
        self.assertEqual(r["cedible"], 590)
        self.assertEqual(r["extras_ida"], 0)
        self.assertEqual(r["cryo_retorno"], 0)
        self.assertEqual(r["costo"], 4950)

    def test_nt_ramal_en_celda_sin_sumar_otra_vez(self):
        kg, flete = cotizar_tramo(self.t, "TOCOPILLA", "Newtrans", "Terrestre", 1.2)
        self.assertEqual(flete, 7200)

    def test_nt_refrigerado_ida_y_cryo_cero(self):
        kg, flete = cotizar_tramo(self.t, "ANTOFAGASTA", "Newtrans", "Terrestre", 6.1)
        nevera = fac("REF", bultos=1, kg=6.1, contenedores=[{"nombre": "NEVERA 12", "cantidad": 1, "kg": 6.1}])
        r = aplicar_reglas(self.t, {}, nevera, "ANTOFAGASTA", "Newtrans", "Terrestre", kg, flete)
        self.assertEqual(r["extras_ida"], 11270)
        self.assertEqual(r["cryo_retorno"], 0)
        self.assertEqual(r["cedible"], 590)

    def test_nt_controlado_refrigerado_suma_ambos_de_ida(self):
        kg, flete = cotizar_tramo(self.t, "ANTOFAGASTA", "Newtrans", "Terrestre", 6.1)
        r = aplicar_reglas(self.t, {}, fac("CREF", bultos=2), "ANTOFAGASTA", "Newtrans", "Terrestre", kg, flete)
        self.assertEqual(r["extras_ida"], 11270 * 4)

    def test_tf_controlado_usa_cedible_1500(self):
        kg, flete = cotizar_tramo(self.t, "SANTIAGO", "Transfarma", "Terrestre", 1.2)
        r = aplicar_reglas(self.t, {}, fac("CONTROLADO"), "SANTIAGO", "Transfarma", "Terrestre", kg, flete)
        self.assertEqual(r["cedible"], 1500)
        self.assertEqual(r["extras_ida"], 0)
        self.assertEqual(r["costo"], 3000 + 1500)

    def test_tf_cryo_es_70_por_ciento_terrestre(self):
        kg, flete = cotizar_tramo(self.t, "SANTIAGO", "Transfarma", "Terrestre", 1.2)
        nevera = fac("REF", kg=1.2, contenedores=[{"nombre": "NEVERA 12", "cantidad": 1, "kg": 1.2}])
        r = aplicar_reglas(self.t, {}, nevera, "SANTIAGO", "Transfarma", "Terrestre", kg, flete)
        self.assertEqual(r["cedible"], 500)
        self.assertEqual(r["cryo_retorno"], 2100)
        self.assertEqual(r["extras_ida"], 0)
        self.assertEqual(r["costo"], 3000 + 500 + 2100)

    def test_prueba_matriz_sigue_cotizando_flete(self):
        t = armar_tarifas([{
            "Courier": "Newtrans", "Via": "Terrestre", "Comuna": "Talca", "Region": "Maule",
            "Kg_Desde": 0, "Kg_Hasta": 10, "Tipo_Precio": "fijo", "Precio_Neto": 3000,
        }])
        self.assertEqual(cotizar_tramo(t, "Talca", "Newtrans", "Terrestre", 1.0), (1.0, 3000))


if __name__ == "__main__":
    unittest.main()
