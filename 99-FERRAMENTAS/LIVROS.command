#!/bin/bash
# =============================================================================
#  LIVROS - fluxo local incremental de preparacao
# =============================================================================
#  Abra com DOIS CLIQUES. Nao precisa digitar nada no terminal.
#
#  Novos PDFs, DOC/DOCX, PPT/PPTX, HTML ou pastas organizadas entram em
#  livros/00-ENTRADA. O Biblio só aceita PDF: Word, PowerPoint, HTML e EPUB
#  são convertidos para PDF pesquisável; apresentações entram como
#  documentos (só o título é obrigatório). OPF e capa de mesmo nome
#  acompanham o item. Livros, documentos, trabalhos acadêmicos e revistas
#  seguem para pastas e filas próprias. Nenhum original é apagado no preparo.
#
#  As camadas, na ordem em que sao consultadas:
#     1. codigo de barras   - ISBN exato da capa/contracapa
#     2. bloco CIP          - a ficha catalografica impressa no livro
#     3. pagina de creditos - titulo da edicao, tradutor, editora
#     4. Open Library / Google Books, por ISBN
#     5. CBL/ISBN Brasil    - so se a leitura falhar ou faltar dado essencial
#     6. BnF                - catalogo oficial para edicoes francesas
#     7. Internet Archive   - evidencia auxiliar, sempre exige revisao
#     8. Crossref/OpenAlex  - artigos, teses e dissertações internacionais
#     9. CORE/OATD          - complemento e link de conferência acadêmica
#    10. folha de rosto     - pagina 1
#    11. capa               - OCR do Vision + NER (pessoa x instituicao)
#    12. Estante/Amazon     - ultima conferencia dos livros ainda pendentes
#    13. nome do arquivo    - rede de seguranca, sempre marcado para conferir
# =============================================================================

cd "$(dirname "$0")" || exit 1
V=$'\033[0;32m'; A=$'\033[0;33m'; R=$'\033[0;31m'
AZ=$'\033[0;34m'; N=$'\033[1m'; F=$'\033[0m'
linha(){ printf "${AZ}  %s${F}\n" "------------------------------------------------------------"; }

clear
echo ""
printf "${N}${AZ}   LIVROS  ->  metadados para o tombo${F}\n"
linha
echo ""

# ---------------------------------------------------------------------------
# 1. interpretador
# ---------------------------------------------------------------------------
# O python3 do macOS e o 3.9 e nao aceita instalar nada. Se o
# INSTALAR-NER.command ja criou o .venv, usamos ele - e o unico que tem spaCy.
# O ambiente vive FORA do Dropbox: venv e feito de symlinks e caminhos
# absolutos, e a sincronia quebra os dois. Criado pelo INSTALAR-NER.command.
VENV="$HOME/.biblio-venv"
if [ -x "$VENV/bin/python" ]; then
  PY="$VENV/bin/python"
  ONDE="ambiente proprio ($VENV)"
else
  PY="$(command -v python3)"
  ONDE="python do sistema - rode o INSTALAR-NER.command"
fi
[ -x "$PY" ] || { printf "${R}   python3 nao encontrado${F}\n\n"; read -n1 -s; exit 1; }

# ---------------------------------------------------------------------------
# 2. o que esta disponivel
# ---------------------------------------------------------------------------
printf "${N}   Verificando as camadas...${F}\n\n"

FALTA=0
checar(){ # $1=rotulo  $2=condicao_ok  $3=essencial  $4=como_resolver
  if [ "$2" = "1" ]; then printf "${V}   [ok]${F}   %s\n" "$1"
  elif [ "$3" = "1" ]; then printf "${R}   [x]${F}    %s  -> %s\n" "$1" "$4"; FALTA=1
  else printf "${A}   [--]${F}   %s  (opcional) -> %s\n" "$1" "$4"; fi
}

command -v pdftotext >/dev/null && T=1 || T=0
checar "poppler (ler PDF)" $T 1 "brew install poppler"

if command -v zbarimg >/dev/null || [ -x /opt/homebrew/bin/zbarimg ]; then T=1; else T=0; fi
checar "zbar (ler ISBN do código de barras da capa)" $T 1 "brew install zbar"

"$PY" -c "import requests" 2>/dev/null && T=1 || T=0
if [ "$T" = "0" ]; then "$PY" -m pip install requests --quiet 2>/dev/null; \
   "$PY" -c "import requests" 2>/dev/null && T=1; fi
checar "requests (consultar bases bibliograficas e CBL)" $T 1 "pip3 install requests"

# O LibreOffice converte Word E PowerPoint. Sete apresentações ficaram
# paradas em 00-ENTRADA sem que nada reclamasse; agora a falta aparece aqui.
"$PY" -c "import sys;sys.path.insert(0,'.');
import importlib.util,pathlib
s=importlib.util.spec_from_file_location('bl',pathlib.Path('biblioteca-local.py'))
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
exit(0 if m.localizar_soffice() else 1)" 2>/dev/null && T=1 || T=0
checar "LibreOffice (converter Word e PowerPoint em PDF)" $T 0 \
  "brew install --cask libreoffice"

"$PY" -c "import playwright" 2>/dev/null && PLAYWRIGHT=1 || PLAYWRIGHT=0
checar "navegador automatizado (Estante Virtual e Amazon)" $PLAYWRIGHT 0 \
  "instale playwright no ambiente da biblioteca"

command -v security >/dev/null && T=1 || T=0
checar "Chaves do macOS (proteger acesso da API)" $T 1 "recurso ausente neste Mac"

command -v ocrmypdf >/dev/null && T=1 || T=0
checar "ocrmypdf (preparar automaticamente quem estiver sem OCR)" $T 1 "brew install ocrmypdf"

command -v gs >/dev/null && T=1 || T=0
checar "Ghostscript (reduzir livros grandes para envio)" $T 1 "brew install ghostscript"

[ -x ./vision-ocr ] && [ ! ./vision-ocr.swift -nt ./vision-ocr ] && T=1 || T=0
if [ "$T" = "0" ] && [ -f ./vision-ocr.swift ]; then
  echo "        compilando o vision-ocr..."
  VISION_TMP="${TMPDIR:-/tmp}/biblio-vision-ocr-$$"
  if [ -d /Applications/Xcode.app/Contents/Developer ]; then
    CLANG_MODULE_CACHE_PATH="${TMPDIR:-/tmp}/biblio-clang-cache" \
      DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer \
      xcrun swiftc -O vision-ocr.swift -o "$VISION_TMP" 2>/dev/null
  elif command -v swiftc >/dev/null; then
    swiftc -O vision-ocr.swift -o "$VISION_TMP" 2>/dev/null
  fi
  if [ -x "$VISION_TMP" ]; then mv "$VISION_TMP" vision-ocr; fi
  chmod +x vision-ocr 2>/dev/null
  [ -x ./vision-ocr ] && T=1
fi
[ -f ./apple-vision-ocr-plugin.py ] || T=0
checar "Apple Vision (OCR pesquisavel de todas as paginas)" $T 1 "instale o Xcode e reabra"

"$PY" -c "import sys;sys.path.insert(0,'.');import identificar;\
exit(0 if identificar.tem_ner() else 1)" 2>/dev/null && T=1 || T=0
checar "spaCy NER (separa pessoa de instituicao)" $T 0 "abra o INSTALAR-NER.command"

if [ "$FALTA" = "1" ]; then
  echo ""; printf "${R}   Falta algo essencial. Resolva acima e abra de novo.${F}\n\n"
  read -n1 -s -r -p "   Tecla para fechar..."; exit 1
fi
printf "\n   usando: %s\n" "$ONDE"

# ---------------------------------------------------------------------------
# 3. biblioteca unica
# ---------------------------------------------------------------------------
echo ""
PADRAO="$(cd .. && pwd)/livros"
LIVROS="$PADRAO"
echo "   Biblioteca unica: $LIVROS"
echo "   Entrada unica:    $LIVROS/00-ENTRADA"
echo ""

mkdir -p "$LIVROS/00-ENTRADA" || {
  printf "\n${R}   Nao foi possivel criar a biblioteca unica:${F}\n   %s\n\n" "$LIVROS"
  read -n1 -s -r -p "   Tecla para fechar..."; exit 1;
}
QTD=$(find "$LIVROS" -maxdepth 1 -type f -iname '*.pdf' 2>/dev/null | wc -l | tr -d ' ')
"$PY" biblioteca-local.py --raiz "$LIVROS" --inicializar >/dev/null || {
  printf "\n${R}   Nao foi possivel preparar a estrutura local.${F}\n\n"
  read -n1 -s -r -p "   Tecla para fechar..."; exit 1; }

# A conferência que antes dependia da opção 15 agora protege os fluxos
# automaticamente. Nos ciclos de preparo ela roda ao final, porque o próprio
# reprocessamento pode corrigir uma ficha divergente. Antes de qualquer envio,
# uma divergência bloqueia o acesso à API.
conferir_revisoes_automaticamente(){
  echo ""
  echo "   Conferindo a integridade das revisões manuais..."
  if "$PY" conferir_revisoes.py --raiz "$LIVROS"; then
    printf "${V}   Revisões verificadas: tudo certo.${F}\n"
    return 0
  fi
  printf "${R}   Há revisões divergentes. O envio foi bloqueado por segurança.${F}\n"
  printf "${A}   Corrija ou reavalie os itens indicados antes de continuar.${F}\n"
  return 1
}

iniciar_grobid_para_ciclo(){
  echo ""
  echo "   Preparando o leitor acadêmico local (GROBID)..."
  if ! "$PY" gerenciar-grobid.py --raiz "$LIVROS" --garantir; then
    printf "${A}   O ciclo continuará pelas fontes atuais, sem bloquear.${F}\n"
  fi
}

encerrar_grobid_do_ciclo(){
  "$PY" gerenciar-grobid.py --raiz "$LIVROS" --parar 2>/dev/null || true
}

# Se o operador interromper o aplicativo, um contêiner iniciado por este
# ciclo também será encerrado. Serviços externos ou iniciados manualmente
# não possuem o marcador e nunca são tocados.
trap 'encerrar_grobid_do_ciclo' EXIT

# ---------------------------------------------------------------------------
# 4. menu
# ---------------------------------------------------------------------------
while true; do
  echo ""; linha
  # Contamos TUDO, nao so PDF. Um HTML ficou meses em 00-ENTRADA sem
  # aparecer aqui, porque o painel so procurava *.pdf: nao era processado,
  # nao era convertido e nao era reclamado. Arquivo que o sistema nao trata
  # precisa APARECER.
  NOVOS=$(find "$LIVROS"/00-ENTRADA -type f -iname '*.pdf' 2>/dev/null | wc -l | tr -d ' ')
  OUTROS=$(find "$LIVROS"/00-ENTRADA -type f ! -iname '*.pdf' ! -name '.*' \
           ! -path '*_files/*' ! -path '*_arquivos/*' 2>/dev/null | wc -l | tr -d ' ')
  printf "${N}   Biblioteca local: %s  |  novos na entrada: %s${F}" \
         "$(basename "$LIVROS")" "$NOVOS"
  if [ "$OUTROS" -gt 0 ]; then
    printf "${A}  + %s outro(s) formato(s)${F}" "$OUTROS"
  fi
  echo ""
  if [ "$OUTROS" -gt 0 ]; then
    find "$LIVROS"/00-ENTRADA -type f ! -iname '*.pdf' ! -name '.*' \
      ! -path '*_files/*' ! -path '*_arquivos/*' 2>/dev/null \
      | head -5 | while read -r f; do
        case "${f##*.}" in
          html|htm|xhtml|HTML|HTM) marca="sera convertido em PDF" ;;
          doc|docx|DOC|DOCX)       marca="sera convertido em PDF" ;;
          epub|EPUB)               marca="sera convertido em PDF" ;;
          ppt|pptx|pps|ppsx|odp|PPT|PPTX|PPS|PPSX|ODP) marca="sera convertido em PDF" ;;
          *)                       marca="formato nao reconhecido" ;;
        esac
        printf "${A}     %s${F}  -  %s\n" "$(basename "$f")" "$marca"
      done
  fi
  linha
  echo ""
  echo "     1)  Executar o ciclo completo              (recomendado)"
  echo "     2)  Executar o ciclo completo sem internet"
  echo "     3)  Registrar o lote antigo sem mover PDFs"
  echo ""
  echo "     4)  Ver o estado da biblioteca local"
  echo "     5)  Quais idiomas o Vision reconhece neste Mac"
  echo ""
  echo "     6)  Configurar a chave segura da API"
  echo "     7)  Atualizar e ver a fila de envio"
  echo "     8)  Enviar somente os livros pendentes da fila"
  echo "     9)  Gerar relatorio tecnico das rejeicoes"
  echo "    10)  Criar e-mail para o operador (rascunho)"
  echo "    11)  Reavaliar os itens que estão em revisão"
  echo "    12)  Liberar espaço de cadastrados, duplicados e descartes"
  echo "    13)  Enviar documentos, trabalhos acadêmicos ou revistas"
  echo "    14)  Configurar fontes acadêmicas internacionais"
  echo "    15)  Preparar ou verificar o GROBID local"
  echo "    16)  Enviar tudo que estiver pronto"
  echo "    17)  Abrir bancada de revisão visual"
  echo ""
  printf "${V}   Integridade das revisões: conferência automática${F}\n"
  echo ""
  echo "     0)  Sair"
  echo ""
  read -p "   Numero + Enter: " op
  echo ""; linha; echo ""

  case "$op" in
    1) # A Estante/Amazon e UMA camada de treze. Antes, faltar o Playwright
       # cancelava o ciclo inteiro: o menu imprimia duas linhas e voltava,
       # e quem rodava concluia que "nada saiu". Agora o ciclo roda e
       # apenas pula as duas etapas que dependem do navegador.
       if [ "$PLAYWRIGHT" != "1" ]; then
         printf "${A}   Sem o navegador automatizado: as etapas de Estante${F}\n"
         printf "${A}   Virtual e Amazon serao puladas. As outras rodam.${F}\n"
         echo ""
       fi
       iniciar_grobid_para_ciclo
       echo "   Etapa 1/7 - corrigindo OCR e tamanho pendentes..."
       "$PY" biblioteca-local.py --raiz "$LIVROS" --corrigir-ocr
       echo ""
       echo "   Etapa 2/7 - processando os livros novos..."
       if ! "$PY" biblioteca-local.py --raiz "$LIVROS" --processar; then
         printf "\n${R}   A preparação dos novos arquivos falhou.${F}\n"
         echo "   O ciclo foi interrompido para não apresentar um resultado enganoso."
         echo "   Os arquivos permanecem preservados para a retomada."
         continue
       fi
       echo ""
       echo "   Etapa 3/7 - conciliando PDF, ISBN e bases bibliográficas/acadêmicas..."
       "$PY" biblioteca-local.py --raiz "$LIVROS" --reprocessar-revisao
       echo ""
       if [ "$PLAYWRIGHT" = "1" ]; then
         echo "   Etapa 4/7 - Estante Virtual somente para obras em português..."
         "$PY" consultar-web-navegador.py --raiz "$LIVROS" --motor estante \
           --limite 0 --executar --oculto
       else
         echo "   Etapa 4/7 - pulada (sem navegador automatizado)"
       fi
       echo ""
       echo "   Etapa 5/7 - aplicando o consenso da Estante Virtual..."
       "$PY" biblioteca-local.py --raiz "$LIVROS" --reprocessar-revisao
       echo ""
       if [ "$PLAYWRIGHT" = "1" ]; then
         echo "   Etapa 6/7 - Amazon Brasil/EUA conforme o idioma da obra..."
         "$PY" consultar-web-navegador.py --raiz "$LIVROS" --motor amazon \
           --limite 0 --executar --oculto
       else
         echo "   Etapa 6/7 - pulada (sem navegador automatizado)"
       fi
       echo ""
       echo "   Etapa 7/7 - conciliação final, fila e resumo..."
       "$PY" biblioteca-local.py --raiz "$LIVROS" --reprocessar-revisao
       "$PY" enviar-livro-api.py --atualizar-fila "$LIVROS"
       "$PY" biblioteca-local.py --raiz "$LIVROS" --status
       conferir_revisoes_automaticamente
       encerrar_grobid_do_ciclo ;;
    2) iniciar_grobid_para_ciclo
       echo "   Etapa 1/4 - corrigindo OCR e tamanho pendentes..."
       "$PY" biblioteca-local.py --raiz "$LIVROS" --corrigir-ocr --sem-api
       echo ""
       echo "   Etapa 2/4 - processando os livros novos..."
       if ! "$PY" biblioteca-local.py --raiz "$LIVROS" --processar --sem-api; then
         printf "\n${R}   A preparação dos novos arquivos falhou.${F}\n"
         echo "   O ciclo foi interrompido; os arquivos permanecem preservados."
         continue
       fi
       echo ""
       echo "   Etapa 3/4 - reavaliando automaticamente as pendencias..."
       "$PY" biblioteca-local.py --raiz "$LIVROS" --reprocessar-revisao --sem-api
       echo ""
       echo "   Etapa 4/4 - atualizando a fila e o resumo..."
       "$PY" enviar-livro-api.py --atualizar-fila "$LIVROS"
       "$PY" biblioteca-local.py --raiz "$LIVROS" --status
       conferir_revisoes_automaticamente
       encerrar_grobid_do_ciclo ;;
    3) printf "${A}   Os PDFs existentes permanecerao onde estao.${F}\n"
       "$PY" biblioteca-local.py --raiz "$LIVROS" --registrar-existentes ;;
    4) "$PY" biblioteca-local.py --raiz "$LIVROS" --status ;;
    5) if [ -x ./vision-ocr ]; then
         echo "   Idiomas que o Vision reconhece neste Mac:"; echo ""
         ./vision-ocr --idiomas | tr ' ' '\n' | sed 's/^/     /'
       else echo "   vision-ocr nao compilado."; fi ;;
    6) "$PY" enviar-livro-api.py --configurar-chave ;;
    7) "$PY" enviar-livro-api.py --atualizar-fila "$LIVROS"
       "$PY" biblioteca-local.py --raiz "$LIVROS" --atualizar-filas-especificas ;;
    8) if ! "$PY" enviar-livro-api.py --verificar-chave; then
         printf "${A}   Configure primeiro a chave na opcao 6.${F}\n"
       else
         if ! conferir_revisoes_automaticamente; then
           echo ""
           read -n 1 -s -r -p "   Tecla para voltar ao menu..."
           clear
           continue
         fi
         echo "   Atualizando somente a lista dos livros que já estão prontos..."
         echo "   Nenhum OCR, compactação ou preparo será executado."
         "$PY" enviar-livro-api.py --atualizar-fila "$LIVROS"
         echo ""
         echo "   Quantos livros deseja enviar neste lote?"
         echo "   Use 0 para todos os pendentes. Sugestao inicial: 20."
         read -p "   Quantidade [20]: " LIMITE
         LIMITE="${LIMITE:-20}"
         case "$LIMITE" in (*[!0-9]*|'')
           printf "${A}   Quantidade invalida.${F}\n" ;;
         (*) echo ""
           printf "${A}   Os livros serao cadastrados como PUBLICOS, um por vez.${F}\n"
           read -p "   Digite SIM para iniciar: " CONFIRMA
           case "$CONFIRMA" in
           [Ss][Ii][Mm])
             "$PY" enviar-livro-api.py --processar-fila "$LIVROS" \
               --limite "$LIMITE" --intervalo 3 --enviar ;;
           *) echo "   Envio cancelado. A fila foi preservada." ;;
           esac ;;
         esac
       fi ;;
    9) "$PY" enviar-livro-api.py --relatorio-rejeicoes "$LIVROS" ;;
   10) "$PY" enviar-livro-api.py --criar-email-operador "$LIVROS" ;;
   11) "$PY" biblioteca-local.py --raiz "$LIVROS" --reprocessar-revisao
       conferir_revisoes_automaticamente ;;
   12) "$PY" enviar-livro-api.py --atualizar-fila "$LIVROS" >/dev/null
       "$PY" biblioteca-local.py --raiz "$LIVROS" --liberar-espaco
       echo ""
       printf "${A}   Cadastrados, duplicados e descartes acima irão para a Lixeira do macOS.${F}\n"
       printf "${A}   Em livros importados, PDF, OPF, EPUB e capa associados serão removidos.${F}\n"
       printf "${A}   Pastas vazias e arquivos .DS_Store residuais também serão limpos.${F}\n"
       printf "${A}   Metadados, IDs, hashes e histórico serão preservados.${F}\n"
       read -p "   Digite LIBERAR para confirmar: " CONFIRMA
       if [ "$CONFIRMA" = "LIBERAR" ]; then
         "$PY" biblioteca-local.py --raiz "$LIVROS" --liberar-espaco --executar
       else
         echo "   Operação cancelada. Nenhum arquivo foi movido."
       fi ;;
   13) if ! "$PY" enviar-livro-api.py --verificar-chave; then
         printf "${A}   Configure primeiro a chave na opcao 6.${F}\n"
       else
         if ! conferir_revisoes_automaticamente; then
           echo ""
           read -n 1 -s -r -p "   Tecla para voltar ao menu..."
           clear
           continue
         fi
         "$PY" biblioteca-local.py --raiz "$LIVROS" \
           --atualizar-filas-especificas
         echo ""
         echo "   Qual fila deseja enviar?"
         echo "     1) Documentos, apostilas, sermões e artigos"
         echo "     2) Teses, dissertações e trabalhos acadêmicos"
         echo "     3) Revistas e periódicos completos"
         read -p "   Numero + Enter: " GRUPO_ESCOLHA
         case "$GRUPO_ESCOLHA" in
           1) GRUPO="documentos" ;;
           2) GRUPO="academico" ;;
           3) GRUPO="revistas" ;;
           *) GRUPO=""; printf "${A}   Fila inválida.${F}\n" ;;
         esac
         if [ -n "$GRUPO" ]; then
           echo ""
           "$PY" enviar-livro-api.py --processar-fila-especifica "$LIVROS" \
             --grupo-especifico "$GRUPO" --limite 0
           echo ""
           echo "   Quantos materiais deseja enviar? Use 0 para todos."
           read -p "   Quantidade [20]: " LIMITE
           LIMITE="${LIMITE:-20}"
           case "$LIMITE" in (*[!0-9]*|'')
             printf "${A}   Quantidade inválida.${F}\n" ;;
           (*) printf "${A}   Os materiais serão cadastrados como PUBLICOS.${F}\n"
             read -p "   Digite SIM para iniciar: " CONFIRMA
             case "$CONFIRMA" in
             [Ss][Ii][Mm])
               "$PY" enviar-livro-api.py --processar-fila-especifica "$LIVROS" \
                 --grupo-especifico "$GRUPO" --limite "$LIMITE" \
                 --intervalo 3 --enviar ;;
             *) echo "   Envio cancelado. A fila foi preservada." ;;
             esac ;;
           esac
         fi
       fi ;;
   14) echo "   Fontes acadêmicas internacionais:"
       echo ""
       echo "     OpenAlex: principal para teses, dissertações e artigos"
       echo "       A consulta básica funciona sem chave; a chave amplia a franquia."
       echo "       https://openalex.org/settings/api"
       echo "     CORE: complemento acadêmico em modo público"
       echo "       A consulta básica funciona sem chave; a chave amplia a franquia."
       echo "       https://core.ac.uk/services/api"
       echo "     OATD: link de conferência manual; não oferece API"
       echo ""
       "$PY" consultar_fontes_bibliograficas.py --status-chaves
       echo ""
       echo "     1) Guardar chave OpenAlex no Chaves do macOS"
       echo "     2) Guardar chave CORE no Chaves do macOS"
       echo "     3) Apenas ver o estado"
       read -p "   Numero + Enter: " FONTE_ACADEMICA
       case "$FONTE_ACADEMICA" in
         1) "$PY" consultar_fontes_bibliograficas.py --configurar-openalex ;;
         2) "$PY" consultar_fontes_bibliograficas.py --configurar-core ;;
         3) : ;;
         *) printf "${A}   Opção inválida.${F}\n" ;;
       esac ;;
   15) echo "   Leitor acadêmico local GROBID:"
       echo ""
       "$PY" gerenciar-grobid.py --raiz "$LIVROS" --status || true
       echo ""
       echo "     1) Iniciar e testar agora"
       echo "     2) Encerrar o contêiner iniciado pelo aplicativo"
       echo "     3) Instalar ou atualizar a imagem (aprox. 1,7 GB)"
       echo "     0) Voltar"
       read -p "   Numero + Enter: " ACAO_GROBID
       case "$ACAO_GROBID" in
         1) "$PY" gerenciar-grobid.py --raiz "$LIVROS" --garantir ;;
         2) "$PY" gerenciar-grobid.py --raiz "$LIVROS" --parar ;;
         3) "$PY" gerenciar-grobid.py --instalar ;;
         0) : ;;
         *) printf "${A}   Opção inválida.${F}\n" ;;
       esac ;;
   16) if ! "$PY" enviar-livro-api.py --verificar-chave; then
         printf "${A}   Configure primeiro a chave na opcao 6.${F}\n"
       else
         if ! conferir_revisoes_automaticamente; then
           echo ""
           read -n 1 -s -r -p "   Tecla para voltar ao menu..."
           clear
           continue
         fi
         echo "   Atualizando as quatro filas sem executar OCR ou preparo..."
         "$PY" enviar-livro-api.py --atualizar-fila "$LIVROS" >/dev/null
         "$PY" biblioteca-local.py --raiz "$LIVROS" \
           --atualizar-filas-especificas >/dev/null
         echo ""
         echo "   Materiais disponiveis para o envio unificado:"
         PLANO_ENVIO="$("$PY" enviar-livro-api.py \
           --processar-todas-filas "$LIVROS" --limite 0)"
         printf '%s\n' "$PLANO_ENVIO"
         TOTAL_ENVIO="$(printf '%s' "$PLANO_ENVIO" | "$PY" -c \
           'import json,sys; print(json.load(sys.stdin).get("total_disponivel", 0))')"
         if [ "$TOTAL_ENVIO" = "0" ]; then
           echo ""
           printf "${A}   Nada novo foi enviado.${F}\n"
           echo "   A conferencia confirmou que nao ha material pronto pendente."
           echo "   Itens ja cadastrados ou reconhecidos na API nao sao reenviados."
         else
           echo ""
           echo "   Quantos materiais deseja enviar no total?"
           echo "   Use 0 para todos. O limite e dividido entre as filas."
           read -p "   Quantidade [20]: " LIMITE
           LIMITE="${LIMITE:-20}"
           case "$LIMITE" in (*[!0-9]*|'')
             printf "${A}   Quantidade invalida.${F}\n" ;;
           (*) echo ""
             printf "${A}   Livros, documentos, trabalhos academicos e revistas${F}\n"
             printf "${A}   serao cadastrados como PUBLICOS, um por vez.${F}\n"
             read -p "   Digite SIM para iniciar: " CONFIRMA
             case "$CONFIRMA" in
             [Ss][Ii][Mm])
               "$PY" enviar-livro-api.py --processar-todas-filas "$LIVROS" \
                 --limite "$LIMITE" --intervalo 3 --enviar ;;
             *) echo "   Envio cancelado. Todas as filas foram preservadas." ;;
             esac ;;
           esac
         fi
       fi ;;
   17) echo "   Abrindo a bancada local de revisão visual..."
       echo "   Ela mostra PDF ativo, capa, metadados, conflitos, causas de ausência,"
       echo "   páginas internas sugeridas, ISBNs válidos/suspeitos e grava revisões."
       echo ""
       "$PY" revisao-visual.py --raiz "$LIVROS" --limite 0 --abrir ;;
    0) echo "   Ate logo."; echo ""; exit 0 ;;
    *) printf "${A}   Opcao invalida.${F}\n" ;;
  esac

  echo ""; linha
  read -n 1 -s -r -p "   Tecla para voltar ao menu..."
  clear
done
