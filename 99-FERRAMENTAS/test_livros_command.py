#!/usr/bin/env python3
import pathlib
import unittest


COMANDO = pathlib.Path(__file__).with_name("LIVROS.command")


class ConferenciaAutomaticaDasRevisoesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.texto = COMANDO.read_text(encoding="utf-8")

    def test_item_manual_nao_aparece_mais_no_menu(self):
        self.assertNotIn(
            "15)  Conferir se as revisões manuais estão valendo", self.texto)
        self.assertIn(
            "Integridade das revisões: conferência automática", self.texto)

    def test_ciclos_e_reavaliacao_conferem_ao_final(self):
        self.assertGreaterEqual(
            self.texto.count("conferir_revisoes_automaticamente"), 7)

    def test_todos_os_envios_bloqueiam_quando_a_conferencia_falha(self):
        trava = "if ! conferir_revisoes_automaticamente; then"
        self.assertEqual(3, self.texto.count(trava))
        bloco = (trava + '\n'
                 '           echo ""\n'
                 '           read -n 1 -s -r -p "   Tecla para voltar ao menu..."')
        self.assertEqual(3, self.texto.count(bloco))


if __name__ == "__main__":
    unittest.main()
