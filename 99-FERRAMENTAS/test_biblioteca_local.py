#!/usr/bin/env python3
import importlib.util
import contextlib
import base64
import hashlib
import io
import json
import os
import pathlib
import tempfile
import unittest
from unittest import mock


ARQUIVO = pathlib.Path(__file__).with_name("biblioteca-local.py")
SPEC = importlib.util.spec_from_file_location("biblioteca_local", ARQUIVO)
local = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(local)


def resultado_pronto(nome):
    return {
        "arquivo": nome, "situacao": "pronto para cadastro",
        "situacao_ocr": "OCR aprovado", "situacao_metadados": "pronto para cadastro",
        "titulo": "Livro de teste", "nmAutor0": "Autor, Teste",
        "conflitos": "", "pendencias": "", "capa": "",
        "_diagnostico_ocr": {"status": "OCR aprovado"},
        "_evidencias": {},
    }


class BibliotecaLocalTest(unittest.TestCase):
    def escrever_opf(self, caminho, titulo="Livro Alpha", autor="Ana Souza",
                     isbn="9788577790364"):
        caminho.write_text(f'''<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"
            xmlns:opf="http://www.idpf.org/2007/opf">
    <dc:title>{titulo}</dc:title>
    <dc:creator>{autor}</dc:creator>
    <dc:publisher>Editora Teste</dc:publisher>
    <dc:identifier opf:scheme="ISBN">{isbn}</dc:identifier>
    <dc:language>por</dc:language>
    <dc:date>2021-07-19T00:00:00+00:00</dc:date>
  </metadata>
</package>''', encoding="utf-8")

    def test_ler_opf_extrai_metadados_estruturados(self):
        with tempfile.TemporaryDirectory() as td:
            opf = pathlib.Path(td) / "Livro Alpha.opf"
            self.escrever_opf(opf)
            dados = local.ler_opf(opf)
            self.assertEqual("Livro Alpha", dados["campos"]["titulo"])
            self.assertEqual("Souza, Ana", dados["campos"]["nmAutor0"])
            self.assertEqual("9788577790364", dados["campos"]["isbn"])
            self.assertEqual("2021", dados["campos"]["data"])
            self.assertEqual("Português", dados["campos"]["nmLingua"])

    def test_ler_opf_separa_dois_autores_no_mesmo_creator(self):
        with tempfile.TemporaryDirectory() as td:
            opf = pathlib.Path(td) / "Serie.opf"
            self.escrever_opf(opf, autor="John Stott e Tim Chester")
            dados = local.ler_opf(opf)
            self.assertEqual("Stott, John", dados["campos"]["nmAutor0"])
            self.assertEqual(
                ["Stott, John", "Chester, Tim"],
                [a["nome"] for a in dados["campos"]["autores"]])

    def test_relatorio_mostra_formato_desconhecido_na_entrada(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = pathlib.Path(td) / "livros"
            c = local.inicializar(raiz)
            (c["entrada"] / "Livro.pdf").write_bytes(b"%PDF")
            (c["entrada"] / "Documento.docx").write_bytes(b"docx")
            (c["entrada"] / "Arquivo.xyz").write_bytes(b"???")

            saida = io.StringIO()
            with contextlib.redirect_stdout(saida):
                local.mostrar_status(raiz)

            texto = saida.getvalue()
            self.assertIn("aguardando na entrada", texto)
            self.assertIn("   3", texto)
            self.assertIn("formato não tratado na entrada", texto)
            self.assertIn("   1", texto)

    def test_entrada_com_varios_livros_associa_opf_somente_pelo_nome(self):
        with tempfile.TemporaryDirectory() as td:
            c = local.inicializar(pathlib.Path(td) / "livros")
            autor = c["entrada"] / "Autor"
            autor.mkdir()
            (autor / "Livro Alpha.pdf").write_bytes(b"%PDF-alpha")
            (autor / "Livro Beta.pdf").write_bytes(b"%PDF-beta")
            self.escrever_opf(autor / "Livro Alpha.opf")

            resumo = local.preparar_entrada_organizada(
                c, local.carregar_catalogo(c))

            self.assertEqual(2, resumo["importados"])
            self.assertTrue((c["entrada"] / "Livro Alpha.pdf").is_file())
            self.assertTrue((c["entrada"] / "Livro Beta.pdf").is_file())
            revisoes = json.loads((c["controle"] /
                                   "revisoes-manuais.json").read_text())
            alpha = revisoes["livros"]["Livro Alpha.pdf"]
            beta = revisoes["livros"]["Livro Beta.pdf"]
            self.assertEqual("Livro Alpha", alpha["campos"]["titulo"])
            self.assertEqual("", beta["campos"]["opf_origem"])
            self.assertFalse(beta["aprovado"])
            repeticao = local.preparar_entrada_organizada(
                c, local.carregar_catalogo(c))
            self.assertEqual(0, repeticao["importados"])

    def test_opf_com_epub_sem_pdf_e_convertido_para_entrada(self):
        with tempfile.TemporaryDirectory() as td:
            c = local.inicializar(pathlib.Path(td) / "livros")
            pasta = c["entrada"] / "Autor" / "Livro"
            pasta.mkdir(parents=True)
            opf = pasta / "Livro Alpha.opf"
            epub = pasta / "Livro Alpha.epub"
            self.escrever_opf(opf)
            epub.write_bytes(b"EPUB")
            conversor = pathlib.Path(td) / "ebook-convert"
            conversor.write_text("teste")

            def converter(comando, **_kwargs):
                pathlib.Path(comando[2]).write_bytes(b"%PDF-convertido")
                return mock.Mock(returncode=0, stderr="")

            with mock.patch.object(local, "EBOOK_CONVERT", conversor), \
                    mock.patch.object(local.subprocess, "run", side_effect=converter):
                resumo = local.preparar_entrada_organizada(
                    c, local.carregar_catalogo(c))

            self.assertEqual(1, resumo["convertidos"])
            self.assertEqual(1, resumo["importados"])
            self.assertTrue((c["entrada"] / "Livro Alpha.pdf").is_file())

    def test_epub_avulso_na_raiz_e_convertido_sem_opf(self):
        with tempfile.TemporaryDirectory() as td:
            c = local.inicializar(pathlib.Path(td) / "livros")
            epub = c["entrada"] / "Worship.epub"
            epub.write_bytes(b"EPUB-avulso")
            conversor = pathlib.Path(td) / "ebook-convert"
            conversor.write_text("teste")

            def converter(comando, **_kwargs):
                pathlib.Path(comando[2]).write_bytes(b"%PDF-convertido")
                return mock.Mock(returncode=0, stderr="", stdout="")

            with mock.patch.object(local, "EBOOK_CONVERT", conversor), \
                    mock.patch.object(local.subprocess, "run", side_effect=converter):
                resumo = local.preparar_entrada_organizada(
                    c, local.carregar_catalogo(c))

            self.assertEqual(1, resumo["convertidos"])
            self.assertEqual(1, resumo["importados"])
            self.assertTrue((c["entrada"] / "Worship.pdf").is_file())
            estado = json.loads((c["controle"] /
                                  "importacoes-organizadas.json").read_text())
            item = estado["itens"][str(epub.resolve())]
            self.assertTrue(item["convertido_de_epub"])
            self.assertEqual("Calibre (EPUB)", item["motor_conversao"])

    def test_docx_e_convertido_para_pdf_e_original_fica_vinculado(self):
        with tempfile.TemporaryDirectory() as td:
            c = local.inicializar(pathlib.Path(td) / "livros")
            pasta = c["entrada"] / "Autor" / "Documento"
            pasta.mkdir(parents=True)
            word = pasta / "Estudo.docx"
            word.write_bytes(b"PK-documento-word")

            def converter(_origem, destino):
                pathlib.Path(destino).write_bytes(b"%PDF-convertido")
                return {"ok": True, "motor": "LibreOffice", "erro": ""}

            with mock.patch.object(local, "converter_word_para_pdf",
                                   side_effect=converter) as conversor:
                resumo = local.preparar_entrada_organizada(
                    c, local.carregar_catalogo(c))
                repeticao = local.preparar_entrada_organizada(
                    c, local.carregar_catalogo(c))

            self.assertEqual(1, resumo["convertidos"])
            self.assertEqual(1, resumo["importados"])
            self.assertEqual(0, repeticao["convertidos"])
            conversor.assert_called_once()
            self.assertTrue((c["entrada"] / "Estudo.pdf").is_file())
            self.assertTrue(word.is_file())
            estado = json.loads((c["controle"] /
                                 "importacoes-organizadas.json").read_text())
            registro = estado["itens"][str(word.resolve())]
            self.assertTrue(registro["convertido_de_word"])
            self.assertEqual("LibreOffice", registro["motor_conversao"])
            revisoes = json.loads((c["controle"] /
                                   "revisoes-manuais.json").read_text())
            associados = revisoes["livros"]["Estudo.pdf"]["campos"][
                "arquivos_origem_importacao"]
            self.assertIn(str(word.resolve()), associados)

    def test_falha_na_conversao_word_preserva_original_e_pode_repetir(self):
        with tempfile.TemporaryDirectory() as td:
            c = local.inicializar(pathlib.Path(td) / "livros")
            word = c["entrada"] / "Legado.doc"
            word.write_bytes(b"documento legado")
            falha = {"ok": False, "motor": "", "erro": "conversor ausente"}
            with mock.patch.object(local, "converter_word_para_pdf",
                                   return_value=falha) as conversor:
                primeiro = local.preparar_entrada_organizada(
                    c, local.carregar_catalogo(c))
                segundo = local.preparar_entrada_organizada(
                    c, local.carregar_catalogo(c))
            self.assertEqual(1, primeiro["falhas"])
            self.assertEqual(1, segundo["falhas"])
            self.assertEqual(2, conversor.call_count)
            self.assertTrue(word.is_file())
            self.assertFalse((c["entrada"] / "Legado.pdf").exists())
            estado = json.loads((c["controle"] /
                                 "importacoes-organizadas.json").read_text())
            self.assertEqual("falha na conversão Word",
                             estado["itens"][str(word.resolve())]["estado"])

    def test_arquivo_temporario_do_word_nao_entra_na_fila(self):
        with tempfile.TemporaryDirectory() as td:
            c = local.inicializar(pathlib.Path(td) / "livros")
            temporario = c["entrada"] / "~$Documento.docx"
            temporario.write_bytes(b"bloqueio temporario do Word")
            with mock.patch.object(local, "converter_word_para_pdf") as conversor:
                resumo = local.preparar_entrada_organizada(
                    c, local.carregar_catalogo(c))
            self.assertEqual(0, resumo["encontrados"])
            conversor.assert_not_called()
            self.assertTrue(temporario.is_file())

    def test_conversor_word_prefere_libreoffice_e_tem_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            origem = pathlib.Path(td) / "Documento.docx"
            destino = pathlib.Path(td) / "Documento.pdf"
            origem.write_bytes(b"docx")
            soffice = pathlib.Path(td) / "soffice"
            soffice.write_bytes(b"executavel")
            with mock.patch.object(local, "localizar_soffice",
                                   return_value=soffice), \
                 mock.patch.object(local, "_converter_word_libreoffice",
                                   return_value=(True, "")) as libreoffice, \
                 mock.patch.object(local, "_converter_word_microsoft") as word:
                resultado = local.converter_word_para_pdf(origem, destino)
            self.assertTrue(resultado["ok"])
            self.assertEqual("LibreOffice", resultado["motor"])
            libreoffice.assert_called_once()
            word.assert_not_called()

    def test_conversor_word_nao_abre_word_sem_autorizacao_explicita(self):
        with tempfile.TemporaryDirectory() as td:
            origem = pathlib.Path(td) / "Documento.docx"
            destino = pathlib.Path(td) / "Documento.pdf"
            origem.write_bytes(b"docx")
            with mock.patch.object(local, "localizar_soffice",
                                   return_value=None), \
                 mock.patch.object(local, "MICROSOFT_WORD",
                                   pathlib.Path("/Applications/Microsoft Word.app")), \
                 mock.patch.object(local, "_converter_word_microsoft") as word, \
                 mock.patch.dict(os.environ, {}, clear=True):
                resultado = local.converter_word_para_pdf(origem, destino)
            self.assertFalse(resultado["ok"])
            self.assertIn("LibreOffice", resultado["erro"])
            word.assert_not_called()

    def test_conversor_word_grafico_exige_autorizacao_explicita(self):
        with tempfile.TemporaryDirectory() as td:
            origem = pathlib.Path(td) / "Documento.docx"
            destino = pathlib.Path(td) / "Documento.pdf"
            origem.write_bytes(b"docx")
            with mock.patch.object(local, "localizar_soffice",
                                   return_value=None), \
                 mock.patch.object(local, "MICROSOFT_WORD") as app_word, \
                 mock.patch.object(local.shutil, "which",
                                   return_value="/usr/bin/osascript"), \
                 mock.patch.object(local, "_converter_word_microsoft",
                                   return_value=(True, "")) as word, \
                 mock.patch.dict(os.environ,
                                 {"BIBLIO_PERMITIR_WORD": "sim"}, clear=True):
                app_word.is_dir.return_value = True
                resultado = local.converter_word_para_pdf(origem, destino)
            self.assertTrue(resultado["ok"])
            self.assertEqual("Microsoft Word", resultado["motor"])
            word.assert_called_once()

    def test_duplicidade_textual_quase_identica_e_confirmada(self):
        with tempfile.TemporaryDirectory() as td:
            c = local.inicializar(pathlib.Path(td) / "livros")
            base = ("lideranca cristã pessoas objetivo comunicar delegar " * 80)
            paginas_a = [base + " conclusao original"]
            paginas_b = [base + " conclusao revisada"]
            candidato = c["documentos"] / "primeiro.pdf"
            candidato.write_bytes(b"%PDF-candidato")
            assinatura = local.assinatura_textual(paginas_a)
            catalogo = {"livros": {"abc": {
                "arquivo": candidato.name,
                "caminho": local.relativo(c, candidato),
                "simhash_texto": assinatura["simhash"],
                "palavras_texto": assinatura["palavras"],
                "estado": "cadastrado", "id_remoto": 20561,
            }}}
            with mock.patch.object(local.prep, "paginas_pdftotext",
                                   return_value=paginas_a):
                atual, duplicado = local.localizar_duplicado_textual(
                    c, catalogo, paginas_b)
            self.assertTrue(atual["simhash"])
            self.assertEqual("primeiro.pdf", duplicado["arquivo"])
            self.assertGreaterEqual(duplicado["similaridade"], 0.94)
            self.assertEqual(20561, duplicado["id_remoto"])

    def test_duplicidade_de_obra_enorme_usa_amostra_distribuida(self):
        palavras = (["inicio"] + [f"a{i}" for i in range(39_999)]
                    + ["marcadormeio"] + [f"b{i}" for i in range(39_999)]
                    + ["final"])
        texto = local.texto_normalizado_para_duplicidade(
            [" ".join(palavras)], limite=300)
        amostra = texto.split()
        self.assertLessEqual(len(amostra), 300)
        self.assertIn("inicio", amostra)
        self.assertIn("marcadormeio", amostra)
        self.assertIn("final", amostra)

    def test_duplicidade_textual_de_cadastro_confirmado_sai_da_revisao(self):
        with tempfile.TemporaryDirectory() as td:
            c = local.inicializar(pathlib.Path(td) / "livros")
            origem = c["entrada"] / "segunda.pdf"
            origem.write_bytes(b"%PDF-segunda")
            digest = hashlib.sha256(origem.read_bytes()).hexdigest()
            ficha = c["metadados"] / "segunda.json"
            local.salvar_json(ficha, {"arquivo": origem.name})
            catalogo = local.carregar_catalogo(c)
            catalogo["livros"][digest] = {
                "arquivo": origem.name, "caminho": local.relativo(c, origem),
                "metadados": local.relativo(c, ficha)}
            local.registrar_duplicado_textual(
                c, catalogo, digest, origem,
                {"simhash": "abc", "palavras": 100, "hash_texto": "def"},
                {"arquivo": "primeira.pdf", "caminho": "20-PRONTOS/primeira.pdf",
                 "similaridade": 0.9946, "estado": "cadastrado",
                 "id_remoto": 20561})
            registro = local.carregar_catalogo(c)["livros"][digest]
            self.assertEqual(local.ESTADO_DUPLICADO_CONTEUDO,
                             registro["estado"])
            self.assertEqual(20561, registro["id_remoto"])
            atualizada = json.loads(ficha.read_text(encoding="utf-8"))
            self.assertEqual("", atualizada["pendencias"])

    def test_compactacao_limita_tres_passes_progressivamente_agressivos(self):
        self.assertEqual(((120, 240), (105, 210), (96, 200)),
                         local.TENTATIVAS_COMPACTACAO)
        self.assertEqual(3, len(local.TENTATIVAS_COMPACTACAO))
        self.assertEqual(sorted(local.TENTATIVAS_COMPACTACAO, reverse=True),
                         list(local.TENTATIVAS_COMPACTACAO))

    def test_pdf_acima_de_75_mb_vai_direto_para_96_dpi(self):
        self.assertEqual(((96, 200),),
                         local.selecionar_tentativas_compactacao(79_261_614))
        self.assertEqual(local.TENTATIVAS_COMPACTACAO,
                         local.selecionar_tentativas_compactacao(60_000_000))

    def test_ganho_inferior_a_tres_por_cento_e_inexpressivo(self):
        fonte = 60_000_000
        pouco = local.medir_compactacao(fonte, 59_000_000)
        relevante = local.medir_compactacao(fonte, 55_000_000)
        self.assertFalse(pouco["ganho_relevante"])
        self.assertTrue(relevante["ganho_relevante"])
        self.assertEqual(9.0, pouco["excesso_mb"])

    def test_amostra_projeta_resultado_antes_da_compactacao_integral(self):
        with tempfile.TemporaryDirectory() as td:
            fonte = pathlib.Path(td) / "livro.pdf"
            fonte.write_bytes(b"%PDF-amostra")

            def qpdf_falso(comando, **kwargs):
                pathlib.Path(comando[-1]).write_bytes(b"%PDF-recorte")
                return mock.Mock(returncode=0)

            def compactar_falso(entrada, destino, **kwargs):
                with pathlib.Path(destino).open("wb") as f:
                    f.write(b"%PDF-")
                    f.seek(8_000_000 - 1)
                    f.write(b"x")
                return True

            with mock.patch.object(local.shutil, "which", return_value="qpdf"), \
                 mock.patch.object(local.subprocess, "run", side_effect=qpdf_falso), \
                 mock.patch.object(local.prep, "otimizar_pdf_envio",
                                   side_effect=compactar_falso):
                estimativa = local.estimar_compactacao_96(fonte, 1000)
            self.assertTrue(estimativa["disponivel"])
            self.assertEqual(140, estimativa["paginas_amostra"])
            self.assertEqual("exceção projetada", estimativa["decisao"])
            self.assertGreater(estimativa["projecao_bytes"],
                               local.LIMITE_PROJECAO_EXCECAO)

    def test_projecao_acima_do_limite_evitaria_processamento_integral(self):
        with tempfile.TemporaryDirectory() as td:
            c = local.inicializar(td)
            origem = c["entrada"] / "muito-grande.pdf"
            with origem.open("wb") as f:
                f.write(b"%PDF-")
                f.seek(local.LIMITE_ENVIO_BYTES + 10_000_000)
                f.write(b"x")
            bom = {"status": "OCR aprovado", "paginas_pesquisaveis": 500}
            projecao = {
                "disponivel": True, "paginas_amostra": 140,
                "projecao_mb": 72.5, "projecao_bytes": 72_500_000,
                "decisao": "exceção projetada",
            }
            with mock.patch.object(local.prep, "n_paginas", return_value=500), \
                 mock.patch.object(local.prep, "diagnosticar_ocr", return_value=bom), \
                 mock.patch.object(local, "estimar_compactacao_96",
                                   return_value=projecao), \
                 mock.patch.object(local.prep, "otimizar_pdf_envio") as otimizar:
                preparo = local.preparar_pdf_automaticamente(
                    c, origem, local.sha256(origem), ["texto bom"])
            otimizar.assert_not_called()
            self.assertEqual(projecao, preparo["preflight_compactacao"])
            self.assertIn("compactação integral evitada por amostragem",
                          preparo["acoes"])

    def test_diagnostico_estrutura_conta_fontes_jbig2_e_hebraico(self):
        imagens = """page num type width height color comp bpc enc
   1   0 image 2000 3000 gray 1 1 jbig2
   2   1 image 2000 3000 gray 1 1 jbig2
   3   2 image 1000 1000 rgb 3 8 jpeg
"""
        fontes = """name type encoding emb sub uni object ID
------------------------------------
Arial CID TrueType Identity-H yes yes yes 1 0
Times CID TrueType Identity-H yes yes yes 2 0
"""
        with mock.patch.object(
                local.subprocess, "run",
                side_effect=(mock.Mock(stdout=imagens),
                             mock.Mock(stdout=fontes))):
            d = local.diagnosticar_estrutura_pdf("livro.pdf", "שלום")
        self.assertEqual(3, d["imagens"])
        self.assertEqual(2, d["imagens_jbig2"])
        self.assertEqual(2, d["fontes"])
        self.assertTrue(d["alfabeto_complexo"])

    def test_estrutura_hebraica_otimizada_evitaria_reducao_de_dpi(self):
        with tempfile.TemporaryDirectory() as td:
            c = local.inicializar(td)
            origem = c["entrada"] / "hebraico.pdf"
            with origem.open("wb") as f:
                f.write(b"%PDF-")
                f.seek(local.LIMITE_ENVIO_BYTES + 20_000_000)
                f.write(b"x")
            bom = {"status": "OCR aprovado", "paginas_pesquisaveis": 500}
            estrutura = {
                "disponivel": True, "imagens": 800, "imagens_jbig2": 790,
                "proporcao_jbig2": 0.9875, "fontes": 6000,
                "alfabeto_complexo": True,
            }
            sem_perdas = {
                "disponivel": True, "metodo": "qpdf sem perdas",
                "tamanho_bytes": 55_000_000, "tamanho_mb": 55.0,
                "reducao_percentual": 21.4, "excesso_bytes": 5_000_000,
                "excesso_mb": 5.0, "contraproducente": False,
                "ganho_relevante": True,
            }
            with mock.patch.object(local.prep, "n_paginas", return_value=500), \
                 mock.patch.object(local.prep, "diagnosticar_ocr", return_value=bom), \
                 mock.patch.object(local, "diagnosticar_estrutura_pdf",
                                   return_value=estrutura), \
                 mock.patch.object(local, "otimizar_pdf_sem_perdas",
                                   return_value=(False, sem_perdas)), \
                 mock.patch.object(local.prep, "otimizar_pdf_envio") as raster:
                preparo = local.preparar_pdf_automaticamente(
                    c, origem, local.sha256(origem), ["שלום"])
            raster.assert_not_called()
            self.assertTrue(any("preservar escrita complexa" in a
                                for a in preparo["acoes"]))
            self.assertEqual(estrutura, preparo["diagnostico_estrutura"])

    def test_limpeza_sem_perdas_aprovada_vem_antes_do_raster(self):
        with tempfile.TemporaryDirectory() as td:
            c = local.inicializar(td)
            origem = c["entrada"] / "fontes-repetidas.pdf"
            with origem.open("wb") as f:
                f.write(b"%PDF-")
                f.seek(local.LIMITE_ENVIO_BYTES + 1_000_000)
                f.write(b"x")
            bom = {"status": "OCR aprovado", "paginas_pesquisaveis": 100}
            medida = {
                "disponivel": True, "metodo": "qpdf sem perdas",
                "tamanho_bytes": 45_000_000, "tamanho_mb": 45.0,
                "reducao_percentual": 11.8, "excesso_bytes": 0,
                "excesso_mb": 0.0, "contraproducente": False,
                "ganho_relevante": True, "resultado": "aceito",
            }

            def limpar(fonte, destino, **kwargs):
                pathlib.Path(destino).write_bytes(b"%PDF-limpo")
                return True, medida

            with mock.patch.object(local.prep, "n_paginas", return_value=100), \
                 mock.patch.object(local.prep, "diagnosticar_ocr", return_value=bom), \
                 mock.patch.object(local.prep, "paginas_pdftotext",
                                   return_value=["texto"]), \
                 mock.patch.object(local, "diagnosticar_estrutura_pdf",
                                   return_value={"disponivel": False}), \
                 mock.patch.object(local, "otimizar_pdf_sem_perdas",
                                   side_effect=limpar), \
                 mock.patch.object(local.prep, "otimizar_pdf_envio") as raster:
                preparo = local.preparar_pdf_automaticamente(
                    c, origem, local.sha256(origem), ["texto"])
            raster.assert_not_called()
            self.assertIn("PDF otimizado sem perdas", preparo["acoes"])
            self.assertEqual("qpdf sem perdas",
                             preparo["tentativas_compactacao"][0]["metodo"])

    def test_trava_impede_duas_execucoes_simultaneas(self):
        with tempfile.TemporaryDirectory() as td:
            with local.trava_execucao(td, "primeira"):
                with self.assertRaisesRegex(RuntimeError,
                                            "processamento ativo"):
                    with local.trava_execucao(td, "segunda"):
                        pass

    def test_progresso_persiste_pagina_percentual_e_estimativa(self):
        with tempfile.TemporaryDirectory() as td:
            c = local.inicializar(td)
            with mock.patch.object(local.time, "monotonic",
                                   side_effect=(100.0, 110.0)):
                progresso = local.monitor_progresso_compactacao(
                    c, "livro.pdf", 100, 96)
                progresso(20)
            ativo = json.loads((c["controle"] /
                                "processamento-ativo.json").read_text())
            self.assertEqual(20, ativo["pagina"])
            self.assertEqual(20, ativo["percentual"])
            self.assertEqual(40, ativo["eta_segundos"])
            self.assertEqual(96, ativo["dpi"])

    def test_progresso_ocr_persiste_percentual_e_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            c = local.inicializar(td)
            with mock.patch.object(local.time, "monotonic",
                                   side_effect=(100.0, 110.0)):
                progresso = local.monitor_progresso_ocr(
                    c, "livro.pdf", 200, 400_000_000)
                progresso(50, 600_000_000)
            ativo = json.loads((c["controle"] /
                                "processamento-ativo.json").read_text())
            self.assertEqual("OCR com Apple Vision", ativo["etapa"])
            self.assertEqual(25, ativo["percentual"])
            self.assertEqual(100_000_000, ativo["bytes_percorridos"])
            self.assertEqual(400_000_000, ativo["bytes_origem"])
            self.assertEqual(600_000_000,
                             ativo["bytes_temporarios_processados"])
            self.assertEqual(30, ativo["eta_segundos"])

    def test_progresso_limpeza_persiste_percentual_e_bytes_de_saida(self):
        with tempfile.TemporaryDirectory() as td:
            c = local.inicializar(td)
            with mock.patch.object(local.time, "monotonic",
                                   side_effect=(100.0, 110.0)):
                progresso = local.monitor_progresso_limpeza(
                    c, "livro.pdf", 200_000_000)
                progresso(40, 70_000_000)
            ativo = json.loads((c["controle"] /
                                "processamento-ativo.json").read_text())
            self.assertEqual("limpeza sem perdas", ativo["etapa"])
            self.assertEqual(40, ativo["percentual"])
            self.assertEqual(70_000_000, ativo["bytes_saida_temporaria"])
            self.assertEqual(15, ativo["eta_segundos"])

    def test_revisao_bibliografica_preserva_excecao_de_tamanho(self):
        with tempfile.TemporaryDirectory() as td:
            c = local.inicializar(td)
            origem = c["excecoes_tamanho"] / "volume-grande.pdf"
            with origem.open("wb") as f:
                f.write(b"%PDF-")
                f.seek(local.LIMITE_ENVIO_BYTES + 1000)
                f.write(b"x")
            digest = local.sha256(origem)
            ficha = c["metadados"] / "volume-grande.json"
            local.salvar_json(ficha, {
                "titulo": "Volume grande", "pdf_original": local.relativo(c, origem)})
            catalogo = local.carregar_catalogo(c)
            catalogo["livros"][digest] = {
                "hash_sha256": digest, "arquivo": origem.name,
                "caminho": local.relativo(c, origem),
                "metadados": local.relativo(c, ficha),
                "estado": local.ESTADO_EXCECAO_TAMANHO,
                "tamanho_bytes": origem.stat().st_size,
            }
            local.salvar_catalogo(c, catalogo)
            with mock.patch.object(local.prep, "paginas_pdftotext",
                                   return_value=["texto"]), \
                 mock.patch.object(local.prep, "gerar_capa", return_value=""), \
                 mock.patch.object(local.prep, "processar",
                                   return_value=resultado_pronto(origem.name)):
                local.reprocessar_revisao(td, usar_api=False,
                                          arquivos=[origem.name])
            registro = local.carregar_catalogo(c)["livros"][digest]
            self.assertEqual(local.ESTADO_EXCECAO_TAMANHO,
                             registro["estado"])
            self.assertTrue(origem.is_file())
            ativo = json.loads((c["controle"] /
                                "processamento-ativo.json").read_text())
            self.assertEqual("reavaliando 1 de 1", ativo["etapa"])
            self.assertEqual(origem.name, ativo["arquivo"])
            self.assertEqual(100, ativo["percentual"])

    def test_primeiro_passe_maior_interrompe_sem_novas_tentativas(self):
        with tempfile.TemporaryDirectory() as td:
            c = local.inicializar(td)
            origem = c["entrada"] / "incompressivel.pdf"
            with origem.open("wb") as f:
                f.write(b"%PDF-")
                f.seek(local.LIMITE_ENVIO_BYTES + 1_000_000)
                f.write(b"x")
            bom = {"status": "OCR aprovado", "paginas_pesquisaveis": 10}

            def aumentar(fonte, destino, **kwargs):
                with pathlib.Path(destino).open("wb") as f:
                    f.write(b"%PDF-")
                    f.seek(pathlib.Path(fonte).stat().st_size + 1_000_000)
                    f.write(b"x")
                return True

            with mock.patch.object(local.prep, "n_paginas", return_value=10), \
                 mock.patch.object(local.prep, "diagnosticar_ocr", return_value=bom), \
                 mock.patch.object(local.prep, "otimizar_pdf_envio",
                                   side_effect=aumentar) as otimizar:
                preparo = local.preparar_pdf_automaticamente(
                    c, origem, local.sha256(origem), ["texto bom"])
            self.assertEqual(1, otimizar.call_count)
            self.assertEqual("contraproducente",
                             preparo["tentativas_compactacao"][0]["resultado"])
            self.assertTrue(any("limite real" in erro
                                for erro in preparo["erros"]))

    def test_inicializa_sem_criar_pdfs(self):
        with tempfile.TemporaryDirectory() as td:
            c = local.inicializar(td)
            self.assertTrue(all(c[k].is_dir() for k in local.PASTAS))
            self.assertFalse(list(pathlib.Path(td).rglob("*.pdf")))

    def test_registra_legado_sem_mover(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = pathlib.Path(td)
            livro = raiz / "antigo.pdf"
            livro.write_bytes(b"PDF antigo")
            local.registrar_existentes(raiz)
            self.assertTrue(livro.exists())
            c = local.inicializar(raiz)
            catalogo = local.carregar_catalogo(c)
            self.assertEqual(1, len(catalogo["livros"]))
            self.assertEqual("antigo.pdf", next(iter(catalogo["livros"].values()))["caminho"])

    def test_reindexar_preserva_estado_cadastrado(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = pathlib.Path(td)
            livro = raiz / "enviado.pdf"
            livro.write_bytes(b"PDF ja enviado")
            c = local.inicializar(raiz)
            digest = local.sha256(livro)
            local.salvar_json(c["metadados"] / "enviado.json", {
                "situacao": "pronto para cadastro", "gerado_em": "agora"})
            catalogo = local.carregar_catalogo(c)
            catalogo["livros"][digest] = {
                "hash_sha256": digest, "arquivo": livro.name,
                "caminho": livro.name, "estado": "cadastrado",
                "id_remoto": 123,
            }
            local.salvar_catalogo(c, catalogo)
            local.registrar_existentes(raiz)
            atualizado = local.carregar_catalogo(c)["livros"][digest]
            self.assertEqual("cadastrado", atualizado["estado"])
            self.assertEqual(123, atualizado["id_remoto"])

    def test_consulta_previa_usa_campos_da_revisao_manual(self):
        with tempfile.TemporaryDirectory() as td:
            origem = pathlib.Path(td) / "ruim.pdf"
            origem.write_bytes(b"%PDF")
            revisao = {"campos": {
                "titulo": "Livro Revisado",
                "nmAutor0": "Autor, Correto",
                "isbn": "9788577790364",
                "autores": [{"nome": "Autor, Correto", "desc": "Autor"}],
            }}
            with mock.patch.object(local.prep, "paginas_pdftotext", return_value=[]), \
                 mock.patch.object(local.prep, "revisao_manual", return_value=revisao), \
                 mock.patch.object(local.prep, "metadados_pdf",
                                   return_value={"titulo": "Aula 2",
                                                 "autor": "INGLATERRA, NA"}), \
                 mock.patch.object(local.prep, "do_nome",
                                   return_value=("Arquivo Ruim", "")):
                pistas = local.pistas_consulta_previa(origem)
            self.assertEqual("9788577790364", pistas["isbn"])
            self.assertEqual("Livro Revisado", pistas["titulo"])
            self.assertEqual(["Autor, Correto"], pistas["autores"])

    def test_consulta_previa_nao_envia_titulo_autor_ruidosos(self):
        with tempfile.TemporaryDirectory() as td:
            origem = pathlib.Path(td) / "Aula 2 - INGLATERRA NA.pdf"
            origem.write_bytes(b"%PDF")
            sessao = object()
            with mock.patch.object(local.prep, "paginas_pdftotext", return_value=[]), \
                 mock.patch.object(local.prep, "revisao_manual", return_value={}), \
                 mock.patch.object(local.prep, "metadados_pdf",
                                   return_value={"titulo": "Aula 2",
                                                 "autor": "INGLATERRA, NA"}), \
                 mock.patch.object(local.prep, "do_nome",
                                   return_value=("Aula 2", "INGLATERRA, NA")), \
                 mock.patch.object(local.api_envio, "consultar_livro") as consultar:
                resposta, pistas = local.consultar_duplicidade_antes_do_preparo(
                    origem, sessao, "chave")
            self.assertEqual({}, resposta)
            self.assertEqual("", pistas["titulo"])
            self.assertEqual([], pistas["autores"])
            consultar.assert_not_called()

    def test_pacote_revisao_explica_ausencia_e_aponta_paginas_internas(self):
        with tempfile.TemporaryDirectory() as td:
            c = local.inicializar(pathlib.Path(td) / "livros")
            pdf = c["revisao"] / "pendente.pdf"
            pdf.write_bytes(b"%PDF-pendente")
            digest = local.sha256(pdf)
            ficha = c["metadados"] / "pendente.json"
            local.salvar_json(ficha, {
                "arquivo": pdf.name,
                "pdf_original": local.relativo(c, pdf),
                "titulo": "Livro Pendente",
                "nmAutor0": "",
                "editora": "",
                "data": "1987",
                "nmLingua": "Português",
                "tipo_documento": "livro",
                "pendencias": "autor: CIP sem resultado | editora: créditos sem padrão",
                "fontes_rejeitadas": [{
                    "fonte": "Estante Virtual",
                    "motivo": "autor não encontrado",
                }],
                "conflitos": "autor so do nome do arquivo: Pendente",
            })
            catalogo = local.carregar_catalogo(c)
            catalogo["livros"][digest] = {
                "hash_sha256": digest,
                "arquivo": pdf.name,
                "caminho": local.relativo(c, pdf),
                "estado": "conflito",
                "metadados": local.relativo(c, ficha),
            }
            local.salvar_catalogo(c, catalogo)
            paginas = [
                "Livro Pendente\nFolha de rosto",
                "Dados Internacionais de Catalogação\nAutor, Correto",
                "Copyright © 1987\nEditora Teste\nISBN 978-85-7779-036-4",
            ]
            with mock.patch.object(local.prep, "paginas_pdftotext",
                                   return_value=paginas):
                pacote = local.montar_pacote_revisao(
                    c, digest, catalogo["livros"][digest])
            self.assertEqual(local.relativo(c, pdf), pacote["pdf_visualizacao"])
            self.assertEqual(["autor so do nome do arquivo: Pendente"],
                             pacote["conflitos"])
            campos_ausentes = {a["campo"]: a for a in pacote["ausencias"]}
            self.assertIn("nmAutor0", campos_ausentes)
            self.assertIn("editora", campos_ausentes)
            self.assertIn("CIP", " ".join(campos_ausentes["nmAutor0"]["causas"]))
            self.assertTrue(any("ficha catalográfica/CIP" in p["motivo"]
                                for p in pacote["paginas_sugeridas"]))
            self.assertTrue(any("Editora Teste" in p["trecho"]
                                for p in pacote["paginas_sugeridas"]))
            self.assertEqual("ISBN válido localizado",
                             pacote["busca_isbn"]["motivo"])
            self.assertEqual("9788577790364",
                             pacote["busca_isbn"]["validos"][0]["isbn"])

    def test_pacote_revisao_mostra_isbn_suspeito_truncado(self):
        with tempfile.TemporaryDirectory() as td:
            c = local.inicializar(pathlib.Path(td) / "livros")
            pdf = c["revisao"] / "isbn-ruim.pdf"
            pdf.write_bytes(b"%PDF-isbn")
            digest = local.sha256(pdf)
            ficha = c["metadados"] / "isbn-ruim.json"
            local.salvar_json(ficha, {
                "arquivo": pdf.name,
                "pdf_original": local.relativo(c, pdf),
                "titulo": "Livro com ISBN ruim",
                "nmAutor0": "Autor, Teste",
                "editora": "Editora Teste",
                "data": "2020",
                "nmLingua": "Português",
                "tipo_documento": "livro",
                "pendencias": "isbn: leitura truncada",
                "conflitos": "",
            })
            catalogo = local.carregar_catalogo(c)
            catalogo["livros"][digest] = {
                "hash_sha256": digest,
                "arquivo": pdf.name,
                "caminho": local.relativo(c, pdf),
                "estado": "analisado",
                "metadados": local.relativo(c, ficha),
            }
            paginas = ["Copyright\nISBN 978-85-7779-036-5\nEditora Teste"]
            with mock.patch.object(local.prep, "paginas_pdftotext",
                                   return_value=paginas):
                pacote = local.montar_pacote_revisao(
                    c, digest, catalogo["livros"][digest])
            self.assertEqual(
                "ISBN suspeito localizado; exige conferência visual",
                pacote["busca_isbn"]["motivo"])
            self.assertEqual("9788577790365",
                             pacote["busca_isbn"]["suspeitos"][0]["valor"])
            self.assertTrue(
                pacote["busca_isbn"]["suspeitos"][0]["correcoes_um_digito"])

    def test_pacote_revisao_explica_tipo_de_material_suspeito(self):
        with tempfile.TemporaryDirectory() as td:
            c = local.inicializar(pathlib.Path(td) / "livros")
            pdf = c["revisao"] / "aula.pdf"
            pdf.write_bytes(b"%PDF-aula")
            digest = local.sha256(pdf)
            ficha = c["metadados"] / "aula.json"
            local.salvar_json(ficha, {
                "arquivo": pdf.name,
                "pdf_original": local.relativo(c, pdf),
                "titulo": "Aula 2 - Formação de um líder",
                "nmAutor0": "",
                "editora": "",
                "data": "",
                "nmLingua": "Português",
                "tipo_documento": "livro",
                "pendencias": "",
                "conflitos": "",
            })
            registro = {
                "hash_sha256": digest,
                "arquivo": pdf.name,
                "caminho": local.relativo(c, pdf),
                "estado": "analisado",
                "metadados": local.relativo(c, ficha),
            }
            paginas = ["Aula 2\nFormação de um líder\nSlides do treinamento"]
            with mock.patch.object(local.prep, "paginas_pdftotext",
                                   return_value=paginas):
                pacote = local.montar_pacote_revisao(c, digest, registro)
            classificacao = pacote["classificacao_material"]
            self.assertEqual("livro", classificacao["tipo_atual"])
            self.assertTrue(any("documento" in s["tipo"]
                                for s in classificacao["sinais"]))
            self.assertTrue(classificacao["contradicoes"])

    def test_gravar_decisao_revisao_mescla_e_alimenta_memorias(self):
        with tempfile.TemporaryDirectory() as td:
            c = local.inicializar(pathlib.Path(td) / "livros")
            pdf = c["revisao"] / "manual.pdf"
            pdf.write_bytes(b"%PDF-manual")
            digest = local.sha256(pdf)
            ficha = c["metadados"] / "manual.json"
            local.salvar_json(ficha, {
                "arquivo": pdf.name,
                "titulo": "Plano de aula 2",
                "nmAutor0": "INGLATERRA, NA",
                "editora": "",
                "data": "",
                "tipo_documento": "livro",
            })
            catalogo = local.carregar_catalogo(c)
            catalogo["livros"][digest] = {
                "hash_sha256": digest,
                "arquivo": pdf.name,
                "caminho": local.relativo(c, pdf),
                "estado": "conflito",
                "metadados": local.relativo(c, ficha),
            }
            local.salvar_catalogo(c, catalogo)
            revisoes = {"versao": 1, "livros": {
                pdf.name: {
                    "hash_sha256": digest,
                    "campos": {"titulo": "Título antigo"},
                    "fontes": ["CIP"],
                    "aprovado": False,
                }
            }}
            local.salvar_json(c["controle"] / "revisoes-manuais.json", revisoes)
            with mock.patch.object(local.prep, "ARQUIVO_TITULOS_RUIDOSOS",
                                   c["controle"] / "titulos.json"), \
                 mock.patch.object(local.prep, "ARQUIVO_AUTORES_RUIDOSOS",
                                   c["controle"] / "autores.json"):
                resultado = local.gravar_decisao_revisao(
                    c["raiz"], pdf.name,
                    campos={"nmAutor0": "Autor, Correto",
                            "editora": "Editora Teste"},
                    fontes=["folha de rosto"],
                    ruidos_titulo=["Plano de aula 2"],
                    ruidos_autor=["INGLATERRA, NA"])
            gravada = json.loads((c["controle"] /
                                  "revisoes-manuais.json").read_text(
                                      encoding="utf-8"))["livros"][pdf.name]
            self.assertEqual("Título antigo", gravada["campos"]["titulo"])
            self.assertEqual("Autor, Correto", gravada["campos"]["nmAutor0"])
            self.assertTrue(gravada["aprovado"])
            self.assertFalse(gravada["confirmacao_soberana"])
            self.assertIn("CIP", gravada["fontes"])
            self.assertIn("folha de rosto", gravada["fontes"])
            self.assertTrue(resultado["aprendizados"])
            titulos = json.loads((c["controle"] / "titulos.json").read_text(
                encoding="utf-8"))["itens"]
            autores = json.loads((c["controle"] / "autores.json").read_text(
                encoding="utf-8"))["itens"]
            self.assertTrue(any(i["texto"] == "Plano de aula 2"
                                for i in titulos))
            self.assertTrue(any(i["texto"] == "INGLATERRA, NA"
                                for i in autores))

    def test_gravar_decisao_revisao_registra_confirmacao_soberana(self):
        with tempfile.TemporaryDirectory() as td:
            c = local.inicializar(pathlib.Path(td) / "livros")
            pdf = c["revisao"] / "divergente.pdf"
            pdf.write_bytes(b"%PDF-divergente")
            digest = local.sha256(pdf)
            ficha = c["metadados"] / "divergente.json"
            local.salvar_json(ficha, {"arquivo": pdf.name,
                                      "titulo": "Livro divergente"})
            catalogo = local.carregar_catalogo(c)
            catalogo["livros"][digest] = {
                "hash_sha256": digest,
                "arquivo": pdf.name,
                "caminho": local.relativo(c, pdf),
                "estado": "conflito",
                "metadados": local.relativo(c, ficha),
            }
            local.salvar_catalogo(c, catalogo)

            local.gravar_decisao_revisao(
                c["raiz"], pdf.name, campos={"edicao": "1a"},
                fontes=["decisão soberana do operador"],
                confirmacao_soberana=True,
                motivo_confirmacao="página de créditos conferida visualmente",
                imprimir=False)

            gravada = json.loads((c["controle"] /
                                  "revisoes-manuais.json").read_text(
                                      encoding="utf-8"))["livros"][pdf.name]
            self.assertTrue(gravada["confirmacao_soberana"])
            self.assertIn("página de créditos",
                          gravada["motivo_confirmacao_soberana"])

    def test_pacote_revisao_aplica_revisao_manual_salva(self):
        with tempfile.TemporaryDirectory() as td:
            c = local.inicializar(pathlib.Path(td) / "livros")
            pdf = c["revisao"] / "manual-salvo.pdf"
            pdf.write_bytes(b"%PDF-manual-salvo")
            digest = local.sha256(pdf)
            ficha = c["metadados"] / "manual-salvo.json"
            local.salvar_json(ficha, {
                "arquivo": pdf.name,
                "pdf_original": local.relativo(c, pdf),
                "titulo": "TITULO ERRADO DA CAPA",
                "nmAutor0": "autor errado",
                "tipo_documento": "livro",
            })
            catalogo = local.carregar_catalogo(c)
            catalogo["livros"][digest] = {
                "hash_sha256": digest,
                "arquivo": pdf.name,
                "caminho": local.relativo(c, pdf),
                "estado": "analisado",
                "metadados": local.relativo(c, ficha),
            }
            local.salvar_catalogo(c, catalogo)
            local.salvar_json(c["controle"] / "revisoes-manuais.json", {
                "versao": 1,
                "livros": {
                    pdf.name: {
                        "hash_sha256": digest,
                        "aprovado": True,
                        "campos": {
                            "titulo": "Título revisado",
                            "nmAutor0": "Autor, Correto",
                        },
                    }
                },
            })

            pacote = local.montar_pacote_revisao(
                c, digest, catalogo["livros"][digest])

            self.assertEqual("Título revisado", pacote["campos"]["titulo"])
            self.assertEqual("Autor, Correto", pacote["campos"]["nmAutor0"])

    def test_gravar_decisao_revisao_atualiza_ficha_metadados(self):
        with tempfile.TemporaryDirectory() as td:
            c = local.inicializar(pathlib.Path(td) / "livros")
            pdf = c["revisao"] / "persistente.pdf"
            pdf.write_bytes(b"%PDF-persistente")
            digest = local.sha256(pdf)
            ficha = c["metadados"] / "persistente.json"
            local.salvar_json(ficha, {
                "arquivo": pdf.name,
                "titulo": "Antes",
                "tipo_documento": "livro",
            })
            catalogo = local.carregar_catalogo(c)
            catalogo["livros"][digest] = {
                "hash_sha256": digest,
                "arquivo": pdf.name,
                "caminho": local.relativo(c, pdf),
                "estado": "analisado",
                "metadados": local.relativo(c, ficha),
            }
            local.salvar_catalogo(c, catalogo)

            local.gravar_decisao_revisao(
                c["raiz"], pdf.name,
                campos={"titulo": "Depois", "nmAutor0": "Autor"},
                imprimir=False)

            salva = json.loads(ficha.read_text(encoding="utf-8"))
            self.assertEqual("Depois", salva["titulo"])
            self.assertEqual("Autor", salva["nmAutor0"])
            self.assertTrue(salva["revisao_manual_aplicada"])

    def test_substituir_capa_revisao_por_url_atualiza_ficha_e_catalogo(self):
        class HeadersFake:
            def get(self, chave, padrao=None):
                return padrao

            def get_content_type(self):
                return "image/png"

        class RespostaFake:
            headers = HeadersFake()

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def getheader(self, chave):
                return None

            def read(self, limite=-1):
                return b"\x89PNG\r\n\x1a\nimagem"

        with tempfile.TemporaryDirectory() as td:
            c = local.inicializar(pathlib.Path(td) / "livros")
            pdf = c["revisao"] / "sem-capa.pdf"
            pdf.write_bytes(b"%PDF-sem-capa")
            digest = local.sha256(pdf)
            ficha = c["metadados"] / "sem-capa.json"
            local.salvar_json(ficha, {"arquivo": pdf.name, "titulo": "Sem capa"})
            catalogo = local.carregar_catalogo(c)
            catalogo["livros"][digest] = {
                "hash_sha256": digest,
                "arquivo": pdf.name,
                "caminho": local.relativo(c, pdf),
                "estado": "analisado",
                "metadados": local.relativo(c, ficha),
            }
            local.salvar_catalogo(c, catalogo)

            with mock.patch.object(local.urllib.request, "urlopen",
                                   return_value=RespostaFake()):
                out = local.substituir_capa_revisao(
                    c["raiz"], pdf.name, "https://exemplo.test/capa.png",
                    imprimir=False)

            self.assertTrue((c["raiz"] / out["capa"]).is_file())
            salva = json.loads(ficha.read_text(encoding="utf-8"))
            self.assertEqual(out["capa"], salva["capa"])
            catalogo = local.carregar_catalogo(c)
            self.assertEqual(out["capa"], catalogo["livros"][digest]["capa"])

    def test_substituir_capa_revisao_por_arquivo_local(self):
        with tempfile.TemporaryDirectory() as td:
            c = local.inicializar(pathlib.Path(td) / "livros")
            pdf = c["revisao"] / "capa-local.pdf"
            pdf.write_bytes(b"%PDF-capa-local")
            digest = local.sha256(pdf)
            ficha = c["metadados"] / "capa-local.json"
            local.salvar_json(ficha, {"arquivo": pdf.name, "titulo": "Capa local"})
            catalogo = local.carregar_catalogo(c)
            catalogo["livros"][digest] = {
                "hash_sha256": digest,
                "arquivo": pdf.name,
                "caminho": local.relativo(c, pdf),
                "estado": "analisado",
                "metadados": local.relativo(c, ficha),
            }
            local.salvar_catalogo(c, catalogo)

            conteudo = base64.b64encode(b"\xff\xd8imagem").decode("ascii")
            out = local.substituir_capa_arquivo_revisao(
                c["raiz"], pdf.name, "minha-capa.jpg", conteudo,
                imprimir=False)

            self.assertTrue(out["capa"].endswith(".jpg"))
            self.assertTrue((c["raiz"] / out["capa"]).is_file())

    def test_gravar_decisao_revisao_aprovada_move_para_prontos(self):
        with tempfile.TemporaryDirectory() as td:
            c = local.inicializar(pathlib.Path(td) / "livros")
            pdf = c["revisao"] / "revisado.pdf"
            pdf.write_bytes(b"%PDF-revisado")
            digest = local.sha256(pdf)
            ficha = c["metadados"] / "revisado.json"
            local.salvar_json(ficha, {
                "arquivo": pdf.name,
                "titulo": "Antes",
                "tipo_documento": "livro",
            })
            catalogo = local.carregar_catalogo(c)
            catalogo["livros"][digest] = {
                "hash_sha256": digest,
                "arquivo": pdf.name,
                "caminho": local.relativo(c, pdf),
                "estado": "analisado",
                "metadados": local.relativo(c, ficha),
            }
            local.salvar_catalogo(c, catalogo)

            local.gravar_decisao_revisao(
                c["raiz"], pdf.name,
                campos={"titulo": "Depois", "tipo_documento": "livro"},
                aprovado=True,
                imprimir=False)

            catalogo = local.carregar_catalogo(c)
            registro = catalogo["livros"][digest]
            self.assertEqual("pronto para cadastro", registro["estado"])
            self.assertTrue((c["pronto"] / registro["arquivo"]).is_file())
            salva = json.loads(ficha.read_text(encoding="utf-8"))
            self.assertEqual("pronto para cadastro", salva["situacao"])

    def test_pacotes_revisao_nao_reabre_pronto_com_pendencia_historica(self):
        with tempfile.TemporaryDirectory() as td:
            c = local.inicializar(pathlib.Path(td) / "livros")
            pdf = c["pronto"] / "lider.pdf"
            pdf.write_bytes(b"%PDF-lider")
            digest = local.sha256(pdf)
            ficha = c["metadados"] / "lider.json"
            local.salvar_json(ficha, {
                "arquivo": pdf.name,
                "titulo": "Tornando-se um líder",
                "nmAutor0": "Munroe, Myles",
                "editora": "Maná",
                "data": "2006",
                "nmLingua": "Português",
                "tipo_documento": "livro",
                "situacao": "pronto para cadastro",
                "situacao_metadados": "pronto para cadastro",
                "pendencias": "editora: fonte antiga sem resultado",
                "revisao_manual_aprovada": True,
            })
            catalogo = local.carregar_catalogo(c)
            catalogo["livros"][digest] = {
                "hash_sha256": digest,
                "arquivo": pdf.name,
                "caminho": local.relativo(c, pdf),
                "estado": "pronto para cadastro",
                "metadados": local.relativo(c, ficha),
            }
            local.salvar_catalogo(c, catalogo)

            pacote = local.pacotes_revisao(c["raiz"], limite=0,
                                           imprimir=False)

            self.assertEqual([], pacote["itens"])

    def test_pacotes_revisao_nao_lista_cadastrado_liberado_sem_pdf(self):
        with tempfile.TemporaryDirectory() as td:
            c = local.inicializar(pathlib.Path(td) / "livros")
            ficha = c["metadados"] / "liberado.json"
            local.salvar_json(ficha, {
                "arquivo": "liberado.pdf",
                "titulo": "Arquivo liberado",
                "tipo_documento": "apostila",
                "pendencias": "autor: campo opcional não localizado",
            })
            catalogo = local.carregar_catalogo(c)
            catalogo["livros"]["a" * 64] = {
                "hash_sha256": "a" * 64,
                "arquivo": "liberado.pdf",
                "caminho": "16-ARTIGOS-E-DOCUMENTOS/liberado.pdf",
                "estado": "cadastrado - arquivos locais liberados",
                "arquivos_liberados_em": "2026-09-12T10:00:00",
                "metadados": local.relativo(c, ficha),
            }
            local.salvar_catalogo(c, catalogo)

            pacote = local.pacotes_revisao(c["raiz"], limite=0,
                                           imprimir=False)

            self.assertEqual([], pacote["itens"])

    def test_consultar_metadados_isbn_revisao_prefere_fonte_mais_completa(self):
        class FontesFake:
            @staticmethod
            def pasta_cache_para_pdf(caminho):
                return pathlib.Path(caminho).parent / "_cache"

            @staticmethod
            def consultar_open_library(isbn, cache, sessao=None,
                                       atualizar=False):
                return {
                    "titulo": "Livro incompleto",
                    "autores": "Autor, Teste",
                    "fonte": "Open Library",
                }

            @staticmethod
            def consultar_google_books(isbn, cache, sessao=None,
                                       atualizar=False):
                return {
                    "titulo": "Livro Completo",
                    "subtitulo": "Subtítulo",
                    "autores": "Autor, Teste; Segundo, Autor",
                    "editora": "Editora Teste",
                    "ano": "2022",
                    "paginas": "128",
                    "assuntos": "Teologia",
                    "isbn": isbn,
                    "fonte": "Google Books",
                }

            @staticmethod
            def consultar_library_of_congress(isbn, cache, sessao=None,
                                              atualizar=False):
                return {}

            @staticmethod
            def consultar_hathitrust(isbn, cache, sessao=None, atualizar=False):
                return {}

            @staticmethod
            def consultar_bnf(isbn, cache, sessao=None, atualizar=False):
                return []

            @staticmethod
            def resolver_candidatos(candidatos):
                return {}, "não encontrado"

        with tempfile.TemporaryDirectory() as td:
            c = local.inicializar(pathlib.Path(td) / "livros")
            with mock.patch.object(local.prep, "fontes_biblio", FontesFake), \
                 mock.patch.object(local.prep, "consultar_cbl", None):
                resposta = local.consultar_metadados_isbn_revisao(
                    c["raiz"], "978-85-7779-036-4", imprimir=False)

            self.assertTrue(resposta["encontrado"])
            self.assertEqual("Google Books", resposta["melhor"]["fonte"])
            self.assertEqual("Livro Completo", resposta["campos"]["titulo"])
            self.assertEqual("Autor, Teste", resposta["campos"]["nmAutor0"])
            self.assertEqual("128", resposta["campos"]["nPaginas"])

    def test_consultar_metadados_isbn_revisao_aceita_isbn10(self):
        class FontesFake:
            @staticmethod
            def pasta_cache_para_pdf(caminho):
                return pathlib.Path(caminho).parent / "_cache"

            @staticmethod
            def consultar_open_library(isbn, cache, sessao=None,
                                       atualizar=False):
                return {"titulo": "ISBN Dez", "autores": "Autor",
                        "isbn": isbn, "fonte": "Open Library"}

            consultar_google_books = staticmethod(lambda *a, **k: {})
            consultar_library_of_congress = staticmethod(lambda *a, **k: {})
            consultar_hathitrust = staticmethod(lambda *a, **k: {})
            consultar_bnf = staticmethod(lambda *a, **k: [])
            resolver_candidatos = staticmethod(lambda c: ({}, ""))

        with tempfile.TemporaryDirectory() as td:
            c = local.inicializar(pathlib.Path(td) / "livros")
            with mock.patch.object(local.prep, "fontes_biblio", FontesFake), \
                 mock.patch.object(local.prep, "consultar_cbl", None):
                resposta = local.consultar_metadados_isbn_revisao(
                    c["raiz"], "8577790363", imprimir=False)

            self.assertEqual("8577790363", resposta["isbn"])
            self.assertEqual("ISBN Dez", resposta["campos"]["titulo"])

    def test_consultar_metadados_isbn_revisao_vazia_devolve_links_busca(self):
        class FontesFake:
            pasta_cache_para_pdf = staticmethod(
                lambda caminho: pathlib.Path(caminho).parent / "_cache")
            consultar_open_library = staticmethod(lambda *a, **k: {})
            consultar_google_books = staticmethod(lambda *a, **k: {})
            consultar_library_of_congress = staticmethod(lambda *a, **k: {})
            consultar_hathitrust = staticmethod(lambda *a, **k: {})
            consultar_bnf = staticmethod(lambda *a, **k: [])
            resolver_candidatos = staticmethod(lambda c: ({}, ""))

        with tempfile.TemporaryDirectory() as td:
            c = local.inicializar(pathlib.Path(td) / "livros")
            with mock.patch.object(local.prep, "fontes_biblio", FontesFake), \
                 mock.patch.object(local.prep, "consultar_cbl", None):
                resposta = local.consultar_metadados_isbn_revisao(
                    c["raiz"], "9788587646293", imprimir=False)

            self.assertFalse(resposta["encontrado"])
            rotulos = [x["rotulo"] for x in resposta["links_busca"]]
            self.assertIn("Google — Touché Livros", rotulos)
            self.assertTrue(any("9788587646293" in x["url"]
                                for x in resposta["links_busca"]))

    def test_livro_pronto_e_movido_sem_copia(self):
        with tempfile.TemporaryDirectory() as td:
            c = local.inicializar(td)
            origem = c["entrada"] / "novo.pdf"
            origem.write_bytes(b"um PDF de teste")
            with mock.patch.object(local.prep, "paginas_pdftotext", return_value=["texto"]), \
                 mock.patch.object(local.prep, "n_paginas", return_value=1), \
                 mock.patch.object(local.prep, "diagnosticar_ocr",
                                   return_value={"status": "OCR aprovado"}), \
                 mock.patch.object(local.prep, "gerar_capa", return_value=""), \
                 mock.patch.object(local.prep, "processar",
                                   return_value=resultado_pronto(origem.name)):
                resumo = local.processar_entrada(td, usar_api=False)
            self.assertEqual(1, resumo["prontos"])
            self.assertFalse(origem.exists())
            prontos = list(c["pronto"].glob("*.pdf"))
            self.assertEqual(1, len(prontos))
            self.assertEqual(b"um PDF de teste", prontos[0].read_bytes())

    def test_isbn_descoberto_no_preparo_e_barrado_antes_da_fila(self):
        with tempfile.TemporaryDirectory() as td:
            c = local.inicializar(td)
            origem = c["entrada"] / "biblia.pdf"
            origem.write_bytes(b"um PDF de teste")
            linha = resultado_pronto(origem.name)
            linha.update({
                "titulo": "Bíblia Prazer da Palavra",
                "isbn": "9788594115430",
                "nmAutor0": "Azevedo, Israel",
                "autores": [{"nome": "Azevedo, Israel", "desc": "Autor"}],
                "tipo_documento": "livro",
            })
            resposta = {
                "encontrado": True,
                "correspondencia": "exata",
                "id": 20086,
                "titulo": "A História de Jesus Segundo os Evangelhos",
                "autores": ["AZEVEDO, ISRAEL"],
                "isbn": "9788594115430",
                "criterios_enviados": {"isbn": "9788594115430"},
            }
            with mock.patch.object(local.api_envio, "ler_chave_chaves",
                                   return_value="chave"), \
                 mock.patch.object(local.api_envio, "criar_sessao_api",
                                   return_value=object()), \
                 mock.patch.object(local, "consultar_duplicidade_antes_do_preparo",
                                   return_value=({}, {"isbn": ""})), \
                 mock.patch.object(local.api_envio, "consultar_livro",
                                   return_value=resposta) as consultar, \
                 mock.patch.object(local.prep, "paginas_pdftotext",
                                   return_value=["texto"]), \
                 mock.patch.object(local.prep, "n_paginas", return_value=1), \
                 mock.patch.object(local.prep, "diagnosticar_ocr",
                                   return_value={"status": "OCR aprovado"}), \
                 mock.patch.object(local.prep, "gerar_capa", return_value=""), \
                 mock.patch.object(local.prep, "processar", return_value=linha):
                resumo = local.processar_entrada(td, usar_api=True)

            self.assertEqual(1, consultar.call_count)
            self.assertEqual(1, resumo["duplicados_api"])
            self.assertEqual(0, resumo["prontos"])
            self.assertEqual(1, resumo["revisao"])
            self.assertFalse(origem.exists())
            duplicados = list((c["revisao"] / "DUPLICADOS-API").glob("*.pdf"))
            self.assertEqual(1, len(duplicados))
            registro = next(iter(local.carregar_catalogo(c)["livros"].values()))
            self.assertEqual("duplicado confirmado por ISBN", registro["estado"])
            self.assertEqual(20086, registro["id_remoto"])
            ficha = json.loads((c["raiz"] / registro["metadados"]).read_text(
                encoding="utf-8"))
            self.assertEqual(20086, ficha["consulta_previa_api"]["id"])

    def test_pdf_com_extensao_maiuscula_e_processado(self):
        with tempfile.TemporaryDirectory() as td:
            c = local.inicializar(td)
            origem = c["entrada"] / "Liberating News.PDF"
            origem.write_bytes(b"um PDF com extensao maiuscula")
            with mock.patch.object(local.prep, "paginas_pdftotext", return_value=["texto"]), \
                 mock.patch.object(local.prep, "n_paginas", return_value=1), \
                 mock.patch.object(local.prep, "diagnosticar_ocr",
                                   return_value={"status": "OCR aprovado"}), \
                 mock.patch.object(local.prep, "gerar_capa", return_value=""), \
                 mock.patch.object(local.prep, "processar",
                                   return_value=resultado_pronto(origem.name)):
                resumo = local.processar_entrada(td, usar_api=False)
            self.assertEqual(1, resumo["novos"])
            self.assertEqual(1, resumo["prontos"])
            self.assertFalse(origem.exists())
            self.assertTrue((c["pronto"] / origem.name).is_file())

    def test_falha_bibliografica_isola_item_e_lote_continua(self):
        with tempfile.TemporaryDirectory() as td:
            c = local.inicializar(td)
            primeiro = c["entrada"] / "01-com-falha.pdf"
            segundo = c["entrada"] / "02-valido.pdf"
            primeiro.write_bytes(b"PDF com metadados inesperados")
            segundo.write_bytes(b"PDF valido")

            def processar(fonte, **kwargs):
                if pathlib.Path(fonte).name == primeiro.name:
                    raise ValueError("texto inesperado")
                return resultado_pronto(segundo.name)

            with mock.patch.object(local.prep, "paginas_pdftotext", return_value=["texto"]), \
                 mock.patch.object(local.prep, "n_paginas", return_value=1), \
                 mock.patch.object(local.prep, "diagnosticar_ocr",
                                   return_value={"status": "OCR aprovado"}), \
                 mock.patch.object(local.prep, "gerar_capa", return_value=""), \
                 mock.patch.object(local.prep, "processar", side_effect=processar):
                resumo = local.processar_entrada(td, usar_api=False)

            self.assertEqual(2, resumo["novos"])
            self.assertEqual(1, resumo["prontos"])
            self.assertEqual(1, resumo["revisao"])
            self.assertEqual(1, len(list(c["revisao"].glob("01-com-falha*.pdf"))))
            self.assertEqual(1, len(list(c["pronto"].glob("02-valido*.pdf"))))

    def test_ocr_necessario_e_preparado_automaticamente(self):
        with tempfile.TemporaryDirectory() as td:
            c = local.inicializar(td)
            origem = c["entrada"] / "sem-ocr.pdf"
            origem.write_bytes(b"%PDF-original")
            ruim = {"status": "precisa OCR", "paginas_pesquisaveis": 0}
            bom = {"status": "OCR aprovado", "paginas_pesquisaveis": 10}

            def ocr_falso(fonte, destino, **kwargs):
                pathlib.Path(destino).write_bytes(b"%PDF-preparado-com-texto")
                return True

            with mock.patch.object(local.prep, "paginas_pdftotext",
                                   side_effect=([""], ["texto bom"])), \
                 mock.patch.object(local.prep, "n_paginas", return_value=10), \
                 mock.patch.object(local.prep, "diagnosticar_ocr",
                                   side_effect=(ruim, bom)), \
                 mock.patch.object(local.prep, "texto_inicio", return_value="livro"), \
                 mock.patch.object(local.prep, "idioma_do_texto", return_value="por"), \
                 mock.patch.object(local.prep, "rodar_ocr", side_effect=ocr_falso):
                preparo = local.preparar_pdf_automaticamente(
                    c, origem, local.sha256(origem), [""])
            self.assertEqual("OCR aprovado", preparo["diagnostico"]["status"])
            self.assertTrue(preparo["preparado"].is_file())
            self.assertIn("OCR criado", preparo["acoes"])
            self.assertFalse(preparo["erros"])
            self.assertTrue(origem.is_file())

    def test_pdf_grande_gera_copia_compacta(self):
        with tempfile.TemporaryDirectory() as td:
            c = local.inicializar(td)
            origem = c["entrada"] / "grande.pdf"
            with origem.open("wb") as f:
                f.write(b"%PDF-")
                f.seek(local.LIMITE_ENVIO_BYTES + 1024)
                f.write(b"x")
            bom = {"status": "OCR aprovado", "paginas_pesquisaveis": 10}

            def otimizar_falso(fonte, destino, **kwargs):
                pathlib.Path(destino).write_bytes(b"%PDF-compacto")
                return True

            with mock.patch.object(local.prep, "n_paginas", return_value=10), \
                 mock.patch.object(local.prep, "diagnosticar_ocr", return_value=bom), \
                 mock.patch.object(local.prep, "paginas_pdftotext",
                                   return_value=["texto bom"]), \
                 mock.patch.object(local.prep, "otimizar_pdf_envio",
                                   side_effect=otimizar_falso):
                preparo = local.preparar_pdf_automaticamente(
                    c, origem, local.sha256(origem), ["texto bom"])
            self.assertLess(preparo["tamanho_envio"], local.LIMITE_ENVIO_BYTES)
            self.assertTrue(any("PDF otimizado para envio" in acao
                                for acao in preparo["acoes"]))
            self.assertTrue(origem.is_file())

    def test_copia_de_envio_ausente_volta_ao_preparo(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = pathlib.Path(td)
            origem = raiz / "livro.pdf"
            origem.write_bytes(b"%PDF-original")
            registro = {"estado": "pronto para cadastro"}
            ficha = {"pdf_preparado": "_preparados-envio/ausente.pdf"}
            self.assertTrue(local.preparo_envio_pendente(
                registro, origem, ficha, raiz))

    def test_copia_de_envio_valida_nao_e_refeita(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = pathlib.Path(td)
            origem = raiz / "livro.pdf"
            copia = raiz / "_preparados-envio" / "livro.pdf"
            copia.parent.mkdir()
            origem.write_bytes(b"%PDF-original")
            copia.write_bytes(b"%PDF-compacto")
            registro = {"estado": "pronto para cadastro"}
            ficha = {"pdf_preparado": "_preparados-envio/livro.pdf"}
            self.assertFalse(local.preparo_envio_pendente(
                registro, origem, ficha, raiz))

    def test_duplicata_e_isolada_sem_apagar(self):
        with tempfile.TemporaryDirectory() as td:
            c = local.inicializar(td)
            legado = pathlib.Path(td) / "existente.pdf"
            legado.write_bytes(b"conteudo igual")
            local.registrar_existentes(td)
            novo = c["entrada"] / "outro-nome.pdf"
            novo.write_bytes(b"conteudo igual")
            resumo = local.processar_entrada(td, usar_api=False)
            self.assertEqual(1, resumo["duplicados"])
            self.assertTrue(legado.exists())
            self.assertFalse(novo.exists())
            self.assertEqual(1, len(list((c["revisao"] / "DUPLICADOS").glob("*.pdf"))))

    def test_catalogo_e_json_valido_apos_retomada(self):
        with tempfile.TemporaryDirectory() as td:
            c = local.inicializar(td)
            local.salvar_catalogo(c, local.carregar_catalogo(c))
            local.salvar_catalogo(c, local.carregar_catalogo(c))
            p = c["controle"] / "catalogo-local.json"
            self.assertIn("livros", json.loads(p.read_text(encoding="utf-8")))

    def test_academico_vai_para_fila_especifica_e_nao_para_api_de_livros(self):
        with tempfile.TemporaryDirectory() as td:
            c = local.inicializar(td)
            ficha = c["metadados"] / "tese.json"
            pdf = c["academicos"] / "pesquisa.pdf"
            capa = c["capas"] / "pesquisa.jpg"
            pdf.write_bytes(b"%PDF-pesquisa")
            capa.write_bytes(b"imagem")
            local.salvar_json(ficha, {
                "tipo_documento": "dissertação", "titulo": "Pesquisa",
                "nmAutor0": "Silva, Ana", "status_ocr": "OCR aprovado",
                "situacao": "aguardando cadastro específico",
                "conflitos": "", "pendencias": "",
                "pdf_original": local.relativo(c, pdf),
                "capa": local.relativo(c, capa),
            })
            catalogo = local.carregar_catalogo(c)
            catalogo["livros"]["a" * 64] = {
                "hash_sha256": "a" * 64, "arquivo": "pesquisa.pdf",
                "caminho": "15-TESES-DISSERTACOES-E-TRABALHOS/pesquisa.pdf",
                "estado": "aguardando cadastro específico",
                "metadados": local.relativo(c, ficha),
            }
            local.consolidar(c, catalogo)
            fila = json.loads((c["controle"] /
                               "fila-cadastro-academico.json").read_text())
            self.assertEqual(1, fila["quantidade"])
            self.assertTrue(fila["envio_automatico_habilitado"])
            self.assertEqual("dissertação", fila["itens"][0]["tipo_documento"])
            self.assertEqual("documento", fila["itens"][0]["tipo_api"])
            self.assertEqual("pronto para cadastro específico",
                             fila["itens"][0]["estado"])

    def test_revista_vai_para_fila_propria(self):
        with tempfile.TemporaryDirectory() as td:
            c = local.inicializar(td)
            ficha = c["metadados"] / "revista.json"
            pdf = c["revistas"] / "revista.pdf"
            capa = c["capas"] / "revista.jpg"
            pdf.write_bytes(b"%PDF-revista")
            capa.write_bytes(b"imagem")
            local.salvar_json(ficha, {
                "tipo_documento": "revista", "titulo": "Revista Teológica",
                "nmAutor0": "", "status_ocr": "OCR aprovado",
                "situacao": "aguardando cadastro específico",
                "conflitos": "", "pendencias": "",
                "pdf_original": local.relativo(c, pdf),
                "capa": local.relativo(c, capa),
            })
            catalogo = local.carregar_catalogo(c)
            catalogo["livros"]["r" * 64] = {
                "hash_sha256": "r" * 64, "arquivo": "revista.pdf",
                "caminho": "17-REVISTAS-E-PERIODICOS/revista.pdf",
                "estado": "aguardando cadastro específico",
                "metadados": local.relativo(c, ficha),
            }
            local.consolidar(c, catalogo)
            fila = json.loads((c["controle"] /
                               "fila-cadastro-revistas.json").read_text())
            self.assertEqual(1, fila["quantidade"])
            self.assertTrue(fila["envio_automatico_habilitado"])
            self.assertEqual("revista", fila["itens"][0]["tipo_api"])
            self.assertEqual("pronto para cadastro específico",
                             fila["itens"][0]["estado"])

    def test_arquivo_invalido_vai_para_descarte_duravel(self):
        with tempfile.TemporaryDirectory() as td:
            c = local.inicializar(td)
            self.assertEqual("19-DESCARTE", c["descarte"].name)
            self.assertTrue(c["descarte"].is_dir())
            self.assertNotIn(local.ESTADO_DESCARTE,
                             {"analisado", "conflito", "precisa OCR"})

    def test_liberar_espaco_simula_e_executa_so_cadastro_com_id(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as lixo:
            raiz = pathlib.Path(td) / "livros"
            c = local.inicializar(raiz)
            pdf = c["pronto"] / "confirmado.pdf"
            capa = c["capas"] / "confirmado.jpg"
            pendente = c["pronto"] / "pendente.pdf"
            pdf.write_bytes(b"%PDF-confirmado")
            capa.write_bytes(b"capa")
            pendente.write_bytes(b"%PDF-pendente")
            ficha_ok = c["metadados"] / "confirmado.json"
            ficha_pendente = c["metadados"] / "pendente.json"
            local.salvar_json(ficha_ok, {
                "titulo": "Confirmado", "pdf_original": local.relativo(c, pdf),
                "capa": local.relativo(c, capa)})
            local.salvar_json(ficha_pendente, {
                "titulo": "Pendente", "pdf_original": local.relativo(c, pendente)})
            catalogo = local.carregar_catalogo(c)
            catalogo["livros"] = {
                "ok": {"hash_sha256": "ok", "estado": "cadastrado",
                       "caminho": local.relativo(c, pdf),
                       "metadados": local.relativo(c, ficha_ok),
                       "tamanho_bytes": pdf.stat().st_size},
                "nao": {"hash_sha256": "nao", "estado": "pronto para cadastro",
                        "caminho": local.relativo(c, pendente),
                        "metadados": local.relativo(c, ficha_pendente),
                        "tamanho_bytes": pendente.stat().st_size},
            }
            local.salvar_catalogo(c, catalogo)
            local.salvar_json(c["controle"] / "fila-envio-api.json", {
                "itens": [
                    {"ficha": local.relativo(c, ficha_ok), "estado": "cadastrado",
                     "id_remoto": 55, "titulo": "Confirmado"},
                    {"ficha": local.relativo(c, ficha_pendente), "estado": "pendente",
                     "titulo": "Pendente"},
                ]})
            simulacao = local.liberar_espaco(raiz)
            self.assertEqual(1, simulacao["livros"])
            self.assertTrue(pdf.exists())
            executado = local.liberar_espaco(raiz, executar=True, lixeira=lixo)
            self.assertEqual(1, executado["livros"])
            self.assertFalse(pdf.exists())
            self.assertFalse(capa.exists())
            self.assertTrue(pendente.exists())
            self.assertTrue(ficha_ok.exists())
            self.assertEqual(2, len(list(pathlib.Path(lixo).iterdir())))
            manifesto = json.loads((c["controle"] /
                                    "manifesto-liberacao-espaco.json").read_text())
            self.assertEqual(55, manifesto["operacoes"][0]["livros"][0]["id_remoto"])

    def test_liberar_espaco_inclui_duplicado_confirmado_pela_api(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as lixo:
            raiz = pathlib.Path(td) / "livros"
            c = local.inicializar(raiz)
            pdf = c["pronto"] / "duplicado.pdf"
            capa = c["capas"] / "duplicado.jpg"
            pdf.write_bytes(b"%PDF-duplicado")
            capa.write_bytes(b"capa")
            ficha_path = c["metadados"] / "duplicado.json"
            local.salvar_json(ficha_path, {
                "titulo": "Livro duplicado", "tipo_documento": "livro",
                "pdf_original": local.relativo(c, pdf),
                "capa": local.relativo(c, capa)})
            catalogo = local.carregar_catalogo(c)
            catalogo["livros"]["dup"] = {
                "hash_sha256": "dup", "estado": "já existente na API - conferir vínculo",
                "arquivo": pdf.name, "caminho": local.relativo(c, pdf),
                "metadados": local.relativo(c, ficha_path),
                "capa": local.relativo(c, capa), "tamanho_bytes": pdf.stat().st_size}
            local.salvar_catalogo(c, catalogo)
            local.salvar_json(c["controle"] / "fila-envio-api.json", {
                "itens": [{
                    "ficha": local.relativo(c, ficha_path),
                    "titulo": "Livro duplicado",
                    "estado": "duplicado informado pela API - revisar",
                    "http_status": 400}]})

            simulacao = local.liberar_espaco(raiz)
            self.assertEqual(1, simulacao["livros"])
            self.assertEqual("duplicidade confirmada pela API",
                             simulacao["itens"][0]["motivo"])
            local.liberar_espaco(raiz, executar=True, lixeira=lixo)
            self.assertFalse(pdf.exists())
            self.assertFalse(capa.exists())
            self.assertTrue(ficha_path.exists())
            atualizado = local.carregar_catalogo(c)["livros"]["dup"]
            self.assertEqual("duplicado na API - arquivos locais liberados",
                             atualizado["estado"])
            fila = json.loads((c["controle"] / "fila-envio-api.json").read_text())
            self.assertEqual("duplicado na API - arquivos locais liberados",
                             fila["itens"][0]["estado"])

    def test_liberar_espaco_inclui_duplicado_confirmado_por_titulo_autor(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as lixo:
            raiz = pathlib.Path(td) / "livros"
            c = local.inicializar(raiz)
            pdf = c["pronto"] / "duplicado.pdf"
            capa = c["capas"] / "duplicado.jpg"
            pdf.write_bytes(b"%PDF-duplicado")
            capa.write_bytes(b"capa")
            ficha_path = c["metadados"] / "duplicado.json"
            local.salvar_json(ficha_path, {
                "titulo": "Livro duplicado", "tipo_documento": "livro",
                "pdf_original": local.relativo(c, pdf),
                "capa": local.relativo(c, capa)})
            catalogo = local.carregar_catalogo(c)
            catalogo["livros"]["dup"] = {
                "hash_sha256": "dup",
                "estado": local.api_envio.ESTADO_DUPLICADO_TITULO_AUTOR,
                "arquivo": pdf.name, "caminho": local.relativo(c, pdf),
                "metadados": local.relativo(c, ficha_path),
                "capa": local.relativo(c, capa),
                "tamanho_bytes": pdf.stat().st_size, "id_remoto": 12394,
                "confirmado_por_api": "titulo_autor"}
            local.salvar_catalogo(c, catalogo)
            local.salvar_json(c["controle"] / "fila-envio-api.json", {
                "itens": [{
                    "ficha": local.relativo(c, ficha_path),
                    "titulo": "Livro duplicado", "id_remoto": 12394,
                    "estado": local.api_envio.ESTADO_DUPLICADO_TITULO_AUTOR}]})

            simulacao = local.liberar_espaco(raiz)
            self.assertEqual(1, simulacao["livros"])
            local.liberar_espaco(raiz, executar=True, lixeira=lixo)
            self.assertFalse(pdf.exists())
            self.assertFalse(capa.exists())

    def test_fila_especifica_preserva_item_ja_enviado_e_liberado(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = pathlib.Path(td) / "livros"
            c = local.inicializar(raiz)
            ficha_path = c["metadados"] / "documento.json"
            local.salvar_json(ficha_path, {
                "titulo": "Documento enviado",
                "tipo_documento": "documento",
                "pdf_original": "16-ARTIGOS-E-DOCUMENTOS/ausente.pdf",
                "capa": "_capas/ausente.jpg",
                "motivo_liberacao_espaco": "cadastro confirmado pela API",
            })
            catalogo = local.carregar_catalogo(c)
            catalogo["livros"]["doc"] = {
                "hash_sha256": "doc", "arquivo": "ausente.pdf",
                "estado": "aguardando correção para cadastro específico",
                "caminho": "", "tamanho_bytes": 0,
                "metadados": local.relativo(c, ficha_path),
                "id_remoto": 20511,
                "arquivos_liberados_em": "2026-08-18T15:03:43",
            }
            local.consolidar_filas_especificas(c, catalogo)
            atualizado = local.carregar_catalogo(c)["livros"]["doc"]
            self.assertEqual("cadastrado - arquivos locais liberados",
                             atualizado["estado"])
            fila = json.loads((c["controle"] /
                               "fila-cadastro-documentos.json").read_text())
            self.assertEqual([], fila["itens"])

    def test_fila_especifica_preserva_id_remoto_do_catalogo(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = pathlib.Path(td) / "livros"
            c = local.inicializar(raiz)
            pdf = c["documentos"] / "documento.pdf"
            capa = c["capas"] / "documento.jpg"
            pdf.write_bytes(b"%PDF-documento")
            capa.write_bytes(b"capa")
            ficha_path = c["metadados"] / "documento.json"
            local.salvar_json(ficha_path, {
                "titulo": "Documento enviado",
                "nmAutor0": "Autor, Nome",
                "tipo_documento": "documento",
                "pdf_original": local.relativo(c, pdf),
                "capa": local.relativo(c, capa),
            })
            catalogo = local.carregar_catalogo(c)
            catalogo["livros"]["doc"] = {
                "hash_sha256": "doc", "arquivo": pdf.name,
                "estado": "cadastrado", "caminho": local.relativo(c, pdf),
                "metadados": local.relativo(c, ficha_path),
                "tamanho_bytes": pdf.stat().st_size, "id_remoto": 20773,
            }
            local.consolidar_filas_especificas(c, catalogo)
            fila = json.loads((c["controle"] /
                               "fila-cadastro-documentos.json").read_text())
            self.assertEqual(20773, fila["itens"][0]["id_remoto"])

    def test_isbn_ja_confirmado_no_catalogo_resolve_copia_pendente(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = pathlib.Path(td) / "livros"
            c = local.inicializar(raiz)
            ficha_fonte = c["metadados"] / "fonte.json"
            ficha_copia = c["metadados"] / "copia.json"
            local.salvar_json(ficha_fonte, {
                "titulo": "Obra cadastrada", "tipo_documento": "livro",
                "isbn": "9786586173208"})
            local.salvar_json(ficha_copia, {
                "titulo": "Outra cópia", "tipo_documento": "livro",
                "isbn": "978-65-86173-20-8"})
            catalogo = local.carregar_catalogo(c)
            catalogo["livros"]["fonte"] = {
                "hash_sha256": "fonte", "arquivo": "fonte.pdf",
                "estado": "cadastrado - arquivos locais liberados",
                "caminho": "", "metadados": local.relativo(c, ficha_fonte),
                "tamanho_bytes": 0, "id_remoto": 20469,
                "arquivos_liberados_em": "2026-09-03T10:00:00"}
            catalogo["livros"]["copia"] = {
                "hash_sha256": "copia", "arquivo": "copia.pdf",
                "estado": "já existente na API - conferir vínculo",
                "caminho": "10-REVISAO/DUPLICADOS-API/copia.pdf",
                "metadados": local.relativo(c, ficha_copia),
                "tamanho_bytes": 100, "id_remoto": 20469}

            local.consolidar_filas_especificas(c, catalogo)

            atualizado = local.carregar_catalogo(c)["livros"]["copia"]
            self.assertEqual("duplicado confirmado por ISBN",
                             atualizado["estado"])
            self.assertEqual("fonte", atualizado["duplicado_de"])
            self.assertEqual("isbn", atualizado["confirmado_por_api"])
            ficha = json.loads(ficha_copia.read_text(encoding="utf-8"))
            self.assertEqual("duplicado confirmado por ISBN", ficha["situacao"])

    def test_liberar_espaco_inclui_item_classificado_para_descarte(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as lixo:
            raiz = pathlib.Path(td) / "livros"
            c = local.inicializar(raiz)
            pdf = c["descarte"] / "resumo.pdf"
            preparado = c["preparados"] / "resumo-preparado.pdf"
            capa = c["capas"] / "resumo.jpg"
            pdf.write_bytes(b"%PDF-resumo")
            preparado.write_bytes(b"%PDF-resumo-preparado")
            capa.write_bytes(b"capa")
            ficha_path = c["metadados"] / "resumo.json"
            local.salvar_json(ficha_path, {
                "titulo": "Resumo incompleto",
                "tipo_documento": "arquivo inválido",
                "pdf_original": local.relativo(c, pdf),
                "pdf_preparado": local.relativo(c, preparado),
                "capa": local.relativo(c, capa),
            })
            catalogo = local.carregar_catalogo(c)
            catalogo["livros"]["desc"] = {
                "hash_sha256": "desc", "estado": local.ESTADO_DESCARTE,
                "arquivo": pdf.name, "caminho": local.relativo(c, pdf),
                "metadados": local.relativo(c, ficha_path),
                "capa": local.relativo(c, capa), "tamanho_bytes": pdf.stat().st_size,
            }
            local.salvar_catalogo(c, catalogo)

            simulacao = local.liberar_espaco(raiz)
            self.assertEqual(1, simulacao["livros"])
            self.assertEqual("item classificado para descarte",
                             simulacao["itens"][0]["motivo"])
            executado = local.liberar_espaco(raiz, executar=True, lixeira=lixo)
            self.assertEqual(1, executado["livros"])
            self.assertFalse(pdf.exists())
            self.assertFalse(preparado.exists())
            self.assertFalse(capa.exists())
            self.assertTrue(ficha_path.exists())
            self.assertEqual(3, len(list(pathlib.Path(lixo).iterdir())))
            atualizado = local.carregar_catalogo(c)["livros"]["desc"]
            self.assertEqual("descartado - arquivos locais liberados",
                             atualizado["estado"])

    def test_liberar_espaco_remove_pasta_completa_de_livro_importado(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as lixo:
            base = pathlib.Path(td)
            raiz = base / "biblioteca-local"
            pacote = base / "acervo-calibre" / "Autor" / "Livro"
            pacote.mkdir(parents=True)
            originais = [
                pacote / "livro.pdf", pacote / "livro.epub",
                pacote / "livro.opf", pacote / "livro.jpg",
            ]
            for arquivo in originais:
                arquivo.write_bytes((arquivo.suffix + "-original").encode())
            c = local.inicializar(raiz)
            pdf = c["pronto"] / "livro.pdf"
            pdf.write_bytes(b"%PDF-copia-local")
            ficha_path = c["metadados"] / "livro.json"
            local.salvar_json(ficha_path, {
                "titulo": "Livro importado",
                "pdf_original": local.relativo(c, pdf),
                "pasta_origem_importacao": str(pacote),
                "arquivos_origem_importacao": [str(p) for p in originais],
            })
            catalogo = local.carregar_catalogo(c)
            catalogo["livros"]["importado"] = {
                "hash_sha256": "importado", "estado": "cadastrado",
                "caminho": local.relativo(c, pdf),
                "metadados": local.relativo(c, ficha_path),
                "tamanho_bytes": pdf.stat().st_size,
            }
            local.salvar_catalogo(c, catalogo)
            local.salvar_json(c["controle"] / "fila-envio-api.json", {
                "itens": [{"ficha": local.relativo(c, ficha_path),
                           "estado": "cadastrado", "id_remoto": 81,
                           "titulo": "Livro importado"}]})

            simulacao = local.liberar_espaco(raiz)
            self.assertEqual(1, simulacao["livros"])
            self.assertIn(str((pacote / "livro.opf").resolve()),
                          simulacao["itens"][0]["arquivos"])
            self.assertTrue(pacote.exists())

            local.liberar_espaco(raiz, executar=True, lixeira=lixo)
            self.assertFalse(pacote.exists())
            self.assertFalse(pdf.exists())
            destinos = list(pathlib.Path(lixo).iterdir())
            self.assertEqual(5, len(destinos))
            self.assertTrue(all(p.is_file() for p in destinos))

    def test_word_original_pode_ser_liberado_depois_do_cadastro(self):
        with tempfile.TemporaryDirectory() as td:
            base = pathlib.Path(td)
            pasta = base / "originais" / "Documento"
            pasta.mkdir(parents=True)
            word = pasta / "Documento.docx"
            word.write_bytes(b"word-original")
            ficha = {
                "pasta_origem_importacao": str(pasta),
                "arquivos_origem_importacao": [str(word)],
            }
            self.assertEqual(
                [word.resolve()],
                local._arquivos_origem_importados(ficha, base / "biblioteca"))

    def test_powerpoint_original_pode_ser_liberado_depois_do_cadastro(self):
        with tempfile.TemporaryDirectory() as td:
            base = pathlib.Path(td)
            pasta = base / "originais" / "Apresentacao"
            pasta.mkdir(parents=True)
            powerpoint = pasta / "Apresentacao.pptx"
            powerpoint.write_bytes(b"powerpoint-original")
            ficha = {
                "pasta_origem_importacao": str(pasta),
                "arquivos_origem_importacao": [str(powerpoint)],
            }
            self.assertEqual(
                [powerpoint.resolve()],
                local._arquivos_origem_importados(ficha, base / "biblioteca"))

    def test_limpeza_recupera_word_legado_pelo_historico_de_importacao(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = pathlib.Path(td) / "livros"
            c = local.inicializar(raiz)
            word = c["entrada"] / "Livro.docx"
            word.write_bytes(b"word")
            digest = "a" * 64
            ficha = c["metadados"] / "livro.json"
            local.salvar_json(ficha, {
                "titulo": "Livro", "motivo_liberacao_espaco":
                "duplicidade confirmada pela consulta prévia"})
            catalogo = local.carregar_catalogo(c)
            catalogo["livros"][digest] = {
                "hash_sha256": digest, "arquivo": "Livro.pdf", "caminho": "",
                "estado": "duplicado local - arquivos liberados",
                "metadados": local.relativo(c, ficha), "id_remoto": 10,
                "arquivos_liberados_em": "2026-08-19T12:00:00"}
            local.salvar_catalogo(c, catalogo)
            local.salvar_json(c["controle"] / "importacoes-organizadas.json", {
                "itens": {str(word): {"hash_sha256": digest,
                                       "pdf_entrada": ""}}})
            simulacao = local.liberar_espaco(raiz)
            self.assertEqual(1, simulacao["livros"])
            self.assertIn(local.relativo(c, word),
                          simulacao["itens"][0]["arquivos"])

    def test_limpeza_nunca_remove_a_pasta_principal_de_entrada(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as lixo:
            raiz = pathlib.Path(td) / "livros"
            c = local.inicializar(raiz)
            word = c["entrada"] / "Livro.docx"
            word.write_bytes(b"word")
            digest = "b" * 64
            ficha = c["metadados"] / "livro.json"
            local.salvar_json(ficha, {
                "titulo": "Livro", "pasta_origem_importacao": str(c["entrada"]),
                "arquivos_origem_importacao": [str(word)]})
            catalogo = local.carregar_catalogo(c)
            catalogo["livros"][digest] = {
                "hash_sha256": digest, "arquivo": "Livro.pdf", "caminho": "",
                "estado": "cadastrado", "metadados": local.relativo(c, ficha),
                "id_remoto": 81}
            local.salvar_catalogo(c, catalogo)
            local.salvar_json(c["controle"] / "fila-envio-api.json", {
                "itens": [{"ficha": local.relativo(c, ficha),
                           "estado": "cadastrado", "id_remoto": 81,
                           "titulo": "Livro"}]})
            local.liberar_espaco(raiz, executar=True, lixeira=lixo)
            self.assertFalse(word.exists())
            self.assertTrue(c["entrada"].is_dir())

    def test_limpeza_preserva_outros_livros_na_mesma_pasta_de_autor(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as lixo:
            base = pathlib.Path(td)
            raiz = base / "biblioteca"
            pasta_autor = base / "entrada" / "Mesmo Autor"
            pasta_autor.mkdir(parents=True)
            livro_a = [pasta_autor / "A.pdf", pasta_autor / "A.opf"]
            livro_b = [pasta_autor / "B.pdf", pasta_autor / "B.opf"]
            for arquivo in livro_a + livro_b:
                arquivo.write_bytes(arquivo.name.encode())
            c = local.inicializar(raiz)
            copia = c["pronto"] / "A.pdf"
            copia.write_bytes(b"copia A")
            ficha = c["metadados"] / "A.json"
            local.salvar_json(ficha, {
                "titulo": "A", "pdf_original": local.relativo(c, copia),
                "pasta_origem_importacao": str(pasta_autor),
                "arquivos_origem_importacao": [str(p) for p in livro_a],
            })
            catalogo = local.carregar_catalogo(c)
            catalogo["livros"]["A"] = {
                "estado": "cadastrado", "caminho": local.relativo(c, copia),
                "metadados": local.relativo(c, ficha), "tamanho_bytes": 7}
            local.salvar_catalogo(c, catalogo)
            local.salvar_json(c["controle"] / "fila-envio-api.json", {
                "itens": [{"ficha": local.relativo(c, ficha),
                           "estado": "cadastrado", "id_remoto": 9,
                           "titulo": "A"}]})

            local.liberar_espaco(raiz, executar=True, lixeira=lixo)

            self.assertTrue(pasta_autor.is_dir())
            self.assertFalse(any(p.exists() for p in livro_a))
            self.assertTrue(all(p.exists() for p in livro_b))

    def test_limpeza_remove_pastas_com_apenas_ds_store_mesmo_sem_livros(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as lixo:
            c = local.inicializar(pathlib.Path(td) / "livros")
            autor = c["entrada"] / "Autor" / "Livro"
            autor.mkdir(parents=True)
            (autor / ".DS_Store").write_bytes(b"finder")
            (autor.parent / ".DS_Store").write_bytes(b"finder autor")

            simulacao = local.liberar_espaco(c["raiz"])
            self.assertEqual(0, simulacao["livros"])
            self.assertIn("00-ENTRADA/Autor/Livro",
                          simulacao["pastas_vazias"])
            self.assertTrue(autor.exists())

            local.liberar_espaco(c["raiz"], executar=True, lixeira=lixo)
            self.assertFalse((c["entrada"] / "Autor").exists())
            self.assertTrue(c["entrada"].is_dir())
            self.assertEqual(2, len(list(pathlib.Path(lixo).iterdir())))

    def test_limpeza_nao_remove_pasta_que_ainda_tem_livro(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as lixo:
            c = local.inicializar(pathlib.Path(td) / "livros")
            autor = c["entrada"] / "Autor"
            autor.mkdir()
            livro = autor / "mantido.pdf"
            livro.write_bytes(b"%PDF-mantido")
            (autor / ".DS_Store").write_bytes(b"finder")

            simulacao = local.liberar_espaco(c["raiz"])
            self.assertNotIn("00-ENTRADA/Autor", simulacao["pastas_vazias"])
            local.liberar_espaco(c["raiz"], executar=True, lixeira=lixo)

            self.assertTrue(autor.is_dir())
            self.assertTrue(livro.is_file())
            self.assertTrue((autor / ".DS_Store").is_file())


class LiberacaoAbrangeTodasAsFilasTest(unittest.TestCase):
    """Regressoes de liberacao de espaco, todas vistas no acervo real.

    Tres desencontros diferentes prendiam itens, e nenhum aparecia:

      1. so a fila principal era lida - documentos, academicos e revistas
         tem filas proprias e nunca eram varridos;
      2. exigia-se id_remoto, que a resposta de BUSCA do Biblio nao traz,
         embora o estado ja seja confirmacao contra a base;
      3. a fila principal chama a ficha de "ficha" e as especificas de
         "metadados" - a busca so procurava por um dos nomes.
    """

    def _acervo(self, td, nome_fila, chave_ficha, estado, id_remoto=None):
        raiz = pathlib.Path(td) / "livros"
        c = local.inicializar(raiz)
        pdf = c["documentos"] / "artigo.pdf" if "documentos" in c \
            else c["pronto"] / "artigo.pdf"
        pdf.parent.mkdir(parents=True, exist_ok=True)
        pdf.write_bytes(b"%PDF-artigo")
        ficha = c["metadados"] / "artigo.json"
        local.salvar_json(ficha, {"titulo": "Artigo",
                                  "pdf_original": local.relativo(c, pdf)})
        catalogo = local.carregar_catalogo(c)
        catalogo["livros"] = {"a": {
            "hash_sha256": "a", "estado": estado,
            "caminho": local.relativo(c, pdf),
            "metadados": local.relativo(c, ficha),
            "tamanho_bytes": pdf.stat().st_size}}
        local.salvar_catalogo(c, catalogo)
        item = {chave_ficha: local.relativo(c, ficha), "estado": estado,
                "titulo": "Artigo"}
        if id_remoto is not None:
            item["id_remoto"] = id_remoto
        local.salvar_json(c["controle"] / nome_fila, {"itens": [item]})
        return raiz, pdf

    def test_fila_especifica_de_documentos_tambem_e_varrida(self):
        nome = local.api_envio.FILAS_ESPECIFICAS["documentos"]
        with tempfile.TemporaryDirectory() as td:
            raiz, _ = self._acervo(td, nome, "metadados",
                                   "duplicado confirmado por ISBN")
            resumo = local.liberar_espaco(raiz)
            self.assertEqual(1, resumo["livros"],
                             "duplicado confirmado em fila especifica deve ser liberavel")

    def test_liberacao_atualiza_estado_na_fila_especifica(self):
        nome = local.api_envio.FILAS_ESPECIFICAS["documentos"]
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as lixo:
            raiz, pdf = self._acervo(td, nome, "metadados",
                                     "duplicado confirmado por ISBN")
            c = local.inicializar(raiz)
            local.liberar_espaco(raiz, executar=True, lixeira=lixo)
            self.assertFalse(pdf.exists())
            fila = json.loads((c["controle"] / nome).read_text(encoding="utf-8"))
            self.assertEqual([], fila["itens"])

    def test_estado_confirmado_dispensa_id_remoto(self):
        # O estado so e atribuido quando a consulta ao Biblio confirma;
        # o id_remoto falta apenas porque a resposta de busca nao o traz.
        with tempfile.TemporaryDirectory() as td:
            raiz, _ = self._acervo(td, "fila-envio-api.json", "ficha",
                                   "duplicado confirmado por ISBN")
            self.assertEqual(1, local.liberar_espaco(raiz)["livros"])

    def test_estado_que_pede_conferencia_continua_travado(self):
        with tempfile.TemporaryDirectory() as td:
            raiz, pdf = self._acervo(td, "fila-envio-api.json", "ficha",
                                     "já existente na API - conferir vínculo")
            resumo = local.liberar_espaco(raiz)
            self.assertEqual(0, resumo["livros"])
            self.assertTrue(pdf.exists())

    def test_vinculo_com_id_e_consulta_bibliografica_pode_ser_liberado(self):
        with tempfile.TemporaryDirectory() as td:
            raiz, pdf = self._acervo(
                td, "fila-envio-api.json", "ficha",
                "já existente na API - conferir vínculo", id_remoto=11171)
            caminho = raiz / "_controle" / "fila-envio-api.json"
            fila = json.loads(caminho.read_text(encoding="utf-8"))
            fila["itens"][0]["consulta_previa_api"] = {
                "encontrado": True,
                "id": 11171,
                "confirmado_por": "titulo_autor_aproximado",
            }
            local.salvar_json(caminho, fila)
            resumo = local.liberar_espaco(raiz)
            self.assertEqual(1, resumo["livros"])
            self.assertEqual("duplicidade confirmada pela API",
                             resumo["itens"][0]["motivo"])
            self.assertTrue(pdf.exists(), "a simulação não remove o arquivo")

    def test_confirmacao_por_isbn_exige_numero_identico(self):
        self.assertTrue(local.api_envio.consulta_confirmada_por_isbn({
            "encontrado": True, "isbn": "9786501248462",
            "criterios_enviados": {"isbn": "978-65-01-24846-2"}}))
        self.assertFalse(local.api_envio.consulta_confirmada_por_isbn({
            "encontrado": True, "isbn": "9786501248462",
            "criterios_enviados": {"isbn": "9788535606432"}}))

    def test_orfaos_sao_reportados_e_nao_removidos(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = pathlib.Path(td) / "livros"
            c = local.inicializar(raiz)
            orfa = c["capas"] / "ninguem-referencia.jpg"
            orfa.write_bytes(b"capa orfa")
            resumo = local.liberar_espaco(raiz)
            nomes = [o["arquivo"] for o in resumo.get("orfaos", [])]
            self.assertTrue(any("ninguem-referencia" in n for n in nomes))
            self.assertTrue(orfa.exists(), "simulacao nunca remove")

    def test_preparado_com_nome_semelhante_mas_sem_vinculo_e_orfao(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = pathlib.Path(td) / "livros"
            c = local.inicializar(raiz)
            preparado = c["preparados"] / "Livro-ab12cd34.pdf"
            preparado.write_bytes(b"preparado antigo")
            catalogo = local.carregar_catalogo(c)
            catalogo["livros"]["a" * 64] = {
                "arquivo": "Livro.pdf", "caminho": "",
                "estado": "cadastrado - arquivos locais liberados",
                "metadados": "", "hash_sha256": "a" * 64,
            }
            local.salvar_catalogo(c, catalogo)

            resumo = local.liberar_espaco(raiz)

            self.assertIn(
                local.relativo(c, preparado),
                [item["arquivo"] for item in resumo["orfaos"]])

    def test_preparado_exatamente_referenciado_e_preservado(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = pathlib.Path(td) / "livros"
            c = local.inicializar(raiz)
            preparado = c["preparados"] / "Livro-ab12cd34.pdf"
            preparado.write_bytes(b"preparado ativo")
            ficha = c["metadados"] / "livro.json"
            local.salvar_json(ficha, {
                "pdf_preparado": local.relativo(c, preparado)})
            catalogo = local.carregar_catalogo(c)
            catalogo["livros"]["b" * 64] = {
                "arquivo": "Livro.pdf", "caminho": "10-REVISAO/Livro.pdf",
                "estado": "analisado", "metadados": local.relativo(c, ficha),
                "hash_sha256": "b" * 64,
            }
            local.salvar_catalogo(c, catalogo)

            resumo = local.liberar_espaco(raiz)

            self.assertNotIn(
                local.relativo(c, preparado),
                [item["arquivo"] for item in resumo["orfaos"]])

    def test_execucao_remove_orfaos_e_preserva_referenciados(self):
        with tempfile.TemporaryDirectory() as td:
            base = pathlib.Path(td)
            raiz = base / "livros"
            lixo = base / "lixeira"
            c = local.inicializar(raiz)
            orfao = c["preparados"] / "antigo-1234abcd.pdf"
            orfao.write_bytes(b"orfao")
            ativo = c["preparados"] / "ativo-5678abcd.pdf"
            ativo.write_bytes(b"ativo")
            ficha = c["metadados"] / "ativo.json"
            local.salvar_json(ficha, {
                "pdf_preparado": local.relativo(c, ativo)})
            catalogo = local.carregar_catalogo(c)
            catalogo["livros"]["c" * 64] = {
                "arquivo": "ativo.pdf", "caminho": "10-REVISAO/ativo.pdf",
                "estado": "analisado", "metadados": local.relativo(c, ficha),
                "hash_sha256": "c" * 64,
            }
            local.salvar_catalogo(c, catalogo)

            local.liberar_espaco(raiz, executar=True, lixeira=lixo)

            self.assertFalse(orfao.exists())
            self.assertTrue(ativo.exists())
            manifesto = json.loads((c["controle"] /
                                     "manifesto-liberacao-espaco.json").read_text())
            removidos = manifesto["operacoes"][-1]["orfaos_removidos"]
            self.assertEqual(local.relativo(c, orfao), removidos[0]["origem"])


if __name__ == "__main__":
    unittest.main()
