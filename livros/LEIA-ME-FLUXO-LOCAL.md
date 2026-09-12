# Biblioteca local — preparação e cadastro

Sistema local que prepara livros, documentos, trabalhos acadêmicos e periódicos
para o acervo do PIB-Biblio: lê os metadados do próprio arquivo, confere contra
catálogos públicos, separa o que está pronto do que precisa de olho humano e
envia pela API.

Roda inteiramente no seu Mac. Nenhum arquivo é apagado durante o preparo.

---

## Índice

- [Uso diário](#uso-diário)
- [As pastas](#as-pastas)
- [O menu](#o-menu)
- [Como o programa decide](#como-o-programa-decide)
- [Segurança](#segurança)
- [Engenharia — decisões e por quê](#engenharia--decisões-e-por-quê)
- [Manutenção](#manutenção)
- [Limitações conhecidas](#limitações-conhecidas)

---

## Uso diário

1. Coloque os arquivos novos em **`00-ENTRADA`** — PDF, DOC, DOCX ou EPUB.
   Pastas organizadas também são aceitas. Se houver um `.opf` ou uma imagem de
   capa com o mesmo nome, eles acompanham o item.
2. Abra **`99-FERRAMENTAS/LIVROS.command`** com dois cliques.
3. Escolha **`1` — Executar o ciclo completo**.
4. Confira o resultado com a opção **`4`**.

O ciclo completo tem sete etapas e faz tudo: corrige OCR pendente, processa os
novos, concilia com as bases, consulta Estante Virtual e Amazon quando o idioma
justifica, e atualiza a fila de envio.

Se não houver internet, use a opção **`2`** — o mesmo fluxo em quatro etapas,
sem as consultas externas.

Word e EPUB **geram uma cópia PDF pesquisável** e o original é preservado.

---

## As pastas

| Pasta | O que contém |
|---|---|
| `00-ENTRADA` | novos arquivos, ainda não processados |
| `10-REVISAO` | conflito, dado ausente ou OCR a corrigir |
| `10-REVISAO/DUPLICADOS` | cópias idênticas já conhecidas — isoladas, não apagadas |
| `15-TESES-DISSERTACOES-E-TRABALHOS` | material acadêmico, fila própria |
| `16-ARTIGOS-E-DOCUMENTOS` | artigos e documentos, fila própria |
| `17-REVISTAS-E-PERIODICOS` | periódicos, fila própria |
| `18-EXCECOES-DE-TAMANHO` | acima do limite de envio, tratamento à parte |
| `19-DESCARTE` | marcados para descarte, aguardando sua confirmação |
| `20-PRONTOS` | aprovados, aguardando envio |
| `30-ARQUIVADOS` | cadastro já confirmado pela API |

**Os arquivos são movidos, não copiados.** Um livro aprovado ocupa o espaço de
um PDF só — o que importa quando são milhares.

Pastas de apoio: `_capas`, `_metadados` (ficha detalhada por item),
`_preparados-envio` (versões otimizadas) e `_controle` (catálogo, filas, caches
e histórico).

---

## O menu

**Preparo**

| | |
|---|---|
| `1` | ciclo completo — recomendado |
| `2` | ciclo completo sem internet |
| `3` | registrar lote antigo sem mover os PDFs |
| `11` | reavaliar os itens em revisão |

**Consulta**

| | |
|---|---|
| `4` | estado da biblioteca |
| `5` | idiomas que o Vision reconhece neste Mac |
| `9` | relatório técnico das rejeições |

**Envio**

| | |
|---|---|
| `6` | configurar a chave da API |
| `7` | atualizar e ver a fila |
| `8` | enviar os livros pendentes |
| `13` | enviar documentos, acadêmicos ou revistas |
| `10` | rascunho de e-mail para o operador |

**Espaço**

| | |
|---|---|
| `12` | liberar espaço de cadastrados, duplicados e descartes |
| `14` | configurar fontes acadêmicas internacionais |

---

## Como o programa decide

Treze camadas, consultadas nesta ordem. A primeira que responder com confiança
vence; as demais servem de conferência.

| # | Camada | Papel |
|---|---|---|
| 1 | **código de barras** | ISBN exato da capa ou contracapa |
| 2 | **bloco CIP** | ficha catalográfica impressa no livro |
| 3 | **página de créditos** | título da edição, tradutor, editora |
| 4 | **Open Library / Google Books** | por ISBN |
| 5 | **CBL / ISBN Brasil** | só se a leitura falhar ou faltar dado essencial |
| 6 | **BnF** | catálogo oficial francês |
| 7 | **Internet Archive** | evidência auxiliar — sempre exige revisão |
| 8 | **Crossref / OpenAlex** | artigos, teses e dissertações |
| 9 | **CORE / OATD** | complemento e link de conferência acadêmica |
| 10 | **folha de rosto** | página 1 |
| 11 | **capa** | OCR do Vision + NER (pessoa × instituição) |
| 12 | **Estante Virtual / Amazon** | última conferência dos pendentes |
| 13 | **nome do arquivo** | rede de segurança — sempre marcado para conferir |

### A ordem não é arbitrária

Ela vai **do inequívoco ao interpretado**. O código de barras devolve um número
que não precisa ser lido nem entendido. O CIP é uma ficha já escrita por um
bibliotecário. A capa exige OCR e interpretação. O nome do arquivo não prova
nada — no lote de teste, um arquivo chamado *"Herramienta para líderes de
jóvenes"* era, na verdade, *"Aprende a ser un líder como Jesús"*.

### Duas regras que vieram de erro real

**O ISBN impresso numa tradução costuma ser o da edição original.** Por isso a
API devolve o título em inglês para um livro em espanhol. O programa não
sobrescreve: o título estrangeiro vai para `titulo_original`, que é campo
próprio no Biblio, e o registro é marcado. Sem essa regra, *"Se Líder"* virava
*"Lead"* e a *Dogmática Reformada* virava *"Reformed dogmatics"*.

**O detentor do © muitas vezes não é o autor.** É o tradutor, o organizador ou
uma sociedade editorial. Foi assim que Erik Lubbers (autor de um retrato) e John
Bolt (organizador) apareceram como autores no lugar de Herman Bavinck. Hoje o
CIP tem prioridade sobre o ©, e o NER distingue pessoa de instituição.

---

## Segurança

**A chave da API fica no Chaves do macOS**, no serviço
`Biblioteca PIB Curitiba - API Biblio`. Nunca em arquivo, nunca no código. Pode
também vir da variável `BIBLIO_API_KEY`. Quando digitada, é sem eco.

**O padrão é simulação.** O envio real exige `--enviar` explícito.

**Cada tentativa é registrada pelo SHA-256 do PDF *antes* da requisição.** Se a
resposta vier incerta — timeout, conexão caída — o arquivo não é reenviado
automaticamente. Foi o que faltou no cadastro da revista, onde duas edições
entraram duplicadas.

**Uma execução por vez**, garantida por trava de arquivo (`flock`). Duas janelas
abertas não corrompem o catálogo.

**Nada é apagado no preparo.** A liberação de espaço (opção `12`) é operação
separada, simulada por padrão, e só move para a Lixeira depois do cadastro
confirmado.

**Duplicatas são isoladas, não removidas.** A decisão é sua.

**As buscas por navegador param sozinhas ao encontrar verificação ou CAPTCHA** —
não há tentativa de contorná-las. O texto da página de resultados do Google
serve apenas para localizar fontes; nunca é tratado como prova.

---

## Engenharia — decisões e por quê

Esta seção registra as escolhas técnicas e a evidência que levou a cada uma.
Serve para quem for mexer no código daqui a meses — inclusive você.

### O OCR é o Apple Vision, não o Tesseract

Medido nas mesmas 12 capas, com o Tesseract 5.5.3 e 135 idiomas instalados:

| | Título correto |
|---|---|
| Tesseract, 300 dpi | 4/12 |
| **Vision** | **8/12** |

Onde o Tesseract devolvia `DB \ | | VIF AA ANS! e pr e o e ce o t`, o Vision
devolvia `DOGMATICA REFORMADA El Pecado y La Salvación`. Não era falta de idioma
nem de resolução — era o motor.

O `apple-vision-ocr-plugin.py` registra o Vision **como engine do OCRmyPDF**.
Isso resolve o impasse: o Vision lê muito melhor, mas sozinho devolve texto
solto e não sabe gravar a camada de texto dentro do PDF. Como plugin do
OCRmyPDF, o acervo inteiro fica pesquisável com o motor bom.

### A capa é lida a 300 dpi

A 100 dpi o OCR não lê capa decorada. Só essa mudança levou o acerto de 8% para
40% na primeira medição. É a linha `DPI_CAPA` em `preparar-livros.py`.

### O `identificar.py` não usa geometria

Ele é o porte do `CardParser.swift` do aplicativo CartaoContatos. A lição que
veio de lá: **o parser dos cartões recebe só uma lista de linhas de texto**, sem
nenhuma coordenada, e por isso aguenta diagramações completamente diferentes.

A primeira versão da leitura de capa aqui classificava por geometria — maior
corpo = título, rodapé = autor. Acertou **1 capa em 12**. O motivo está nas
próprias capas: em *Dogmática Reformada* e em *Sé Líder* o elemento maior é o
**nome do autor**, porque é o autor que vende. Diagramação é decisão de
marketing e muda a cada livro.

Três camadas, na ordem do app original:

1. honorífico explícito (`Dr.`, `Rev.`, `Pastor`) — ganha de tudo
2. NER, **se passar na pontuação** — nunca obedecido cego
3. maior pontuação — sempre responde

### A caixa alta precisa ser normalizada antes do NER

Medido nos dois modelos do spaCy:

```
HERMAN BAVINCK      → PER   ✓
PAUL DAVID TRIPP    → ORG   ✗
William Cunningham  → PER   ✓
```

Os modelos são treinados em texto com capitalização normal, e capa de livro é
quase toda em caixa alta. A função `caixa_normal()` converte antes de perguntar
ao modelo — e o nome guardado vem sempre da linha original, senão `MACARTHUR`
viraria `Macarthur`.

### O ambiente Python vive fora do Dropbox

Em `~/.biblio-venv`. Um *venv* é feito de symlinks e caminhos absolutos; o
Dropbox não lida bem com nenhum dos dois. Quando ficava junto dos scripts, a
sincronia quebrava o link do `python` e criava arquivos "Cópia em conflito". O
código fica no Dropbox; as dependências, não.

O Python precisa estar entre **3.10 e 3.13**. O 3.9 do macOS é velho demais e
protegido pelo sistema; o 3.14 é novo demais — o spaCy instala e depois não
importa.

### O medidor de qualidade de OCR olha estrutura, não letras

Ter texto não é ter texto bom. Duas versões falharam antes da atual:

- contar caracteres reprovava 11 de 12 livros **bons**, porque página de
  créditos é cheia de ISBN, CEP e telefone;
- contar apenas letras dava **nota 1.0 para o lixo**, já que `VIF AA ANS tbe` é
  feito só de letras.

A versão atual exige que a ficha pareça palavra: tem vogal e não empilha cinco
consoantes. Texto bom fica em 0.90–0.98; lixo de OCR, em 0.59–0.81. O limiar é
`LIMIAR_OCR = 0.85`, **calibrado neste acervo** — se um livro legítimo começar a
ser reprovado, é esse número que baixa.

### Conflito só quando ainda importa

O objetivo não é ter poucos conflitos, é que **todo erro real esteja marcado e
todo conflito marcado seja real**. Três alarmes falsos foram removidos depois de
auditoria linha a linha:

- **páginas** — tradução ao espanhol é mais longa que o original em inglês; isso
  é normal. O critério foi invertido: alerta quando o PDF tem 25% *menos*
  páginas que a edição, o que sugere arquivo incompleto;
- **© × API** — se o CIP já decidiu o autor, o desacordo entre as outras fontes
  é ruído;
- **nome do arquivo** — só preocupa quando nenhuma outra fonte confirma.

E um alerta foi acrescentado: **título em inglês num livro em espanhol ou
francês**. *"Un Appel Dangereux"* passava como pronto com o título
*"Confronting the Unique Challenges of…"* — erro silencioso, que é pior que
conflito.

### A origem de cada campo é gravada

As colunas `origem_titulo`, `origem_autor` e `motor_texto` dizem de onde veio
cada dado. Escolher em silêncio foi o que escondeu, por várias rodadas, que o
Vision não estava sendo usado fora da capa.

### 268 testes automatizados

| Arquivo | Testes |
|---|---|
| `test_preparar_livros.py` | 116 |
| `test_biblioteca_local.py` | 52 |
| `test_enviar_livro_api.py` | 49 |
| `test_consultar_web_navegador.py` | 30 |
| `test_fontes_bibliograficas.py` | 18 |
| `test_consultar_cbl.py` | 3 |

Rode antes de qualquer mudança:

```
cd 99-FERRAMENTAS
~/.biblio-venv/bin/python -m pytest -q
```

Um exemplo de por que existem: numa reorganização da cascata de título, a
comparação `titulo[:18] in tit_api` passou a receber string vazia — e em Python
`"" in "lead"` é sempre verdadeiro. Todos os títulos passaram a ser
sobrescritos pela API. Um teste pega isso; uma conversa, não.

---

## Manutenção

**Os arquivos que você abre** — `LIVROS.command`, `INSTALAR-NER.command`,
`TESTAR-CAPAS.command`. Todo o resto é peça interna.

**As peças principais**

| Arquivo | Papel |
|---|---|
| `biblioteca-local.py` | estados, movimentação, catálogo, duplicatas |
| `preparar-livros.py` | extração de metadados |
| `enviar-livro-api.py` | fila, chave, envio, idempotência |
| `consultar_fontes_bibliograficas.py` | BnF, Internet Archive, acadêmicas |
| `consultar-web-navegador.py` | Estante Virtual e Amazon |
| `identificar.py` | pessoa × instituição |
| `ler-capa.py` | OCR da capa |
| `vision-ocr.swift` | leitor Vision |
| `vision-barcode.swift` | leitor de código de barras |
| `apple-vision-ocr-plugin.py` | Vision como engine do OCRmyPDF |

**Dependências externas** — poppler, zbar, ocrmypdf, ghostscript, Xcode (para
compilar os utilitários Swift), Playwright (opcional, só para Estante e Amazon).
O `LIVROS.command` confere todas na abertura e diz o que falta.

**Onde ajustar o comportamento** — as constantes no topo de
`preparar-livros.py` (`DPI_CAPA`, `LIMIAR_OCR`, `MIN_OCR`, `ANO_ISBN`) e de
`enviar-livro-api.py` (`LIMITE_OTIMIZACAO_BYTES`, `LIMITE_ENVIO_BYTES`,
`TIMEOUT_ENVIO`).

---

## Limitações conhecidas

**Os números foram calibrados num acervo pequeno.** Os limiares e a medição de
92% em título e autor vêm de 12 livros, quase todos traduções para o espanhol e
quatro do mesmo autor. Serve para orientar decisão, não para prometer taxa. Um
lote de 40 ou 50 livros de origens variadas daria um número confiável.

**Traduções automáticas confundem as fontes.** Vários PDFs do acervo são
traduções feitas por máquina: *Baker Academic* virou *"Panadero Académico"* e o
tradutor *John Vriend* virou *"John Amigo"*. Editora e título vindos do texto
são suspeitos nesses casos — prefira o CIP ou a API.

**Obras corporativas não têm autor pessoal.** O manual da Associação Billy
Graham é da instituição, não de uma pessoa. O programa marca para revisão em vez
de escolher.

**Capa em idioma diferente do miolo.** Em alguns PDFs a capa é a da edição
original. É conflito legítimo, não falha — mas exige decisão humana.

**A falta de ISBN não impede o cadastro.** O ISBN foi criado em 1970; o de 13
dígitos só passou a ser obrigatório em 2007. Uma obra antiga pode legitimamente
não ter nenhum — e uma obra antiga em edição moderna pode ter. O número é dado
da *edição*, nunca requisito da obra.

**Direitos autorais.** Este é um acervo pessoal de pesquisa. Vários itens têm
restrição expressa de redistribuição — o manual da Associação Billy Graham, por
exemplo, declara que não deve ser impresso ou distribuído. O programa não
verifica isso; a responsabilidade é de quem cataloga.

---

*Atualizado em 20 de agosto de 2026.*
