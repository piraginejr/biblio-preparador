#!/usr/bin/env python3
import importlib.util
import json
import pathlib
import tempfile
import unittest
from unittest import mock


ARQUIVO = pathlib.Path(__file__).with_name("enviar-livro-api.py")
SPEC = importlib.util.spec_from_file_location("enviar_livro_api", ARQUIVO)
api = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(api)


class EnviarLivroApiTest(unittest.TestCase):
    def test_sessao_api_mantem_verificacao_tls_com_intermediaria(self):
        self.assertTrue(api.CERTIFICADO_INTERMEDIARIO.is_file())
        sessao = api.criar_sessao_api()
        adaptador = sessao.get_adapter(
            "https://apibib.pibcuritiba.org.br/apibiblio.php")
        self.assertIsInstance(adaptador, api.AdaptadorTLSBiblio)

    def criar_ficha(self, raiz, nome, gerado_em, titulo=None):
        (raiz / "_metadados").mkdir(parents=True, exist_ok=True)
        (raiz / "_capas").mkdir(parents=True, exist_ok=True)
        pdf = raiz / f"{nome}.pdf"
        capa = raiz / "_capas" / f"{nome}.jpg"
        pdf.write_bytes(b"%PDF-teste")
        capa.write_bytes(b"imagem")
        ficha = {
            "titulo": titulo or nome, "isbn": nome,
            "nmAutor0": "Autor, Teste", "idioma": "por",
            "situacao": "pronto para cadastro", "status_ocr": "OCR aprovado",
            "conflitos": "", "pendencias": "", "gerado_em": gerado_em,
            "pdf_original": f"{raiz.name}/{nome}.pdf",
            "capa": f"{raiz.name}/_capas/{nome}.jpg",
        }
        caminho = raiz / "_metadados" / f"{nome}.json"
        caminho.write_text(json.dumps(ficha), encoding="utf-8")
        return caminho, pdf

    def test_nome_bibliografico_volta_ao_formato_natural(self):
        self.assertEqual("Robson Rodovalho", api.nome_natural(
            "Rodovalho, Robson"))
        self.assertEqual("Paul David Tripp", api.nome_natural(
            "Tripp, Paul David"))

    def test_mapeamento_publico_e_autor(self):
        payload = api.montar_payload({
            "titulo": "Livro", "nmAutor0": "Rodovalho, Robson",
            "idioma": "por", "tipoAssunto1": "Teologia",
            "subTitulo": "Subtítulo", "cdd": "230",
        })
        self.assertEqual("0", payload["categoria"])
        self.assertEqual("1", payload["tipo"])
        self.assertEqual("portugues", payload["lingua"])
        self.assertEqual("Subtítulo", payload["stitle"])
        self.assertIn("Robson Rodovalho", payload["autores"])
        self.assertNotIn("titulo_publicacao", payload)

    def test_codigos_de_tipo_e_categoria_confirmados_pelo_operador(self):
        self.assertEqual({
            "livro": "1", "revista": "2", "artigo de revista": "3",
            "artigo de jornal": "4", "documento": "5",
            "áudio": "6", "vídeo": "7",
        }, api.TIPOS_API)
        self.assertEqual({"público": "0", "restrito": "1"},
                         api.CATEGORIAS_API)

    def test_documento_usa_tipo_cinco_e_aceita_fila_especifica(self):
        ficha = {
            "titulo": "Relatório", "tipo_documento": "documento",
            "situacao": "aguardando cadastro específico",
            "status_ocr": "OCR aprovado", "conflitos": "",
            "pendencias": "aguardar endpoint de artigos/documentos",
        }
        payload = api.montar_payload(ficha, tipo_api="documento")
        self.assertEqual("5", payload["tipo"])
        self.assertEqual("0", payload["categoria"])

    def test_apostila_sem_editora_e_data_pode_ser_documento(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = pathlib.Path(td)
            pdf, capa = raiz / "apostila.pdf", raiz / "apostila.jpg"
            pdf.write_bytes(b"%PDF-conteudo")
            capa.write_bytes(b"imagem")
            ficha = {
                "titulo": "Pregação Expositiva Temática",
                "tipo_documento": "apostila",
                "situacao": "aguardando cadastro específico",
                "status_ocr": "OCR aprovado", "conflitos": "",
                "pendencias": "editora | data de publicacao",
            }
            self.assertEqual([], api.validar(
                ficha, pdf, capa, tipo_api="documento"))

    def test_apresentacao_so_com_titulo_pode_ser_documento(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = pathlib.Path(td)
            pdf, capa = raiz / "slides.pdf", raiz / "slides.jpg"
            pdf.write_bytes(b"%PDF-conteudo")
            capa.write_bytes(b"imagem")
            ficha = {
                "titulo": "La Economía del Reino",
                "tipo_documento": "apresentação",
                "situacao": "aguardando cadastro específico",
                "status_ocr": "OCR aprovado",
                "conflitos": "autor parece fragmento do texto",
                "pendencias": "",
            }
            self.assertEqual([], api.validar(
                ficha, pdf, capa, tipo_api="documento"))

    def test_documento_com_titulo_valido_nao_bloqueia_por_outros_metadados(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = pathlib.Path(td)
            pdf, capa = raiz / "documento.pdf", raiz / "documento.jpg"
            pdf.write_bytes(b"%PDF-conteudo")
            capa.write_bytes(b"imagem")
            ficha = {
                "titulo": "A História dos Batistas",
                "tipo_documento": "documento",
                "situacao": "aguardando cadastro específico",
                "status_ocr": "OCR aprovado",
                "conflitos": "autor divergente",
                "pendencias": "autor | editora | data de publicacao",
            }
            self.assertEqual([], api.validar(
                ficha, pdf, capa, tipo_api="documento"))

    def test_documento_nao_aceita_resumo_como_titulo(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = pathlib.Path(td)
            pdf, capa = raiz / "documento.pdf", raiz / "documento.jpg"
            pdf.write_bytes(b"%PDF-conteudo")
            capa.write_bytes(b"imagem")
            ficha = {
                "titulo": "Resumo: este texto descreve o conteúdo do documento",
                "tipo_documento": "documento",
                "situacao": "aguardando cadastro específico",
                "status_ocr": "OCR aprovado", "conflitos": "",
                "pendencias": "",
            }
            erros = api.validar(ficha, pdf, capa, tipo_api="documento")
            self.assertIn("titulo documental parece resumo ou trecho de OCR",
                          erros)

    def test_trabalho_academico_ainda_exige_conflitos_resolvidos(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = pathlib.Path(td)
            pdf, capa = raiz / "tese.pdf", raiz / "tese.jpg"
            pdf.write_bytes(b"%PDF-conteudo")
            capa.write_bytes(b"imagem")
            ficha = {
                "titulo": "História dos Batistas",
                "tipo_documento": "trabalho acadêmico",
                "situacao": "aguardando cadastro específico",
                "status_ocr": "OCR aprovado", "conflitos": "título incerto",
                "pendencias": "",
            }
            self.assertIn("a ficha ainda contem conflitos", api.validar(
                ficha, pdf, capa, tipo_api="documento"))

    def test_envio_bloqueia_aviso_de_direitos_autorais_como_titulo(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = pathlib.Path(td)
            pdf, capa = raiz / "livro.pdf", raiz / "livro.jpg"
            pdf.write_bytes(b"%PDF-conteudo")
            capa.write_bytes(b"imagem")
            ficha = {
                "titulo": ("TODOS OS DIREITOS RESERVADOS - PROIBIDA A "
                           "REPRODUÇÃO TOTAL OU PARCIAL DA OBRA"),
                "tipo_documento": "livro",
                "situacao": "pronto para cadastro",
                "status_ocr": "OCR aprovado", "conflitos": "",
                "pendencias": "",
            }
            erros = api.validar(ficha, pdf, capa)
            self.assertTrue(any("direitos autorais" in erro for erro in erros))

    def test_artigo_usa_tipo_tres_sem_fingir_ser_livro(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = pathlib.Path(td)
            pdf, capa = raiz / "artigo.pdf", raiz / "artigo.jpg"
            pdf.write_bytes(b"%PDF-conteudo")
            capa.write_bytes(b"imagem")
            ficha = {
                "titulo": "Artigo Batista", "tipo_documento": "artigo",
                "situacao": "aguardando cadastro específico",
                "status_ocr": "OCR aprovado", "conflitos": "",
                "pendencias": "aguardar endpoint de artigos/documentos",
            }
            self.assertEqual([], api.validar(
                ficha, pdf, capa, tipo_api="artigo de revista"))
            self.assertEqual("3", api.montar_payload(
                ficha, tipo_api="artigo de revista")["tipo"])

    def test_revista_completa_usa_tipo_dois(self):
        ficha = {
            "titulo": "Voice", "tipo_documento": "revista",
            "situacao": "aguardando cadastro específico",
            "status_ocr": "OCR aprovado", "conflitos": "",
            "pendencias": "aguardar endpoint de revistas/periódicos",
        }
        payload = api.montar_payload(ficha, tipo_api="revista")
        self.assertEqual("2", payload["tipo"])
        self.assertEqual("0", payload["categoria"])

    def test_edicao_vazia_vira_primeira_edicao_presumida(self):
        payload = api.montar_payload({"titulo": "Livro", "edicao": ""})
        self.assertEqual("1ª edição (presumida)", payload["edicao"])

    def test_documento_sem_edicao_nao_recebe_primeira_edicao_ficticia(self):
        payload = api.montar_payload(
            {"titulo": "Documento", "edicao": ""}, tipo_api="documento")
        self.assertNotIn("edicao", payload)

    def test_consulta_previa_normaliza_isbn_e_nao_envia_arquivos(self):
        resposta = mock.Mock(status_code=200)
        resposta.json.return_value = {
            "encontrado": True, "correspondencia": "exata", "id": 20095,
            "titulo": "Livro", "autores": ["Autor, Teste"],
            "isbn": "9788512345678", "total_matches": 1,
        }
        sessao = mock.Mock()
        sessao.post.return_value = resposta
        resultado = api.consultar_livro(
            sessao, "segredo", isbn="978-85-12345-67-8",
            titulo=" Livro ", autores=["Autor, Teste"], exato=False)
        self.assertTrue(resultado["encontrado"])
        _, kwargs = sessao.post.call_args
        self.assertEqual("9788512345678", kwargs["json"]["isbn"])
        self.assertEqual(["Autor, Teste"], kwargs["json"]["autores"])
        self.assertNotIn("files", kwargs)
        self.assertEqual("segredo", kwargs["headers"]["X-API-Key"])

    def test_somente_isbn_devolvido_igual_autoriza_descarte(self):
        consulta = {
            "encontrado": True, "isbn": "85-7367-560-8",
            "criterios_enviados": {"isbn": "8573675608"},
        }
        self.assertTrue(api.consulta_confirmada_por_isbn(consulta))
        consulta["criterios_enviados"] = {"titulo": "Enciclopédia"}
        self.assertFalse(api.consulta_confirmada_por_isbn(consulta))
        consulta["criterios_enviados"] = {"isbn": "9780000000002"}
        self.assertFalse(api.consulta_confirmada_por_isbn(consulta))

    def test_isbn_divergente_identifica_outra_edicao_e_nao_bloqueia(self):
        consulta = {
            "encontrado": True, "correspondencia": "aproximada",
            "isbn": "0829709908",
            "criterios_enviados": {"isbn": "9788573677379",
                                     "titulo": "profecia"},
        }
        self.assertTrue(api.consulta_com_isbn_divergente(consulta))
        self.assertFalse(api.consulta_bloqueia_envio(consulta))

        consulta["isbn"] = "978-85-7367-737-9"
        self.assertFalse(api.consulta_com_isbn_divergente(consulta))
        self.assertTrue(api.consulta_bloqueia_envio(consulta))

    def test_titulo_exato_unico_e_autor_confirma_livro_sem_isbn(self):
        consulta = {
            "encontrado": True, "correspondencia": "exata",
            "total_matches": 1, "titulo": "COLUNAS BATISTAS NO BRASIL",
            "autores": ["COSTA, Delcio"], "isbn": "",
            "criterios_enviados": {
                "titulo": "Colunas Batistas no Brasil",
                "autores": ["Costa, Délcio"],
            },
        }
        self.assertTrue(api.consulta_confirmada_por_titulo_autor(consulta))

    def test_titulo_autor_nao_confirma_resultado_multiplo_ou_autor_diferente(self):
        consulta = {
            "encontrado": True, "correspondencia": "exata",
            "total_matches": 2, "titulo": "Livro",
            "autores": ["Silva, João"],
            "criterios_enviados": {
                "titulo": "Livro", "autores": ["Silva, João"]},
        }
        self.assertFalse(api.consulta_confirmada_por_titulo_autor(consulta))
        consulta["total_matches"] = 1
        consulta["autores"] = ["Souza, José"]
        self.assertFalse(api.consulta_confirmada_por_titulo_autor(consulta))

    def test_documento_pode_comparar_titulo_exato_unico_sem_autor(self):
        consulta = {
            "encontrado": True, "correspondencia": "exata",
            "total_matches": 1, "titulo": "Curso de Estudos da Oração Bíblica",
            "autores": [],
            "criterios_enviados": {
                "titulo": "Curso de Estudos da Oração Bíblica"},
        }
        self.assertTrue(api.consulta_corresponde_ao_titulo_exato(consulta))
        consulta["total_matches"] = 2
        self.assertFalse(api.consulta_corresponde_ao_titulo_exato(consulta))

    def test_pdf_acima_da_meta_e_abaixo_do_teto_e_valido(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = pathlib.Path(td)
            pdf = raiz / "grande.pdf"
            capa = raiz / "capa.jpg"
            with pdf.open("wb") as arquivo:
                arquivo.write(b"%PDF-")
                arquivo.seek(api.LIMITE_OTIMIZACAO_BYTES + 1_000_000)
                arquivo.write(b"0")
            capa.write_bytes(b"imagem")
            ficha = {"titulo": "Livro", "situacao": "pronto para cadastro",
                     "status_ocr": "OCR aprovado", "conflitos": "",
                     "pendencias": "", "tipo_documento": "livro"}
            self.assertEqual([], api.validar(ficha, pdf, capa))

    def test_apostrofos_sao_removidos_somente_do_payload_da_api(self):
        payload = api.montar_payload({
            "titulo": "Pastor's Library",
            "editora": "Charles Scribner’s Sons",
            "nmAutor0": "O'Connor, James",
        })
        self.assertEqual("Pastors Library", payload["titulo"])
        self.assertEqual("Charles Scribners Sons", payload["editor"])
        self.assertIn("OConnor", payload["autores"])
        self.assertNotIn("'", json.dumps(payload, ensure_ascii=False))
        self.assertNotIn("’", json.dumps(payload, ensure_ascii=False))

    def test_mapeamento_preserva_multiplos_autores_e_papeis(self):
        payload = api.montar_payload({
            "titulo": "Coletânea", "idioma": "por",
            "nmAutor0": "Primeiro, Autor",
            "autores": [
                {"nome": "Primeiro, Autor", "desc": "Organizador"},
                {"nome": "Segundo, Autor", "desc": "Autor"},
            ],
        })
        autores = json.loads(payload["autores"])
        self.assertEqual([
            {"nome": "Autor Primeiro", "desc": "Organizador"},
            {"nome": "Autor Segundo", "desc": "Autor"},
        ], autores)

    def test_trabalho_academico_nunca_entra_na_fila_de_livros(self):
        ficha = {
            "tipo_documento": "tese", "titulo": "Pesquisa",
            "situacao": "pronto para cadastro", "status_ocr": "OCR aprovado",
            "conflitos": "", "pendencias": "",
        }
        self.assertFalse(api.ficha_apta(ficha))

    def test_caminho_antigo_funciona_fora_da_raiz(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = pathlib.Path(td) / "livros"
            ficha, pdf = self.criar_ficha(raiz, "um", "2026-01-01")
            self.assertEqual(pdf.resolve(), api.caminho_local("livros/um.pdf", ficha))

    def test_fila_preserva_ordem_e_reconcilia_cadastrado(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = pathlib.Path(td) / "livros"
            ficha_b, pdf_b = self.criar_ficha(raiz, "b", "2026-02-01")
            ficha_a, _ = self.criar_ficha(raiz, "a", "2026-01-01")
            controle = {"versao": 1, "envios": {"hash": {
                "arquivo": str(pdf_b.resolve()), "estado": "cadastrado",
                "id_remoto": 99, "http_status": 201,
            }}}
            api.salvar_json(raiz / "_controle" / api.NOME_CONTROLE, controle)
            fila, adicionados, _ = api.atualizar_fila(raiz)
            self.assertEqual(2, adicionados)
            self.assertEqual(["a", "b"], [i["titulo"] for i in fila["itens"]])
            self.assertEqual("pendente", fila["itens"][0]["estado"])
            self.assertEqual("cadastrado", fila["itens"][1]["estado"])
            self.assertEqual(99, fila["itens"][1]["id_remoto"])

    def test_reavaliacao_retira_pendente_inapto_sem_apagar_historico(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = pathlib.Path(td) / "livros"
            ficha_path, _ = self.criar_ficha(raiz, "a", "2026-01-01")
            fila, _, _ = api.atualizar_fila(raiz)
            self.assertEqual(1, len(fila["itens"]))
            ficha = json.loads(ficha_path.read_text(encoding="utf-8"))
            ficha["situacao"] = "conflito"
            ficha["conflitos"] = "titulo suspeito"
            ficha_path.write_text(json.dumps(ficha), encoding="utf-8")
            fila, _, _ = api.atualizar_fila(raiz)
            self.assertEqual([], fila["itens"])
            self.assertEqual(1, len(fila["retirados"]))
            self.assertEqual("a", fila["retirados"][0]["titulo"])

    def test_atualizacao_reativa_erro_local_apos_correcao(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = pathlib.Path(td) / "livros"
            self.criar_ficha(raiz, "corrigido", "2026-01-01")
            fila, _, _ = api.atualizar_fila(raiz)
            fila["itens"][0]["estado"] = "erro local - revisar"
            fila["itens"][0]["erro"] = "PDF nao encontrado"
            api.salvar_json(api.fila_da_raiz(raiz), fila)
            fila, _, _ = api.atualizar_fila(raiz)
            self.assertEqual("pendente", fila["itens"][0]["estado"])
            self.assertNotIn("erro", fila["itens"][0])

    def test_ficha_corrigida_reativa_erro_500_e_preserva_historico(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = pathlib.Path(td) / "livros"
            ficha_path, pdf = self.criar_ficha(
                raiz, "corrigido-500", "2026-01-02T12:00:00")
            api.salvar_json(raiz / "_controle" / api.NOME_CONTROLE, {
                "versao": 1, "envios": {"digest": {
                    "arquivo": str(pdf.resolve()),
                    "estado": "erro confirmado - revisar",
                    "http_status": 500,
                    "concluido_em": "2026-01-01T12:00:00",
                }}})
            fila, _, _ = api.atualizar_fila(raiz)
            self.assertEqual("pendente", fila["itens"][0]["estado"])
            controle = api.carregar_controle(
                raiz / "_controle" / api.NOME_CONTROLE)
            self.assertNotIn("digest", controle["envios"])
            self.assertEqual(1, len(
                controle["tentativas_anteriores"]["digest"]))

    def test_erro_500_sem_correcao_continua_bloqueado(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = pathlib.Path(td) / "livros"
            _, pdf = self.criar_ficha(
                raiz, "nao-corrigido", "2026-01-01T12:00:00")
            api.salvar_json(raiz / "_controle" / api.NOME_CONTROLE, {
                "versao": 1, "envios": {"digest": {
                    "arquivo": str(pdf.resolve()),
                    "estado": "erro confirmado - revisar",
                    "http_status": 500,
                    "concluido_em": "2026-01-02T12:00:00",
                }}})
            fila, _, _ = api.atualizar_fila(raiz)
            self.assertEqual("erro confirmado - revisar",
                             fila["itens"][0]["estado"])

    def test_atualizacao_nao_reabre_duplicado_que_ja_liberou_arquivos(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = pathlib.Path(td) / "livros"
            ficha, pdf = self.criar_ficha(raiz, "duplicado", "2026-01-01")
            api.salvar_json(raiz / "_controle" / api.NOME_CONTROLE, {
                "versao": 1, "envios": {"hash": {
                    "arquivo": str(pdf.resolve()),
                    "estado": "duplicado informado pela API - revisar",
                    "http_status": 400}}})
            api.salvar_json(api.fila_da_raiz(raiz), {
                "versao": 1, "itens": [{
                    "ficha": str(ficha.relative_to(raiz)),
                    "titulo": "duplicado",
                    "estado": "duplicado na API - arquivos locais liberados"}]})
            fila, _, _ = api.atualizar_fila(raiz)
            self.assertEqual("duplicado na API - arquivos locais liberados",
                             fila["itens"][0]["estado"])

    def test_isbn_corrigido_reativa_falsa_duplicidade_de_colecao(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = pathlib.Path(td) / "livros"
            ficha_path, pdf = self.criar_ficha(
                raiz, "beacon", "2026-08-18T12:00:00")
            ficha = json.loads(ficha_path.read_text(encoding="utf-8"))
            ficha["isbn"] = "9781563446078"
            ficha_path.write_text(json.dumps(ficha), encoding="utf-8")
            api.salvar_json(api.fila_da_raiz(raiz), {
                "versao": 1, "itens": [{
                    "ficha": str(ficha_path.relative_to(raiz)),
                    "titulo": "Comentario Beacon",
                    "isbn": "9781563446016",
                    "estado": "duplicado informado pela API - revisar",
                    "consulta_previa_api": {
                        "encontrado": True, "isbn": "9781563446016",
                        "criterios_enviados": {"isbn": "9781563446016"},
                    },
                }]})
            api.salvar_json(raiz / "_controle" / api.NOME_CONTROLE, {
                "versao": 1, "envios": {"digest": {
                    "arquivo": str(pdf.resolve()),
                    "isbn": "9781563446016",
                    "estado": "duplicado informado pela API - revisar",
                    "http_status": 400,
                }}})
            fila, _, _ = api.atualizar_fila(raiz)
            self.assertEqual("pendente", fila["itens"][0]["estado"])
            self.assertEqual("9781563446078", fila["itens"][0]["isbn"])
            self.assertNotIn("consulta_previa_api", fila["itens"][0])
            self.assertEqual(1, len(fila["retirados"]))
            controle = api.carregar_controle(
                raiz / "_controle" / api.NOME_CONTROLE)
            self.assertNotIn("digest", controle["envios"])
            self.assertEqual(
                "ISBN da edição corrigido",
                controle["tentativas_anteriores"]["digest"][0]["motivo_reabertura"])

    def test_atualizacao_reativa_aproximada_com_isbn_remoto_divergente(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = pathlib.Path(td) / "livros"
            ficha_path, _ = self.criar_ficha(
                raiz, "profecia", "2026-08-18T12:00:00")
            ficha = json.loads(ficha_path.read_text(encoding="utf-8"))
            ficha["isbn"] = "9788573677379"
            ficha_path.write_text(json.dumps(ficha), encoding="utf-8")
            api.salvar_json(api.fila_da_raiz(raiz), {
                "versao": 1, "itens": [{
                    "ficha": str(ficha_path.relative_to(raiz)),
                    "titulo": "profecia", "isbn": "9788573677379",
                    "estado": "já existente na API - conferir vínculo",
                    "id_remoto": 15849,
                    "consulta_previa_api": {
                        "encontrado": True, "correspondencia": "aproximada",
                        "isbn": "0829709908", "id": 15849,
                        "criterios_enviados": {"isbn": "9788573677379"},
                    },
                }]})
            fila, _, _ = api.atualizar_fila(raiz)
            item = fila["itens"][0]
            self.assertEqual("pendente", item["estado"])
            self.assertNotIn("id_remoto", item)
            self.assertNotIn("consulta_previa_api", item)
            self.assertIn("outra edição", item["motivo_reativacao"])
            self.assertEqual(
                "correspondência aproximada com ISBN divergente",
                fila["retirados"][0]["motivo"])

    def test_processamento_sequencial_atualiza_fila(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = pathlib.Path(td) / "livros"
            self.criar_ficha(raiz, "a", "2026-01-01")
            self.criar_ficha(raiz, "b", "2026-02-01")
            ids = iter((10, 11))

            def envio_falso(*args, **kwargs):
                remoto = next(ids)
                return {"estado": "cadastrado", "http_status": 201,
                        "id_remoto": remoto}

            with mock.patch.object(api, "enviar", side_effect=envio_falso):
                resultado = api.processar_fila(
                    raiz, chave="segredo-de-teste", intervalo=0)
            self.assertEqual(2, resultado["enviados"])
            fila = api.carregar_fila(api.fila_da_raiz(raiz))
            self.assertEqual([10, 11], [i["id_remoto"] for i in fila["itens"]])
            self.assertTrue(all(i["estado"] == "cadastrado" for i in fila["itens"]))

    def test_duplicado_barrado_no_envio_atualiza_catalogo_imediatamente(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = pathlib.Path(td) / "livros"
            ficha_path, _ = self.criar_ficha(
                raiz, "9788594115430", "2026-09-03T03:04:23",
                titulo="Bíblia Prazer da Palavra")
            (raiz / "_controle").mkdir(parents=True, exist_ok=True)
            api.salvar_json(raiz / "_controle" / "catalogo-local.json", {
                "livros": {"hash": {
                    "hash_sha256": "hash",
                    "arquivo": "biblia.pdf",
                    "estado": "pronto para cadastro",
                    "metadados": str(ficha_path.relative_to(raiz)),
                }}
            })
            resposta = {
                "encontrado": True,
                "correspondencia": "exata",
                "id": 20086,
                "isbn": "9788594115430",
                "criterios_enviados": {"isbn": "9788594115430"},
            }
            with mock.patch.object(api, "consultar_livro",
                                   return_value=resposta), \
                 mock.patch.object(api, "enviar") as enviar:
                resultado = api.processar_fila(
                    raiz, chave="segredo-de-teste", intervalo=0)

            enviar.assert_not_called()
            self.assertEqual(1, resultado["revisao"])
            catalogo = json.loads((raiz / "_controle" /
                                   "catalogo-local.json").read_text())
            registro = catalogo["livros"]["hash"]
            self.assertEqual("duplicado confirmado por ISBN",
                             registro["estado"])
            self.assertEqual(20086, registro["id_remoto"])

    def test_envio_continua_quando_api_encontra_outro_isbn(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = pathlib.Path(td) / "livros"
            ficha_path, _ = self.criar_ficha(
                raiz, "profecia", "2026-08-18T12:00:00")
            ficha = json.loads(ficha_path.read_text(encoding="utf-8"))
            ficha["isbn"] = "9788573677379"
            ficha_path.write_text(json.dumps(ficha), encoding="utf-8")
            consulta = {
                "encontrado": True, "correspondencia": "aproximada",
                "isbn": "0829709908", "id": 15849,
                "criterios_enviados": {"isbn": "9788573677379"},
            }
            registro = {"estado": "cadastrado", "http_status": 201,
                        "id_remoto": 30000}
            with mock.patch.object(api, "consultar_livro",
                                   return_value=consulta), \
                 mock.patch.object(api, "enviar", return_value=registro) as enviar:
                resultado = api.processar_fila(
                    raiz, chave="segredo-de-teste", intervalo=0)
            self.assertEqual(1, resultado["enviados"])
            enviar.assert_called_once()
            fila = api.carregar_fila(api.fila_da_raiz(raiz))
            self.assertEqual("cadastrado", fila["itens"][0]["estado"])
            self.assertEqual(1, len(
                fila["itens"][0]["consultas_nao_bloqueantes"]))

    def test_fila_especifica_envia_documento_sem_reprocessar_livro(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = pathlib.Path(td) / "livros"
            (raiz / "_controle").mkdir(parents=True)
            (raiz / "_metadados").mkdir()
            ficha = raiz / "_metadados" / "documento.json"
            ficha.write_text(json.dumps({"titulo": "Documento"}),
                             encoding="utf-8")
            api.salvar_json(raiz / "_controle" /
                            api.FILAS_ESPECIFICAS["documentos"], {
                "itens": [{
                    "hash_sha256": "d" * 64,
                    "titulo": "Documento", "tipo_documento": "apostila",
                    "tipo_api": "documento",
                    "metadados": "_metadados/documento.json",
                    "estado": "pronto para cadastro específico",
                }]})
            api.salvar_json(raiz / "_controle" / "catalogo-local.json", {
                "livros": {"d" * 64: {
                    "hash_sha256": "d" * 64,
                    "estado": "pronto para cadastro específico"}}})
            registro = {"estado": "cadastrado", "http_status": 201,
                        "id_remoto": 31000, "concluido_em": "2026-08-18"}
            with mock.patch.object(api, "enviar", return_value=registro) as enviar:
                resultado = api.processar_fila_especifica(
                    raiz, "documentos", chave="segredo-de-teste",
                    intervalo=0, realmente=True)
            self.assertEqual(1, resultado["enviados"])
            self.assertEqual("documento", enviar.call_args.kwargs["tipo_api"])
            catalogo = json.loads((raiz / "_controle" /
                                   "catalogo-local.json").read_text())
            self.assertEqual("cadastrado",
                             catalogo["livros"]["d" * 64]["estado"])

    def test_fila_especifica_incerto_nao_entra_tambem_como_pronto(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = pathlib.Path(td) / "livros"
            (raiz / "_controle").mkdir(parents=True)
            (raiz / "_metadados").mkdir()
            ficha = raiz / "_metadados" / "documento.json"
            ficha.write_text(json.dumps({"titulo": "Documento"}),
                             encoding="utf-8")
            digest = "d" * 64
            api.salvar_json(raiz / "_controle" /
                            api.FILAS_ESPECIFICAS["documentos"], {
                "itens": [{
                    "hash_sha256": digest, "titulo": "Documento",
                    "tipo_documento": "apostila", "tipo_api": "documento",
                    "metadados": "_metadados/documento.json",
                    "estado": "pronto para cadastro específico",
                }]})
            api.salvar_json(raiz / "_controle" / api.NOME_CONTROLE, {
                "envios": {digest: {
                    "estado": "resultado incerto - nao reenviar sem conferencia"}}})
            registro = {
                "estado": "cadastrado", "http_status": 200,
                "id_remoto": 20563,
                "reconciliado_por": "consulta posterior sem reenvio",
            }
            with mock.patch.object(api, "enviar", return_value=registro) as enviar:
                resultado = api.processar_fila_especifica(
                    raiz, "documentos", chave="segredo-de-teste",
                    intervalo=0, realmente=True)
            enviar.assert_called_once()
            self.assertEqual(0, resultado["enviados"])
            self.assertEqual(1, resultado["reconciliados"])

    def test_fila_especifica_consulta_titulo_antes_do_upload(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = pathlib.Path(td) / "livros"
            (raiz / "_controle").mkdir(parents=True)
            (raiz / "_metadados").mkdir()
            ficha = raiz / "_metadados" / "documento.json"
            ficha.write_text(json.dumps({
                "titulo": "Documento existente", "autores": []}),
                encoding="utf-8")
            digest = "f" * 64
            api.salvar_json(raiz / "_controle" /
                            api.FILAS_ESPECIFICAS["documentos"], {
                "itens": [{
                    "hash_sha256": digest, "titulo": "Documento existente",
                    "tipo_documento": "documento", "tipo_api": "documento",
                    "metadados": "_metadados/documento.json",
                    "estado": "pronto para cadastro específico",
                }]})
            consulta = {
                "encontrado": True, "correspondencia": "exata", "id": 99,
                "total_matches": 1, "titulo": "Documento existente",
                "autores": [], "isbn": "",
                "criterios_enviados": {"titulo": "Documento existente"},
            }
            with mock.patch.object(api, "consultar_livro",
                                   return_value=consulta), \
                 mock.patch.object(api, "enviar") as enviar:
                resultado = api.processar_fila_especifica(
                    raiz, "documentos", chave="segredo-de-teste",
                    intervalo=0, realmente=True)
            enviar.assert_not_called()
            self.assertEqual(1, resultado["revisao"])
            fila = json.loads((raiz / "_controle" /
                               api.FILAS_ESPECIFICAS["documentos"]).read_text())
            self.assertEqual(api.ESTADO_DUPLICADO_TITULO,
                             fila["itens"][0]["estado"])

    def test_reconciliacao_sem_isbn_tenta_titulo_sem_autor(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = pathlib.Path(td) / "livros"
            (raiz / "_controle").mkdir(parents=True)
            (raiz / "_metadados").mkdir()
            ficha_path = raiz / "_metadados" / "documento.json"
            ficha_path.write_text(json.dumps({
                "titulo": "Documento", "nmAutor0": "Sobrenome, Autor",
            }), encoding="utf-8")
            digest = "e" * 64
            registro = {
                "estado": "resultado incerto - nao reenviar sem conferencia"}
            controle = {"envios": {digest: registro}}
            respostas = [
                {"encontrado": False, "total_matches": 0},
                {"encontrado": True, "correspondencia": "exata",
                 "total_matches": 1, "id": 20563, "isbn": None,
                 "criterios_enviados": {"titulo": "Documento"}},
            ]
            with mock.patch.object(api, "consultar_livro",
                                   side_effect=respostas) as consultar:
                resultado = api.reconciliar_resultado_incerto(
                    ficha_path, digest, controle, registro,
                    "segredo-de-teste", tipo_api="documento")
            self.assertEqual("cadastrado", resultado["estado"])
            self.assertEqual(20563, resultado["id_remoto"])
            self.assertEqual(2, consultar.call_count)

    def test_erro_isolado_nao_interrompe_os_proximos(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = pathlib.Path(td) / "livros"
            self.criar_ficha(raiz, "a", "2026-01-01")
            self.criar_ficha(raiz, "b", "2026-02-01")
            with mock.patch.object(api, "enviar", side_effect=RuntimeError("falha")):
                resultado = api.processar_fila(
                    raiz, chave="segredo-de-teste", intervalo=0)
            self.assertFalse(resultado["interrompido"])
            fila = api.carregar_fila(api.fila_da_raiz(raiz))
            self.assertEqual("erro local - revisar", fila["itens"][0]["estado"])
            self.assertEqual("erro local - revisar", fila["itens"][1]["estado"])
            self.assertEqual(2, resultado["falhas"])

    def test_resultado_incerto_fica_para_o_final_sem_bloquear_proximo(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = pathlib.Path(td) / "livros"
            _, pdf = self.criar_ficha(raiz, "a", "2026-01-01")
            self.criar_ficha(raiz, "b", "2026-02-01")
            api.salvar_json(raiz / "_controle" / api.NOME_CONTROLE, {
                "versao": 1, "envios": {"hash": {
                    "arquivo": str(pdf.resolve()),
                    "estado": "resultado incerto - nao reenviar sem conferencia",
                }}})
            def envio_falso(ficha, **kwargs):
                if pathlib.Path(ficha).stem == "a":
                    raise RuntimeError("resultado ainda incerto")
                return {"estado": "cadastrado", "http_status": 201,
                        "id_remoto": 30001}

            with mock.patch.object(api, "enviar", side_effect=envio_falso):
                resultado = api.processar_fila(
                    raiz, chave="segredo-de-teste", intervalo=0)
            self.assertFalse(resultado["interrompido"])
            self.assertEqual(1, resultado["enviados"])
            self.assertEqual(1, resultado["falhas"])
            fila = api.carregar_fila(api.fila_da_raiz(raiz))
            por_titulo = {item["titulo"]: item for item in fila["itens"]}
            self.assertEqual("cadastrado", por_titulo["b"]["estado"])
            self.assertIn("incerto", por_titulo["a"]["estado"])

    def test_envio_incerto_confirmado_por_consulta_nao_repete_upload(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = pathlib.Path(td) / "livros"
            ficha_path, pdf = self.criar_ficha(
                raiz, "documento", "2026-08-19T11:49:26")
            ficha = json.loads(ficha_path.read_text(encoding="utf-8"))
            ficha.update({"titulo": "Documento confirmado", "nmAutor0": "Autor",
                          "tipo_documento": "documento",
                          "situacao": "aguardando cadastro específico"})
            ficha_path.write_text(json.dumps(ficha), encoding="utf-8")
            digest = api.sha256(pdf)
            api.salvar_json(raiz / "_controle" / api.NOME_CONTROLE, {
                "versao": 1, "envios": {digest: {
                    "arquivo": str(pdf.resolve()),
                    "estado": "resultado incerto - nao reenviar sem conferencia",
                }}})
            consulta = {
                "encontrado": True, "correspondencia": "exata",
                "id": 20563, "total_matches": 1, "isbn": None,
                "criterios_enviados": {"titulo": "Documento confirmado"},
            }
            sessao = mock.Mock()
            with mock.patch.object(api, "consultar_livro",
                                   return_value=consulta) as consultar:
                resultado = api.enviar(
                    ficha_path, realmente=True, chave="segredo-de-teste",
                    sessao=sessao, tipo_api="documento")
            self.assertEqual("cadastrado", resultado["estado"])
            self.assertEqual(20563, resultado["id_remoto"])
            self.assertEqual("consulta posterior sem reenvio",
                             resultado["reconciliado_por"])
            consultar.assert_called_once()
            sessao.post.assert_not_called()

    def test_envio_incerto_nao_encontrado_e_reenviado_uma_vez(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = pathlib.Path(td) / "livros"
            ficha_path, pdf = self.criar_ficha(
                raiz, "documento", "2026-08-19T11:49:26")
            ficha = json.loads(ficha_path.read_text(encoding="utf-8"))
            ficha.update({"tipo_documento": "documento",
                          "situacao": "aguardando cadastro específico"})
            ficha_path.write_text(json.dumps(ficha), encoding="utf-8")
            digest = api.sha256(pdf)
            api.salvar_json(raiz / "_controle" / api.NOME_CONTROLE, {
                "versao": 1, "envios": {digest: {
                    "arquivo": str(pdf.resolve()),
                    "estado": "resultado incerto - nao reenviar sem conferencia",
                }}})
            resposta = mock.Mock(status_code=201)
            resposta.json.return_value = {"mensagem": "cadastrado", "id": 20564}
            sessao = mock.Mock()
            sessao.post.return_value = resposta
            with mock.patch.object(api, "consultar_livro", return_value={
                    "encontrado": False, "total_matches": 0}):
                resultado = api.enviar(
                    ficha_path, realmente=True, chave="segredo-de-teste",
                    sessao=sessao, tipo_api="documento")
            self.assertEqual("cadastrado", resultado["estado"])
            self.assertEqual(20564, resultado["id_remoto"])
            sessao.post.assert_called_once()
            controle = api.carregar_controle(
                raiz / "_controle" / api.NOME_CONTROLE)
            self.assertEqual(1, len(
                controle["tentativas_anteriores"][digest]))

    def test_reativa_apenas_antiga_rejeicao_de_isbn_e_preserva_historico(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = pathlib.Path(td) / "livros"
            ficha, pdf = self.criar_ficha(raiz, "antigo", "2026-01-01")
            api.salvar_json(raiz / "_controle" / api.NOME_CONTROLE, {
                "versao": 1, "envios": {
                    "isbn": {"arquivo": str(pdf),
                             "estado": "erro confirmado - revisar",
                             "http_status": 400,
                             "resposta": {"mensagem": "Campo isbn é obrigatório"}},
                    "duplicado": {"arquivo": "/outro.pdf",
                                  "estado": "duplicado informado pela API - revisar",
                                  "http_status": 400,
                                  "resposta": {"mensagem": "Arquivo ja existe"}},
                }})
            api.salvar_json(api.fila_da_raiz(raiz), {
                "versao": 1, "itens": [{
                    "ficha": str(ficha.relative_to(raiz)),
                    "estado": "erro confirmado - revisar", "http_status": 400,
                }]})
            self.assertEqual(1, api.reativar_rejeitados_isbn(raiz))
            controle = api.carregar_controle(
                raiz / "_controle" / api.NOME_CONTROLE)
            self.assertNotIn("isbn", controle["envios"])
            self.assertIn("duplicado", controle["envios"])
            self.assertEqual(1, len(controle["tentativas_anteriores"]["isbn"]))
            fila = api.carregar_fila(api.fila_da_raiz(raiz))
            self.assertEqual("pendente", fila["itens"][0]["estado"])

    def test_reativa_falha_tls_sem_resposta_e_preserva_historico(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = pathlib.Path(td) / "livros"
            ficha, pdf = self.criar_ficha(raiz, "tls", "2026-01-01")
            api.salvar_json(raiz / "_controle" / api.NOME_CONTROLE, {
                "versao": 1, "envios": {"digest": {
                    "arquivo": str(pdf),
                    "estado": "resultado incerto - nao reenviar sem conferencia",
                    "erro_local": "SSLError: CERTIFICATE_VERIFY_FAILED",
                }}})
            api.salvar_json(api.fila_da_raiz(raiz), {
                "versao": 1, "itens": [{
                    "ficha": str(ficha.relative_to(raiz)),
                    "estado": "resultado incerto - nao reenviar sem conferencia",
                }]})
            self.assertEqual(1, api.reativar_falhas_tls_locais(raiz))
            controle = api.carregar_controle(
                raiz / "_controle" / api.NOME_CONTROLE)
            self.assertNotIn("digest", controle["envios"])
            self.assertEqual(1, len(
                controle["tentativas_anteriores"]["digest"]))
            fila = api.carregar_fila(api.fila_da_raiz(raiz))
            self.assertEqual("pendente", fila["itens"][0]["estado"])

    def test_sucesso_aparece_no_catalogo_local(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = pathlib.Path(td) / "livros"
            (raiz / "_controle").mkdir(parents=True)
            api.salvar_json(raiz / "_controle" / "catalogo-local.json", {
                "livros": {"hash": {"hash_sha256": "hash", "arquivo": "a.pdf",
                                     "estado": "pronto para cadastro"}}})
            alterou = api.marcar_catalogo_cadastrado(
                raiz, "hash", {"id_remoto": 123,
                                "concluido_em": "2026-08-13T20:00:00"})
            self.assertTrue(alterou)
            catalogo = json.loads((raiz / "_controle" /
                                   "catalogo-local.json").read_text())
            self.assertEqual("cadastrado", catalogo["livros"]["hash"]["estado"])
            self.assertEqual(123, catalogo["livros"]["hash"]["id_remoto"])
            self.assertIn("id_remoto", (raiz / "_controle" /
                                        "catalogo-local.csv").read_text())

    def test_fila_reconcilia_catalogo_pela_ficha_e_marca_duplicado(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = pathlib.Path(td) / "livros"
            (raiz / "_controle").mkdir(parents=True)
            api.salvar_json(raiz / "_controle" / "catalogo-local.json", {
                "livros": {
                    "hash-original": {"estado": "pronto para cadastro",
                                      "metadados": "_metadados/a.json"},
                    "outro": {"estado": "pronto para cadastro",
                              "metadados": "_metadados/b.json"},
                }})
            fila = {"itens": [
                {"ficha": "_metadados/a.json", "estado": "cadastrado",
                 "id_remoto": 77},
                {"ficha": "_metadados/b.json",
                 "estado": "duplicado informado pela API - revisar"},
            ]}
            self.assertEqual(2, api.sincronizar_catalogo_com_fila(raiz, fila))
            catalogo = json.loads((raiz / "_controle" /
                                   "catalogo-local.json").read_text())
            self.assertEqual("cadastrado",
                             catalogo["livros"]["hash-original"]["estado"])
            self.assertEqual(77, catalogo["livros"]["hash-original"]["id_remoto"])
            self.assertEqual("já existente na API - conferir vínculo",
                             catalogo["livros"]["outro"]["estado"])

    def test_relatorio_documenta_rejeicao_sem_expor_chave(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = pathlib.Path(td) / "livros"
            ficha_path, pdf = self.criar_ficha(raiz, "antigo", "2026-01-01")
            ficha = json.loads(ficha_path.read_text())
            ficha.update({"isbn": "", "isbn_motivo": "sem ISBN - nao localizado",
                          "status_ocr": "OCR aprovado", "cobertura_ocr": 0.98,
                          "evidencias": {"isbn_candidatos": []}})
            ficha_path.write_text(json.dumps(ficha), encoding="utf-8")
            api.salvar_json(raiz / "_controle" / api.NOME_CONTROLE, {
                "versao": 1, "envios": {"hash": {
                    "sha256": "hash", "arquivo": str(pdf.resolve()),
                    "estado": "erro confirmado - revisar", "http_status": 400,
                    "endpoint": api.ENDPOINT, "iniciado_em": "inicio",
                    "concluido_em": "fim", "resposta": {
                        "erro": True, "mensagem": "Campo isbn é obrigatório"},
                }}})
            relatorio, caminhos = api.gerar_relatorio_rejeicoes(raiz)
            self.assertEqual(1, relatorio["total_rejeicoes"])
            caso = relatorio["casos"][0]
            self.assertEqual("ISBN_OBRIGATORIO_API",
                             caso["classificacao"]["codigo"])
            self.assertEqual("hash", caso["arquivo"]["pdf_sha256"])
            for caminho in caminhos.values():
                self.assertTrue(caminho.is_file())
            conteudo = caminhos["json"].read_text(encoding="utf-8")
            self.assertNotIn("segredo-de-teste", conteudo)
            self.assertIn("valor omitido", conteudo)

    def test_rascunho_usa_destinatario_e_impede_duplicacao(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = pathlib.Path(td) / "livros"
            ficha_path, pdf = self.criar_ficha(raiz, "antigo", "2026-01-01")
            ficha = json.loads(ficha_path.read_text())
            ficha.update({"isbn": "", "isbn_motivo": "sem ISBN",
                          "evidencias": {"isbn_candidatos": []}})
            ficha_path.write_text(json.dumps(ficha), encoding="utf-8")
            api.salvar_json(raiz / "_controle" / api.NOME_CONTROLE, {
                "versao": 1, "envios": {"hash": {
                    "sha256": "hash", "arquivo": str(pdf.resolve()),
                    "estado": "erro confirmado - revisar", "http_status": 400,
                    "resposta": {"mensagem": "Campo isbn é obrigatório"},
                }}})

            chamadas = []
            class Resultado:
                returncode, stdout, stderr = 0, "RASCUNHO_CRIADO", ""
            def executor(comando, **kwargs):
                chamadas.append(comando)
                return Resultado()

            registro = api.criar_rascunho_operador(raiz, executor=executor)
            self.assertEqual(api.OPERADOR_EMAIL, registro["destinatario"])
            self.assertIn(api.OPERADOR_EMAIL, chamadas[0])
            self.assertIn(api.REMETENTE_EMAIL, chamadas[0])
            self.assertNotIn("segredo-de-teste", " ".join(chamadas[0]))
            with self.assertRaisesRegex(RuntimeError, "ja existe rascunho"):
                api.criar_rascunho_operador(raiz, executor=executor)


class EnvioUnificadoTest(unittest.TestCase):
    def _criar_filas(self, raiz):
        controle = raiz / "_controle"
        controle.mkdir(parents=True)
        for grupo, nome in api.FILAS_ESPECIFICAS.items():
            quantidade = {"documentos": 4, "academico": 2,
                          "revistas": 1}[grupo]
            itens = [{"titulo": f"{grupo}-{i}",
                      "estado": "pronto para cadastro específico"}
                     for i in range(quantidade)]
            (controle / nome).write_text(
                json.dumps({"itens": itens}), encoding="utf-8")

    def test_limite_unificado_e_total_e_nao_por_fila(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = pathlib.Path(td)
            self._criar_filas(raiz)
            livros = {"itens": [
                {"titulo": f"livro-{i}", "estado": "pendente"}
                for i in range(3)]}
            with mock.patch.object(api, "atualizar_fila",
                                   return_value=(livros, 0, 0)):
                plano = api.planejar_todas_filas(raiz, limite=5)
            self.assertEqual(5, plano["total_selecionado"])
            self.assertEqual(3, plano["filas"]["livros"]["selecionados"])
            self.assertEqual(2, plano["filas"]["documentos"]["selecionados"])
            self.assertEqual(0, plano["filas"]["academico"]["selecionados"])
            self.assertEqual(0, plano["filas"]["revistas"]["selecionados"])

    def test_envio_unificado_reutiliza_motores_existentes(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = pathlib.Path(td)
            self._criar_filas(raiz)
            livros = {"itens": [
                {"titulo": f"livro-{i}", "estado": "pendente"}
                for i in range(3)]}
            with mock.patch.object(api, "atualizar_fila",
                                   return_value=(livros, 0, 0)), \
                    mock.patch.object(api, "ler_chave_chaves",
                                      return_value="segredo"), \
                    mock.patch.object(api, "criar_sessao_api",
                                      return_value=object()), \
                    mock.patch.object(api, "processar_fila",
                                      return_value={"enviados": 3}) as livros_fn, \
                    mock.patch.object(api, "processar_fila_especifica",
                                      return_value={"enviados": 2}) as esp_fn:
                resultado = api.processar_todas_filas(
                    raiz, limite=5, intervalo=0, realmente=True)
            self.assertEqual("ENVIO", resultado["modo"])
            self.assertEqual(5, resultado["planejado"])
            self.assertEqual(3, livros_fn.call_args.kwargs["limite"])
            self.assertEqual("documentos", esp_fn.call_args.args[1])
            self.assertEqual(2, esp_fn.call_args.kwargs["limite"])
            self.assertEqual(1, esp_fn.call_count)


if __name__ == "__main__":
    unittest.main()
