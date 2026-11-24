# Migração e continuidade do Biblio Preparador

Preparado em 24/11/2026. Não apagar a máquina antiga antes de testar o novo
ambiente e conferir o pacote privado. O Git sozinho não é backup do acervo.

## 1. O que vai por cada caminho

| GitHub | Pacote privado de migração | Reconfigurar no novo computador |
|---|---|---|
| Código, testes, interface aprovada, Swift, construtor e documentação | Filas, catálogo operacional, fichas revisadas, comprovantes, originais locais, capas e OCR | Chaves da API no Chaves do macOS |
| Dicionários gerais de autores, ruídos, editoras/cidades e periódicos | Memórias incrementais da instalação ativa, inclusive entradas ainda não auditadas | Logins Claude/Gemini e ferramentas externas |
| Histórico das branches Mac e legado | Experimentos e auditorias de recuperação, staging anterior e bundle Git de segurança | Homebrew, Python, conversores e modelos de NER |

Nunca fazer `git add .` na pasta antiga: os arquivos privados são deliberadamente
excluídos. O pacote privado contém dados pessoais/acervo e deve ser transferido
por armazenamento privado, de preferência criptografado, não por GitHub.
Os livros que existem somente no servidor Biblio continuam dependendo do backup
do servidor; o pacote local não os baixa novamente.

## 2. Recuperar o código no computador novo

```bash
git clone --branch codex/app-mac-biblio https://github.com/piraginejr/biblio-preparador.git
cd biblio-preparador
git status
git log -1 --oneline
```

A branch `desenvolvimento-biblio` conserva o motor antigo. Não trabalhar em
`main`. Mudanças compartilhadas continuam sendo testadas, commitadas e enviadas
nas duas branches, sem force. Os hashes das duas branches não precisam ser
iguais: os históricos de Mac e legado são diferentes.

`dados/fichas/` já integra o histórico do projeto; são fichas bibliográficas,
não substituem o catálogo/fila da instalação ativa. As listas gerais em
`99-FERRAMENTAS/` são as usadas pelo motor. O diretório `dados/` não deve
substituir cegamente essas listas: existem versões com quantidades diferentes.

## 3. Conferir e abrir o pacote privado

Na máquina antiga, com app e OCR encerrados, uma nova cópia pode ser criada com:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/biblio-pycache python3 packaging/migracao.py criar /CAMINHO/PRIVADO/NOVA-PASTA
```

O comando recusa um destino existente, não segue links externos e não lê o
Chaves. Registra links não incluídos no manifesto. Compara cada arquivo
com o conteúdo efetivamente gravado no arquivo compactado. Se um original
mudar durante a cópia ou a conferência falhar, o snapshot não é concluído.

Copiar a pasta inteira, incluindo `MANIFESTO.json`, `dados-privados.tar.gz`,
`historico-git.bundle`, o patch de staging e a nota do snapshot. Na máquina nova:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/biblio-pycache python3 packaging/migracao.py verificar /CAMINHO/DO/PACOTE
mkdir /CAMINHO/NOVO/RESTAURADO
tar -xzf /CAMINHO/DO/PACOTE/dados-privados.tar.gz -C /CAMINHO/NOVO/RESTAURADO
```

Extrair somente após a verificação e numa pasta nova/vazia. A estrutura será:

```text
RESTAURADO/
  projeto/             snapshot completo do projeto antigo, sem .git/venv/caches Python
  instalacao-ativa/    estado do aplicativo em Application Support (quando presente)
```

Não sobrescrever a cópia nova do Git com todo o snapshot antigo. Preservar os
dados/experimentos separadamente e copiar o estado da instalação de modo
controlado. Não aplicar os patches de segurança automaticamente: são registro
do estado anterior, não correções adicionais.

Se o GitHub estiver indisponível, o bundle permite recuperar o histórico:

```bash
git clone --branch codex/app-mac-biblio /CAMINHO/DO/PACOTE/historico-git.bundle biblio-recuperado
```

O bundle foi criado antes do commit da migração; o GitHub é a fonte dos commits
posteriores. Ele é uma salvaguarda adicional, não a referência mais recente.

## 4. Retomar em outro Mac

O pacote nativo atual é para **Apple Silicon (arm64)** e usa Cocoa/WebKit.
O construtor atual fixa essa arquitetura. Um Mac Intel exige ajuste e novo
teste de compilação; o aplicativo Windows ainda não está implementado.

Dependências identificadas no fluxo existente (não são embutidas no clone):

- Xcode/Command Line Tools e Swift, para o app e auxiliares Apple Vision.
- Python 3 com `requests`; o launcher atual tenta primeiro `/usr/bin/python3`,
  depois o Python das Command Line Tools e o Homebrew. Instalar somente em
  outro ambiente virtual não garante que o launcher o usará. Conferir qual
  interpretador o app realmente iniciou antes do primeiro lote.
- Poppler, OCRmyPDF, Tesseract e idiomas usados, Ghostscript e zbar.
- LibreOffice para Word/apresentações; Calibre para EPUB/MOBI/AZW3/FB2.
- Playwright e seu navegador para pesquisa comercial automatizada.
- NER opcional: `99-FERRAMENTAS/INSTALAR-NER.command` recria o ambiente
  `~/.biblio-venv`. Não copiar o venv antigo: contém caminhos absolutos.
- Claude/Gemini: instalar e autenticar as ferramentas usadas. Apple
  Intelligence requer Mac/macOS compatíveis. Indisponibilidade não autoriza
  aprovar metadados sem confirmação.
- GROBID: conferir `docs/GROBID-CENTRAL-OPENVPN.md`; conectar VPN/servidor
  quando usados. Não copiar contêineres ou credenciais por Git.

O script `LIVROS.command` faz a checagem das camadas; sua execução pode tentar
instalar `requests` ou compilar o Vision. Não é uma checagem sem efeitos.
O clone não instala Homebrew nem serviços automaticamente.

Construir sem iniciar preparo/envio:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/biblio-pycache bash packaging/macos/build_app.sh
```

Copiar o `.app` gerado de `dist/` para Aplicativos. A pasta operacional é:

```text
~/Library/Application Support/Biblio Preparador/revista
```

Com o app fechado, preservar/restaurar principalmente `livros/` da instalação
ativa antiga e as memórias incrementais de `99-FERRAMENTAS/`. Não substituir
o motor novo por scripts antigos. O app instala seu pacote-base a cada abertura;
as listas incrementais são mescladas pelo instalador.

**Troca de usuário/caminho:** as fichas e diários podem conter caminhos absolutos
do Mac antigo. Antes de processar ou liberar espaço, remapear os caminhos locais
na cópia restaurada, mantendo uma cópia imutável dos diários originais. Não
reescrever IDs remotos, hashes, recibos ou evidências. Não existe neste roteiro
uma migração automática universal de caminhos: validar o primeiro material na
bancada e todos os arquivos apontados pelas filas antes de enviar qualquer lote.

Validar o motor projeto/pacote/instalação com `packaging/macos/verificar_motor.py`
usando `--comparar`, conforme `AGENTS.md`. Em `/api/health`, conferir a versão
real do servidor iniciado. Uma página recarregada não recarrega Python.

Reconfigurar as chaves pelo menu do aplicativo; o Git e este backup não exportam
o Chaves do macOS, cookies/logins de IA nem senhas da VPN. O Assistente de Migração
do macOS pode ser uma alternativa para transferir conta/Chaves, a confirmar no
novo computador. Não colocar segredos em arquivos versionados.

## 5. Contexto para continuar sem repetir trabalho

- Meta de automação: 95%, preservando decisão humana e qualidade do PDF.
- Manter a bancada aprovada em colunas laterais, com leitura do miolo, todos
  os campos e botões. Não substituir por formulário empilhado.
- Revisões humanas têm precedência e precisam sobreviver ao reprocessamento.
- Antes de OCR pesado, consultar duplicidade. Livros antigos podem não ter ISBN;
  ISBN-10 e ISBN-13 são válidos. Publicações distintas não são duplicadas só
  por título parecido. Documentos podem não ter autor.
- API: livro tipo 1; revista tipo 2; artigo de revista tipo 3; artigo de jornal
  tipo 4; documento tipo 5; áudio 6; vídeo 7. Público é categoria 0.
- Resultado incerto de envio exige conciliação por ID antes de reenviar. Não
  reabrir cadastro confirmado nem criar ficha para reparar apenas um anexo.
- Recuperação da planilha original: última auditoria registrada em 09/11/2026
  indicava 159 IDs, 49 reparados e 110 pendentes; destes, 71 eram do grupo
  “Sem arquivo cadastrado”. Não confundir com fichas novas ou arquivos órfãos.
  Esses números são históricos, não uma consulta ao servidor em 24/11.
- Estado canônico: `experimentos/SITUACAO-RECUPERACAO-ORIGINAL-ATUAL.json`.
  Os diários/recibos e a busca do Kingston estão no pacote privado. Não
  recomeçar o OCR dos 760 PDFs já examinados nem reenviar IDs confirmados.
- A última busca do Kingston não confirmou novas cópias dos 71. Oito fichas
  não tinham identificação suficiente; nomes/prefixos de arquivo não bastam.
- As 17 linhas adicionais de editoras/cidades na instalação ativa incluem
  conflitos e provável ruído. Preservá-las no privado, não promovê-las
  cegamente a regras gerais. Migração não deve alterar a catalogação.

## 6. Aceite no computador novo

1. Clone correto, branches acessíveis e versão do motor validada.
2. Pacote privado íntegro; catálogo, filas e decisões humanas presentes.
3. Caminhos locais resolvidos; abrir PDF e capa de um item sem reprocessá-lo.
4. API configurada e consulta de leitura funcionando, sem cadastrar teste.
5. Conversão/OCR e pesquisas testados em cópias pequenas, sem envio automático.
6. Só então retomar os lotes. Conservar a máquina antiga e o snapshot até esse aceite.

O Kingston estava desconectado em 24/11/2026. Não considerar seu backup
atualizado sem reconectá-lo e comparar os arquivos entregues.
