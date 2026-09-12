#!/usr/bin/env bash
#
# ============================================================================
#  VOICE MAGAZINE (FGBMFI) - Download e OCR em duas etapas
# ============================================================================
#
#  Etapa 1: baixa e valida os 151 originais publicados em
#  fgbmfi.org/resources.
#
#  Etapa 2: aplica OCR individualmente e salva cada resultado na pasta anual
#  do projeto, junto com o texto extraido para pesquisa.
#
#  Os PDFs originais sao scans de imagem, sem texto. Depois do OCR ficam
#  pesquisaveis no Preview, Adobe, Spotlight e via grep/pdfgrep.
#
#  USO:
#      ./baixar-voice-fgbmfi.sh --baixar
#      ./baixar-voice-fgbmfi.sh --ocr
#      ./baixar-voice-fgbmfi.sh --status
#
#  Pode interromper (Ctrl+C) e rodar de novo: ele retoma de onde parou.
#
#  Uso pessoal / pesquisa. O conteudo e de copyright da FGBMFI - nao
#  redistribua os arquivos.
# ============================================================================

set -uo pipefail

# ---------------------------------------------------------------------------
# CONFIGURACAO
# ---------------------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RAIZ="$(cd "$SCRIPT_DIR/.." && pwd)"

IDIOMA_OCR="eng"        # revista e em ingles. Para adicionar: "eng+por"
JOBS=4                  # nucleos usados pelo OCR
PAUSA=1                 # segundos entre downloads (educado com o servidor)
LIMITE=0                # 0 = todas; util para testes

BASE_URL="https://www.fgbmfi.org/_files/ugd/f77bb3_"

# ---------------------------------------------------------------------------

DIR_RAW="$SCRIPT_DIR/_originais_sem_ocr"
DIR_FINAL="$RAIZ/01-EDICOES-PDF"
DIR_TXT="$RAIZ/02-MINERACAO"
LOG="$SCRIPT_DIR/baixar-voice-fgbmfi.log"

VERDE=$'\033[0;32m'; AMARELO=$'\033[0;33m'; VERMELHO=$'\033[0;31m'
AZUL=$'\033[0;34m';  NEGRITO=$'\033[1m';    FIM=$'\033[0m'

msg()  { printf "%s\n" "$*"; }
ok()   { printf "${VERDE}  OK${FIM}  %s\n" "$*"; }
warn() { printf "${AMARELO}  !!${FIM}  %s\n" "$*"; }
err()  { printf "${VERMELHO}  XX${FIM}  %s\n" "$*"; }
log()  { printf "%s  %s\n" "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG"; }

# ---------------------------------------------------------------------------
# DEPENDENCIAS
# ---------------------------------------------------------------------------

checar_dependencias() {
  local etapa="$1"
  local faltando=()

  command -v curl      >/dev/null 2>&1 || faltando+=("curl")
  if [ "$etapa" = "ocr" ]; then
    command -v ocrmypdf  >/dev/null 2>&1 || faltando+=("ocrmypdf")
    command -v tesseract >/dev/null 2>&1 || faltando+=("tesseract")
    command -v pdftotext >/dev/null 2>&1 || faltando+=("poppler (pdftotext)")
    command -v qpdf      >/dev/null 2>&1 || faltando+=("qpdf")
  fi

  if [ ${#faltando[@]} -gt 0 ]; then
    err "Faltam dependencias: ${faltando[*]}"
    msg ""
    msg "${NEGRITO}Instale com Homebrew:${FIM}"
    msg ""
    if ! command -v brew >/dev/null 2>&1; then
      msg '  # Primeiro o Homebrew:'
      msg '  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
      msg ''
    fi
    msg "  brew install ocrmypdf tesseract poppler"
    msg ""
    msg "  # opcional, se quiser OCR em portugues tambem:"
    msg "  brew install tesseract-lang"
    msg ""
    exit 1
  fi

  [ "$etapa" != "ocr" ] && return

  # confere se o idioma pedido esta instalado
  local idioma
  for idioma in ${IDIOMA_OCR//+/ }; do
    if ! tesseract --list-langs 2>/dev/null | grep -qx "$idioma"; then
      err "Idioma '$idioma' nao instalado no Tesseract."
      msg "  Rode:  brew install tesseract-lang"
      exit 1
    fi
  done
}

# ---------------------------------------------------------------------------
# CATALOGO - 151 edicoes  (nome_do_arquivo|id_no_servidor)
# ---------------------------------------------------------------------------

read -r -d '' CATALOGO <<'EOF'
1953-02|fb94e6ffcd8444afb2e5e4f5483ca6bc
1956-07|6dd232ebfb4b45c9985ddb6a862e9c4e
1960-06|e29965fc9508425eb2423f06eeb2b2fe
1960-07-08|56a4ea6bd4f1446bbfaeb42492d4612f
1960-10|2dff55f4985745df903439968044f0af
1960-11|eb779881b52d47f497c392a8da3ab5c6
1960-12|3c0d653da1994009800873fe47af4efc
1961-01|958e86ac24fe49daae1e251057ba0358
1961-02|9f29e4feecd145c29d43e6676c2d622d
1961-07|601f2a0c84b34e638710726d25032446
1961-09|d479ad8e32d840fcb369bf93efbd804c
1962-11|afff5c5a2fbc4c14bfa1385275bb9742
1963-01|0f2a6ddf69024819bcb84104a4a9d41f
1963-02|30fdabe134d54b26be20202758f3ca90
1963-04|cc197b918a474527bd91bf211dac797a
1964-12|80fb6e2c234b4822bb78cfeb5a6abd85
1965-01|53c21c6976644a00a7dc9cd28d7e59fa
1965-05|fa936a4b64924a588e4161522b786948
1965-10|ef360b05083f42fb97f43fcfd9b22efd
1966-05|35f15c69576f4fe2b1e9a2d487996d0c
1967-03|dc56f6b5d4404e3bb9b31161b540ac21
1967-04|86055894a78f43299ae9fbb2cea23b82
1967-06|c0da369219684d16b462e28262542628
1967-09|dd368f8ffb3f46988550886e4fc6a12c
1970-11|a0ce1c6c35544ca799d2b063fe10bfad
1971-04|cbdb43278e5b46aba8e01baed91dbbbe
1971-09|e630f10e84b54e02a1cae0c2a64c3d7f
1971-10|9fc2bbfcfa03403cb4c1a274897c8ab1
1972-03|9465fe054cab419a920ee8c02594fec0
1972-06|21577f1c04c84c8fbea346a3c1abb515
1972-10|6b1e5da769024897a97c7c80bbc9e08f
1973-04|249c3677eb6b4dd1b014413fa2129c4a
1973-07-08|b87d439d35bd436ba21cc67601b3bebc
1973-12|c133fe3a51684551ba261d7134d45aba
1974-02|6bd1ed47bb404489b8bc317fa9ae7a69
1974-03|f2e9aa07daba407fbdc44a1e1c25ba39
1975-01|d16bbb87b08b42eb8df1ecbed638a55d
1975-02|70b860f403fe4702be08c7f14ac91d93
1975-03|fc3ad865526142b09c523ed86f93e1ad
1975-04|12f092d9ca7145dda9cba9346a41752e
1975-07-08|cb15e73be1a544f99dad35848d98afaa
1975-09|8304e7d6f4624d9e93473bbc0815a79b
1976-06|49de130782604e4099458b3da1a61713
1976-09|f67155d0e07846f087bc9d3fe7d930c7
1977-01|4b48a05419a241fda02223aa42b98132
1977-02|06bc6f645d5b41a09dae68039b84e8c8
1977-03|d9b901f18ba54ef8ae438a85d34f0c6e
1977-04|e3a18d3c750f4afd8a8f18c463350142
1977-12|9ebd4991f69f4f59956b0b330c3845f6
1978-01|4d401f984d544764becd4f84ae9b6257
1978-03|1bdb180aa0b346c1ac185aede6ae7e86
1978-06|a0a8828455034987b05aa592d1dbd196
1980-03|0f078e6a2b894b93844a7d0810c16f5c
1980-04|2ce13acd40924e7ebd78878df8bbe0fc
1980-05|651d47813b6844f1984b2af59c98a656
1980-06|e49cec8898c64f92a24bf5b4d5f1842b
1981-03|89fe2dca12b940d2960d980dee89d1ab
1981-04|0cb0f638ea5f43d7a70c24e153d161b9
1981-05|e374d79255f946a88af9eaa7a7a54353
1981-06|1cdd7a7c88664f1284b7ce8d6134f2cc
1981-10|1514df9efca64b98a93e539c12f201c1
1981-11|b7c94d5cd80c480cae4dc63134ab137b
1981-12|aaea6bc2f28f4a35b45e3dfa6e81b86a
1982-02|53e33bc1c6f04f1a8bc9ad45915c2df8
1982-05|cf57d544bf3a481181006c02a3bd31e3
1982-06|bd2b86bfffc846e9ba779945fdfb97b0
1982-07-08|c425312cfd14424f9f1f5a7ee41cc617
1982-09|20f8665049884be384611bce67e63a20
1982-12|c35419b81ac0488482ced276518567c3
1983-01|b93a8cc36e714ec6b6e2af7ea151c94a
1983-02|641d7509d484463e806ad31a5918ad87
1983-04|9f8cec91efd54328ae35180fd0950156
1983-07-08|d7795cccaaf24a03a84fd614ead261b6
1983-09|8edcf68c3d2c4befa32fec7c1bcb4c91
1983-10|97850795ceda41fdbb560d76ce745c0c
1983-11|2ee205e463024bc99d2e8639d8fb984f
1984-02|785c5b8fbb1e4a4aafdfa0df50d7752e
1984-03|6948011493a64bcb9694f2cf50d16589
1984-04|72fb2ee8503e4f818c153ef9b2c65c98
1984-05|fa5751be86ed46a0b14d19ef056bf19e
1984-08|27f73ccbd1d147aeb3545f34a090ae48
1984-09|e4e789dcf11440aba4e456c0871e768b
1984-10|90094e7fd02544dc9580d5885d3e2e6f
1984-11|f5ed9dc27fb247a2b28131522cd54d56
1985-02|b8521d750c2e41baba51b9c22ea2d83f
1985-03|01e90ca9293d4ec0a9c721e1aefc9f26
1985-04|1fbd6909a2db4e979e24cc1a863c1381
1985-05|459964eabe1c4057bd5576f64c75f841
1985-09|b2ffe06315e242078922a7fea0f1acbc
1985-10|6e0b1569f1fd462fa30b26fda31c3331
1985-11|ddf53e8f52c24232ab44072ad9b51b90
1986-01|c279e6c2dbd04676b7e60d0368dd5936
1986-04|e23c1a3c1bbd422c9387dbe69e04a153
1986-05|373fd2aadff54dcb9248256aec0b2417
1986-06|f1f6965fbc994f589a05a28cdc864508
1986-07|9e50482058e84514b4f7fe4b7b3e0893
1986-10|0eca179404e744e4837d2c67f89f0c3a
1986-11|f4f91dd37033425dae6fea3d67d0a8ea
1986-12|3c9db77e6ad44931bf288066f475ee11
1987-02|ab46fe7270354620a615ce3d286a3b8e
1987-05|288b5343794b40b48b1311deabc323dd
1987-09|7a23725d2818487f903141fc4336d7d6
1988-01|dda77a6f95ae48e89bda440441c54a72
1988-02|4a84fdc4ab044973b1048a894daabfd5
1988-06|99b9972b0ef24de3890efa811cec1a0a
1988-07|139c6ae65f8b472fa953d25e61af373f
1988-08|913240a14c514369a122191ea24d9288
1988-09|6c853b4d06c54deaad4a919a6a2f144a
1989-07|88b2db0320094a0d895799a5b27593cb
1990-02|f4560cff4cba426f9877c1b6f1da23ef
1990-07|242b470c73684243a3a14348e81b5480
1991-09|0628b3d106a64ea7b063b73338bf15e7
1992-09|451a830646e4417c97d16d651d04ff84
1992-12|2ce7949994514f72af7187a490cce478
1993-01|2b7d1da4e4a84f8fa051c962e791b007
1993-02|08cf5cf25c594728a26dd042115f6878
1993-08|013cc599a66a4ec095977501320e50f4
1993-10|074427fba5354e90a71299a3a26233f7
1993-11|ae67f294fefb4909a28802303ab5fba7
1994-10|3965d5a71bb940a58c806aef4f760f12
1994-11|e559a9440ab940c8ab7efd914e356ee3
1994-global-report|5cabfaccea204c7cad834a7613b7d9f9
1995-01|2fc70537df4042d2ab2f52785f0cd71c
1995-02|de768ce7dd3844b088af56db146da9db
1996-06|f7bc070a18d54358962d216e641ab00b
1997-10|d2eb98afe26d4f45bb38e8ea4204d67e
1998-07|8fd8381076744051b0fb6a9f9ead0690
1998-09|823d88fe8a5e479b96468a61e4735c80
1999-01|a725f3cde7c84ad7bdb71f7c3ca2d08d
1999-02|a09e1161138b412694f823172fd388f2
1999-03|8d916bc9a57148269fd8bdfdc30e079d
1999-04|0015efdaaa9741dca0ff92b2c82f5bc6
1999-07|72e0319af8ec46db87fe581e986e9197
1999-08|de94a727fe0346fc8136cea495678892
1999-09|02da5b28cdd5434e9f6871061057871f
1999-10|653f0df97bec4e0cab0f3718dbf0c2e1
2000-03|9315a39a572549e38d5876907d0633c7
2000-04|3447b5f6c50842298bd71ac1fc0ac36f
2000-10|32ff5c7278064a3198fa84144582ebce
2001-02|b85b461cde514f6cbfa6828e0bfa593a
2002-07|177c83466bb943af8b63a6686ee0c940
2003-01|7025399f0ae74965aacc7e873d2d3488
2003-06|3951eb0e7182429f98e0e788cc8acb4a
2003-07|d4eae0d4412547df8bce1cfb9a04b05f
2006-01|4c1661f078334f4a95a399d8c5f97235
2006-03|0bcb04cf56fc4bc09ef89ab80d8e288b
2006-12|a506078f649d4f45939103f3fdec984a
2007-01-02|84408751fcc74f1d97f95a08a7781238
2007-11-12|4aef91a67e484088bb1f2239c76c4c7e
2008-01-02|e3a8174faecc40cd82f1ba67be67e2a3
2016-world-convention|a6995db966574a1d95b4e6a95234280a
EOF

# ---------------------------------------------------------------------------
# EXECUCAO
# ---------------------------------------------------------------------------

uso() {
  msg "Uso:"
  msg "  $0 --baixar [--limite N] [--edicao AAAA-MM]"
  msg "  $0 --ocr     [--limite N] [--edicao AAAA-MM]"
  msg "  $0 --status"
  msg ""
  msg "Etapas:"
  msg "  --baixar  baixa e valida somente os originais"
  msg "  --ocr     aplica OCR e instala no acervo anual"
  msg "  --status  mostra o progresso sem alterar arquivos"
}

pdf_valido() {
  local arquivo="$1"
  [ -s "$arquivo" ] && [ "$(head -c 5 "$arquivo" 2>/dev/null)" = "%PDF-" ]
}

qpdf_valido() {
  local arquivo="$1"
  local codigo
  qpdf --check "$arquivo" >>"$LOG" 2>&1
  codigo=$?
  # QPDF usa 3 quando conclui com advertencias recuperaveis.
  [ "$codigo" -eq 0 ] || [ "$codigo" -eq 3 ]
}

nome_mes() {
  case "$1" in
    01) msg "January" ;;
    02) msg "February" ;;
    03) msg "March" ;;
    04) msg "April" ;;
    05) msg "May" ;;
    06) msg "June" ;;
    07) msg "July" ;;
    08) msg "August" ;;
    09) msg "September" ;;
    10) msg "October" ;;
    11) msg "November" ;;
    12) msg "December" ;;
    *)  msg "" ;;
  esac
}

edicao_ja_no_acervo() {
  local rotulo="$1"
  local ano="${rotulo%%-*}"
  local resto="${rotulo#*-}"
  local mes="${resto%%-*}"
  local pasta="$DIR_FINAL/$ano"
  local arquivo base mes_nome

  [ -d "$pasta" ] || return 1
  mes_nome="$(nome_mes "$mes")"

  shopt -s nullglob nocasematch
  for arquivo in "$pasta"/*.pdf; do
    base="$(basename "$arquivo")"
    if [[ "$base" == *"$rotulo"* ]]; then
      msg "$arquivo"
      shopt -u nullglob nocasematch
      return 0
    fi
    if [[ "$rotulo" == *-07-08 ]] &&
       [[ "$base" == *"July-Aug"*"$ano"* ]]; then
      msg "$arquivo"
      shopt -u nullglob nocasematch
      return 0
    fi
    if [ -n "$mes_nome" ] && [[ "$base" == *"$mes_nome"*"$ano"* ]]; then
      msg "$arquivo"
      shopt -u nullglob nocasematch
      return 0
    fi
  done
  shopt -u nullglob nocasematch
  return 1
}

selecionada() {
  local rotulo="$1"
  [ -z "$FILTRO" ] || [ "$rotulo" = "$FILTRO" ]
}

MODO=""
FILTRO=""
while [ $# -gt 0 ]; do
  case "$1" in
    --baixar|--ocr|--status)
      [ -z "$MODO" ] || { err "Escolha apenas uma etapa."; exit 2; }
      MODO="${1#--}"
      shift
      ;;
    --limite)
      [ $# -ge 2 ] || { err "--limite exige um numero."; exit 2; }
      LIMITE="$2"
      shift 2
      ;;
    --edicao)
      [ $# -ge 2 ] || { err "--edicao exige um rotulo."; exit 2; }
      FILTRO="$2"
      shift 2
      ;;
    -h|--help)
      uso
      exit 0
      ;;
    *)
      err "Opcao desconhecida: $1"
      uso
      exit 2
      ;;
  esac
done

[ -n "$MODO" ] || { uso; exit 2; }
[[ "$LIMITE" =~ ^[0-9]+$ ]] || { err "Limite invalido: $LIMITE"; exit 2; }

TOTAL=$(printf "%s\n" "$CATALOGO" | grep -c .)
mkdir -p "$DIR_RAW" "$DIR_FINAL" "$DIR_TXT"

msg ""
msg "${NEGRITO}${AZUL}  VOICE MAGAZINE (FGBMFI) - DUAS ETAPAS${FIM}"
msg "${AZUL}  ------------------------------------------${FIM}"
msg "  Modo:       $MODO"
msg "  Catalogo:   $TOTAL edicoes"
msg "  Originais:  $DIR_RAW"
msg "  PDFs OCR:   $DIR_FINAL/<ano>"
msg "  Textos:     $DIR_TXT/<ano>"
[ -n "$FILTRO" ] && msg "  Edicao:     $FILTRO"
[ "$LIMITE" -gt 0 ] && msg "  Limite:     $LIMITE"
msg ""

if [ "$MODO" = "status" ]; then
  RAW_OK=0
  NO_ACERVO=0
  SELECIONADAS=0
  while IFS='|' read -r ROTULO ID; do
    [ -n "$ROTULO" ] || continue
    selecionada "$ROTULO" || continue
    SELECIONADAS=$((SELECIONADAS+1))
    pdf_valido "$DIR_RAW/Voice-${ROTULO}-original.pdf" && RAW_OK=$((RAW_OK+1))
    edicao_ja_no_acervo "$ROTULO" >/dev/null && NO_ACERVO=$((NO_ACERVO+1))
  done <<< "$CATALOGO"
  msg "  Originais validos ....... $RAW_OK / $SELECIONADAS"
  msg "  Edicoes no acervo ....... $NO_ACERVO / $SELECIONADAS"
  exit 0
fi

checar_dependencias "$MODO"
log "=== Inicio: modo=$MODO filtro=${FILTRO:-todos} limite=$LIMITE ==="

N=0
CONCLUIDAS=0
JA_TINHA=0
FALHAS=0
PULADAS=0
declare -a LISTA_FALHAS=()

while IFS='|' read -r ROTULO ID; do
  [ -n "$ROTULO" ] || continue
  selecionada "$ROTULO" || continue
  [ "$LIMITE" -eq 0 ] || [ "$N" -lt "$LIMITE" ] || break
  N=$((N+1))

  ANO="${ROTULO%%-*}"
  NOME="Voice-${ROTULO}"
  RAW="$DIR_RAW/${NOME}-original.pdf"
  URL="${BASE_URL}${ID}.pdf"
  FINAL_DIR="$DIR_FINAL/$ANO"
  TXT_DIR="$DIR_TXT/$ANO"
  FINAL="$FINAL_DIR/${NOME}.pdf"
  TXT="$TXT_DIR/${NOME}.txt"

  printf "${NEGRITO}[%3d]${FIM} %s\n" "$N" "$NOME"

  if [ "$MODO" = "baixar" ]; then
    if pdf_valido "$RAW"; then
      ok "original ja existe"
      JA_TINHA=$((JA_TINHA+1))
      continue
    fi

    if [ -e "$RAW" ]; then
      mv "$RAW" "$RAW.invalido-$(date '+%Y%m%d-%H%M%S')"
      warn "original anterior era invalido e foi preservado com outro nome"
    fi

    INICIO=$(date +%s)
    if curl -fsSL --retry 4 --retry-delay 3 --connect-timeout 30 \
            -A "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)" \
            -o "$RAW.part" "$URL" &&
       pdf_valido "$RAW.part"; then
      mv "$RAW.part" "$RAW"
      DURACAO=$(( $(date +%s) - INICIO ))
      ok "baixado em ${DURACAO}s ($(du -h "$RAW" | cut -f1 | tr -d ' '))"
      log "DOWNLOAD ok  $NOME  ${DURACAO}s"
      CONCLUIDAS=$((CONCLUIDAS+1))
    else
      [ -e "$RAW.part" ] && mv "$RAW.part" "$RAW.falhou-$(date '+%Y%m%d-%H%M%S')"
      err "download falhou ou nao retornou um PDF"
      log "DOWNLOAD FALHOU  $NOME  $URL"
      LISTA_FALHAS+=("$NOME (download)")
      FALHAS=$((FALHAS+1))
    fi
    sleep "$PAUSA"
    continue
  fi

  # Modo OCR.
  if ! pdf_valido "$RAW"; then
    warn "original ausente; execute --baixar primeiro"
    PULADAS=$((PULADAS+1))
    continue
  fi

  if EXISTENTE="$(edicao_ja_no_acervo "$ROTULO")"; then
    ok "edicao ja esta no acervo: $(basename "$EXISTENTE")"
    JA_TINHA=$((JA_TINHA+1))
    continue
  fi

  mkdir -p "$FINAL_DIR" "$TXT_DIR"
  INICIO=$(date +%s)
  printf "        aplicando OCR..."
  if ocrmypdf \
        --language "$IDIOMA_OCR" \
        --rotate-pages \
        --deskew \
        --skip-text \
        --optimize 1 \
        --jobs "$JOBS" \
        --quiet \
        "$RAW" "$FINAL.part" 2>>"$LOG" &&
     pdf_valido "$FINAL.part" &&
     qpdf_valido "$FINAL.part"; then
    DURACAO=$(( $(date +%s) - INICIO ))
    mv "$FINAL.part" "$FINAL"
    printf "\r"
    ok "OCR concluido em ${DURACAO}s -> $ANO/${NOME}.pdf"
    log "OCR ok  $NOME  ${DURACAO}s"
    CONCLUIDAS=$((CONCLUIDAS+1))

    if pdftotext -layout "$FINAL" "$TXT.part" 2>>"$LOG"; then
      mv "$TXT.part" "$TXT"
      ok "texto extraido -> $ANO/${NOME}.txt"
    else
      [ -e "$TXT.part" ] && mv "$TXT.part" "$TXT.falhou"
      warn "PDF OCR esta valido, mas a extracao do TXT falhou"
      log "TXT FALHOU  $NOME"
    fi
  else
    printf "\r"
    [ -e "$FINAL.part" ] && mv "$FINAL.part" "$FINAL.falhou"
    err "OCR falhou; original preservado e nada foi instalado no acervo"
    log "OCR FALHOU  $NOME"
    LISTA_FALHAS+=("$NOME (ocr)")
    FALHAS=$((FALHAS+1))
  fi
done <<< "$CATALOGO"

msg ""
msg "${AZUL}  ------------------------------------------${FIM}"
msg "${NEGRITO}  RESUMO DA ETAPA${FIM}"
msg ""
msg "    Concluidas agora ...... $CONCLUIDAS"
msg "    Ja existiam ........... $JA_TINHA"
msg "    Puladas ................ $PULADAS"
msg "    Falhas ................. $FALHAS"

if [ ${#LISTA_FALHAS[@]} -gt 0 ]; then
  msg ""
  warn "Itens com problema:"
  for item in "${LISTA_FALHAS[@]}"; do
    msg "      - $item"
  done
fi

msg ""
if [ "$MODO" = "baixar" ]; then
  msg "  Proxima etapa, somente depois de concluir os downloads:"
  msg "    $0 --ocr"
else
  msg "  Pesquisa:"
  msg "    PDFs:   $DIR_FINAL"
  msg "    Textos: $DIR_TXT"
fi
msg ""

log "=== Fim: modo=$MODO concluidas=$CONCLUIDAS existentes=$JA_TINHA puladas=$PULADAS falhas=$FALHAS ==="
