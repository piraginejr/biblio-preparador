#!/bin/bash
# =============================================================================
#  TESTAR-CAPAS - mede a leitura de capa com TUDO no lugar
# =============================================================================
#  Abra com DOIS CLIQUES. Nao precisa digitar nada.
#
#  Instala o que falta, compila o utilitario do Vision, roda os 4 cenarios
#  e grava tudo em _resultado-capas.txt - e esse arquivo que o Claude le
#  para comparar. Nada e enviado para lugar nenhum: o texto fica no seu Mac.
# =============================================================================

cd "$(dirname "$0")" || exit 1
V=$'\033[0;32m'; A=$'\033[0;33m'; R=$'\033[0;31m'; N=$'\033[1m'; F=$'\033[0m'
SAIDA="$(pwd)/_resultado-capas.txt"
: > "$SAIDA"

reg() { echo "$@" | tee -a "$SAIDA"; }

clear
printf "${N}   MEDIR LEITURA DE CAPA${F}\n\n"

# --- 1. onde estao os livros --------------------------------------------------
PADRAO="$(cd .. && pwd)/livros"
read -p "   Pasta dos livros [$PADRAO]: " LIVROS
LIVROS="${LIVROS:-$PADRAO}"
[ -d "$LIVROS" ] || { printf "${R}   Pasta nao encontrada.${F}\n"; read -n1 -s; exit 1; }

# --- 2. dependencias ----------------------------------------------------------
printf "\n${N}   Preparando...${F}\n"

# Se o INSTALAR-NER.command ja criou o ambiente proprio, usamos ele. O
# python3 do sistema e o 3.9 do macOS e nao aceita instalar nada.
# O ambiente vive FORA do Dropbox: venv e feito de symlinks e caminhos
# absolutos, e a sincronia quebra os dois. Criado pelo INSTALAR-NER.command.
VENV="$HOME/.biblio-venv"
if [ -x "$VENV/bin/python" ]; then
  PY="$VENV/bin/python"
else
  PY="$(command -v python3)"
fi

command -v brew >/dev/null || { printf "${R}   Homebrew ausente: https://brew.sh${F}\n"; read -n1 -s; exit 1; }
command -v tesseract >/dev/null || { echo "   instalando tesseract..."; brew install tesseract tesseract-lang; }
brew list tesseract-lang >/dev/null 2>&1 || brew install tesseract-lang
command -v pdftoppm >/dev/null || brew install poppler

# spaCy: o modelo NAO vem pelo 'spacy download' (vai ao GitHub). Vem pelo pip.
# O spaCy e os modelos sao instalados pelo INSTALAR-NER.command, que cria
# o .venv. Aqui so verificamos - a medicao roda com o que houver.
if ! "$PY" -c "import spacy" 2>/dev/null; then
  printf "${A}   spaCy ausente - rode antes o INSTALAR-NER.command${F}\n"
  printf "   (a medicao segue, mas sem a camada de NER)\n"
fi

# Vision: o mesmo motor do app de cartoes
if { [ ! -x ./vision-ocr ] || [ ./vision-ocr.swift -nt ./vision-ocr ]; } && \
   [ -f ./vision-ocr.swift ]; then
  echo "   compilando vision-ocr..."
  VISION_TMP="${TMPDIR:-/tmp}/biblio-vision-ocr-$$"
  if [ -d /Applications/Xcode.app/Contents/Developer ]; then
    CLANG_MODULE_CACHE_PATH="${TMPDIR:-/tmp}/biblio-clang-cache" \
      DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer \
      xcrun swiftc -O vision-ocr.swift -o "$VISION_TMP" 2>/dev/null
  else
    swiftc -O vision-ocr.swift -o "$VISION_TMP" 2>/dev/null
  fi
  if [ -x "$VISION_TMP" ]; then mv "$VISION_TMP" vision-ocr; fi
  chmod +x vision-ocr 2>/dev/null
fi

# --- 3. o que ficou disponivel ------------------------------------------------
TEM_NER=$("$PY" -c "import sys;sys.path.insert(0,'.');import identificar;print(identificar.tem_ner())" 2>/dev/null)
[ -x ./vision-ocr ] && TEM_VIS="True" || TEM_VIS="False"

reg "=========================================================="
reg " MEDICAO DE LEITURA DE CAPA   $(date '+%Y-%m-%d %H:%M')"
reg "=========================================================="
reg " macOS ......... $(sw_vers -productVersion 2>/dev/null)"
reg " tesseract ..... $(tesseract --version 2>&1 | head -1)"
reg " idiomas ....... $(tesseract --list-langs 2>/dev/null | tail -n +2 | tr '\n' ' ')"
reg " spaCy NER ..... $TEM_NER"
reg " Vision OCR .... $TEM_VIS"
reg " livros ........ $(ls "$LIVROS"/*.pdf 2>/dev/null | wc -l | tr -d ' ')"
reg ""

# a caixa alta atrapalha o NER; conferimos o efeito da normalizacao
if [ "$TEM_NER" = "True" ]; then
  reg "---------- NER: caixa alta x caixa normalizada ----------"
  "$PY" - 2>&1 <<'PY' | tee -a "$SAIDA"
import sys, os; sys.path.insert(0, os.getcwd())
import identificar as I
for t in ["PAUL DAVID TRIPP", "HERMAN BAVINCK", "JOHN MACARTHUR",
          "WILLIAM CUNNINGHAM", "BOYD BAILEY", "ROBSON RODOVALHO",
          "SE LIDER", "DOGMATICA REFORMADA", "ETICA REFORMADA",
          "EDITORIAL PORTAVOZ"]:
    cru, _  = I.ner_pessoa_org([t])
    n = I.caixa_normal(t)
    I._NLP and None
    print(f"  {t[:26]:28} -> {n[:26]:28} pessoa={cru or '—'}")
PY
  reg ""
fi

# --- 4. capas a 300 dpi -------------------------------------------------------
CAPAS="$LIVROS/_capas300"; mkdir -p "$CAPAS"
printf "${N}   Gerando capas a 300 dpi...${F}\n"
for pdf in "$LIVROS"/*.pdf; do
  b=$(basename "$pdf" .pdf)
  [ -f "$CAPAS/$b.jpg" ] || pdftoppm -f 1 -l 1 -r 300 -jpeg -singlefile "$pdf" "$CAPAS/$b" 2>/dev/null
done

# --- 5. os quatro cenarios ----------------------------------------------------
rodar() {   # $1=rotulo  $2=usar_vision  $3=usar_ner
  reg ""; reg "---------- $1 ----------"
  USAR_VISION=$2 USAR_NER=$3 "$PY" - "$CAPAS" 2>&1 <<'PY' | tee -a "$SAIDA"
import sys, os, glob, importlib.util
sys.path.insert(0, os.getcwd())
spec = importlib.util.spec_from_file_location("lcap", "ler-capa.py")
m = importlib.util.module_from_spec(spec); sys.modules["lcap"] = m; spec.loader.exec_module(m)
import identificar

if os.environ.get("USAR_VISION") != "1":
    m._ocr_vision = lambda img: None
if os.environ.get("USAR_NER") != "1":
    identificar._NLP = None; identificar._NER_TENTADO = True

for img in sorted(glob.glob(os.path.join(sys.argv[1], "*.jpg"))):
    d = m.ler(img)
    print(f"{os.path.basename(img)[:38]:40} | {d['titulo'][:38]:40} | "
          f"{d['nmAutor0'][:24]:26} | {d['confianca']}/{d['origem_autor']}")
PY
}

printf "${N}   Medindo (4 cenarios)...${F}\n\n"
rodar "Tesseract, sem NER   (o piso ja medido)" 0 0
[ "$TEM_NER"  = "True" ] && rodar "Tesseract + NER"        0 1
[ "$TEM_VIS"  = "True" ] && rodar "Vision, sem NER"        1 0
[ "$TEM_NER" = "True" ] && [ "$TEM_VIS" = "True" ] && rodar "Vision + NER  (completo)" 1 1

reg ""; reg "=========================== fim ==========================="
printf "\n${V}   Pronto.${F}  Resultado em:\n   %s\n\n" "$SAIDA"
printf "   Diga ao Claude para ler o _resultado-capas.txt.\n\n"
read -n 1 -s -r -p "   Pressione qualquer tecla para fechar..."
