#!/usr/bin/env python3
import importlib.util
import pathlib
import unittest


ARQUIVO = pathlib.Path(__file__).with_name("ler-capa.py")
SPEC = importlib.util.spec_from_file_location("ler_capa", ARQUIVO)
lercapa = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lercapa)


class LerCapaVisualTest(unittest.TestCase):
    def test_titulo_visual_usa_maior_bloco_plausivel_e_junta_linhas(self):
        blocos = [
            {"texto": "DO AUTOR CAMPEÃO DE VENDAS MYLES MUNROE",
             "left": 80, "top": 80, "right": 620, "bottom": 130,
             "width": 540, "height": 50, "area": 27000,
             "altura_media": 28},
            {"texto": "Tornando-se um",
             "left": 120, "top": 210, "right": 520, "bottom": 265,
             "width": 400, "height": 55, "area": 22000,
             "altura_media": 42},
            {"texto": "LÍDER",
             "left": 95, "top": 270, "right": 645, "bottom": 385,
             "width": 550, "height": 115, "area": 63250,
             "altura_media": 96},
            {"texto": "TODOS PODEM CONSEGUIR",
             "left": 135, "top": 390, "right": 610, "bottom": 445,
             "width": 475, "height": 55, "area": 26125,
             "altura_media": 40},
            {"texto": "MYLES MUNROE",
             "left": 160, "top": 720, "right": 560, "bottom": 780,
             "width": 400, "height": 60, "area": 24000,
             "altura_media": 44},
        ]

        visual = lercapa.titulo_visual_por_geometria_blocos(
            blocos, autor_conhecido="Myles Munroe")

        self.assertEqual(
            "Tornando-se um LÍDER TODOS PODEM CONSEGUIR",
            visual["titulo"])
        self.assertNotIn("CAMPEÃO DE VENDAS", visual["titulo"])

    def test_titulo_visual_nao_usa_autor_grande_como_titulo(self):
        blocos = [
            {"texto": "HERMAN BAVINCK",
             "left": 80, "top": 100, "right": 650, "bottom": 210,
             "width": 570, "height": 110, "area": 62700,
             "altura_media": 90},
            {"texto": "DOGMÁTICA REFORMADA",
             "left": 130, "top": 310, "right": 620, "bottom": 390,
             "width": 490, "height": 80, "area": 39200,
             "altura_media": 62},
        ]

        visual = lercapa.titulo_visual_por_geometria_blocos(
            blocos, autor_conhecido="Herman Bavinck")

        self.assertEqual("DOGMÁTICA REFORMADA", visual["titulo"])


    def test_blocos_da_capa_cascata_tres_niveis(self):
        original_vision = lercapa._ocr_vision_blocos
        original_rapid = lercapa._ocr_rapidocr_blocos
        original_tess = lercapa._ocr_tesseract_blocos
        try:
            # Nível 1: Vision tem blocos -> usa Vision
            lercapa._ocr_vision_blocos = lambda img: [{"texto": "VISION", "area": 100}]
            lercapa._ocr_rapidocr_blocos = lambda img: [{"texto": "RAPID", "area": 80}]
            lercapa._ocr_tesseract_blocos = lambda img: [{"texto": "TESS", "area": 50}]
            self.assertEqual("VISION", lercapa.blocos_da_capa("dummy.jpg")[0]["texto"])

            # Nível 2: Vision falha ou ausente -> assume RapidOCR
            lercapa._ocr_vision_blocos = lambda img: []
            lercapa._ocr_rapidocr_blocos = lambda img: [{"texto": "RAPID", "area": 80}]
            lercapa._ocr_tesseract_blocos = lambda img: [{"texto": "TESS", "area": 50}]
            self.assertEqual("RAPID", lercapa.blocos_da_capa("dummy.jpg")[0]["texto"])

            # Nível 3: Vision e RapidOCR ausentes -> fallback universal Tesseract
            lercapa._ocr_vision_blocos = lambda img: []
            lercapa._ocr_rapidocr_blocos = lambda img: []
            lercapa._ocr_tesseract_blocos = lambda img: [{"texto": "TESS", "area": 50}]
            self.assertEqual("TESS", lercapa.blocos_da_capa("dummy.jpg")[0]["texto"])
        finally:
            lercapa._ocr_vision_blocos = original_vision
            lercapa._ocr_rapidocr_blocos = original_rapid
            lercapa._ocr_tesseract_blocos = original_tess

    def test_texto_da_capa_cascata_tres_niveis(self):
        original_vision = lercapa._ocr_vision
        original_rapid = lercapa._ocr_rapidocr
        original_tess = lercapa._ocr_tesseract
        try:
            # Nível 1: Vision
            lercapa._ocr_vision = lambda img: ["LINHA VISION"]
            lercapa._ocr_rapidocr = lambda img: ["LINHA RAPID"]
            lercapa._ocr_tesseract = lambda img: ["LINHA TESS"]
            self.assertEqual(["LINHA VISION"], lercapa.texto_da_capa("dummy.jpg"))

            # Nível 2: RapidOCR
            lercapa._ocr_vision = lambda img: None
            lercapa._ocr_rapidocr = lambda img: ["LINHA RAPID"]
            lercapa._ocr_tesseract = lambda img: ["LINHA TESS"]
            self.assertEqual(["LINHA RAPID"], lercapa.texto_da_capa("dummy.jpg"))

            # Nível 3: Tesseract
            lercapa._ocr_vision = lambda img: None
            lercapa._ocr_rapidocr = lambda img: None
            lercapa._ocr_tesseract = lambda img: ["LINHA TESS"]
            self.assertEqual(["LINHA TESS"], lercapa.texto_da_capa("dummy.jpg"))
        finally:
            lercapa._ocr_vision = original_vision
            lercapa._ocr_rapidocr = original_rapid
            lercapa._ocr_tesseract = original_tess


if __name__ == "__main__":
    unittest.main()
