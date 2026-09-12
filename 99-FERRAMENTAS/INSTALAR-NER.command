#!/bin/bash
# =============================================================================
#  INSTALAR-NER - cria um ambiente proprio e poe o spaCy + modelos nele
# =============================================================================
#  Abra com DOIS CLIQUES.
#
#  Por que um ambiente proprio (.venv):
#    - o /usr/bin/python3 e o Python 3.9 do proprio macOS. O pip dele e
#      antigo e o sistema protege a instalacao. Nao se mexe nele.
#    - dentro do .venv nao precisa de nenhuma flag e nada do sistema muda.
#      Para desfazer tudo, basta apagar a pasta .venv.
#
#  O modelo tambem nao vem do PyPI (la so ha a versao 3.1, velha demais).
#  Vem da URL do release no GitHub.
#
#  Qualquer erro fica gravado em _resultado-ner.txt para eu ler.
# =============================================================================

cd "$(dirname "$0")" || exit 1
V=$'\033[0;32m'; R=$'\033[0;31m'; A=$'\033[0;33m'; N=$'\033[1m'; F=$'\033[0m'
LOG="$(pwd)/_resultado-ner.txt"; : > "$LOG"
reg(){ echo "$@" | tee -a "$LOG"; }

clear; printf "${N}   INSTALAR NER (spaCy)${F}\n\n"

# --- 1. achar um Python que o spaCy SUPORTE ----------------------------------
# Nao basta ser moderno: o 3.14 e novo demais, o spaCy instala e depois nao
# importa. E o 3.9 do sistema e velho demais e fica travado. A faixa boa
# hoje e 3.11 a 3.13, e o 3.12 e o mais seguro.
BASE_PY=""
for c in python3.12 python3.11 python3.13 python3.10; do
  p=$(command -v "$c" 2>/dev/null) || continue
  [ -x "$p" ] && { BASE_PY="$p"; break; }
done

if [ -z "$BASE_PY" ]; then
  printf "${A}   Nenhum Python na faixa 3.10-3.13 - instalando o 3.12...${F}\n"
  if command -v brew >/dev/null; then
    brew install python@3.12 2>&1 | tail -3
    for c in python3.12 /opt/homebrew/bin/python3.12 /usr/local/bin/python3.12; do
      p=$(command -v "$c" 2>/dev/null); [ -x "$p" ] && { BASE_PY="$p"; break; }
    done
  fi
fi
if [ ! -x "$BASE_PY" ]; then
  reg "FALHOU: nao achei Python 3.10-3.13 e nao consegui instalar o 3.12."
  reg "        (o python3 padrao aqui e $(python3 -V 2>&1), fora da faixa)"
  printf "\n${R}   Erro no log.${F}\n\n"; read -n1 -s -r -p "   Tecla..."; exit 1
fi
reg "python base ... $BASE_PY  ($("$BASE_PY" -V 2>&1))"

# --- 2. o ambiente proprio, FORA do Dropbox -----------------------------------
#
# Nao pode ficar junto dos scripts: esta pasta e sincronizada, e um
# ambiente virtual e feito de symlinks e caminhos absolutos. O Dropbox
# quebrou o link do python e encheu a pasta de "Copia em conflito".
# Aqui ele vive no seu diretorio pessoal, que ninguem sincroniza.
VENV="$HOME/.biblio-venv"

# tira da frente o .venv que ficou dentro do Dropbox
#
# NAO apagamos aqui: sao milhares de arquivos que o Dropbox ressincroniza
# enquanto o rm trabalha, e o script fica pendurado (aconteceu). Um
# rename e instantaneo, mesmo com a pasta cheia. A remocao vai para
# segundo plano e, se falhar, voce apaga pelo Finder sem pressa.
if [ -d ".venv" ]; then
  LIXO=".venv-descartado-$$"
  if mv .venv "$LIXO" 2>/dev/null; then
    reg "o .venv antigo (dentro do Dropbox) foi movido para $LIXO"
    ( rm -rf "$LIXO" >/dev/null 2>&1 & )
    printf "   apagando o antigo em segundo plano...\n"
  else
    reg "AVISO: nao consegui mover o .venv antigo - apague-o pelo Finder"
  fi
fi

if [ -x "$VENV/bin/python" ]; then
  VV=$("$VENV/bin/python" -c "import sys;print(f'{sys.version_info[0]}.{sys.version_info[1]}')" 2>/dev/null)
  case "$VV" in
    3.10|3.11|3.12|3.13) : ;;
    *) reg "descartando ambiente antigo (Python $VV, fora da faixa)"; rm -rf "$VENV" ;;
  esac
fi
if [ ! -x "$VENV/bin/python" ]; then
  printf "   criando ambiente em %s ...\n" "$VENV"
  "$BASE_PY" -m venv "$VENV" 2>&1 | tail -3 | tee -a "$LOG"
  printf "   ok\n"
fi
PY="$VENV/bin/python"
if [ ! -x "$PY" ]; then
  reg "FALHOU: nao consegui criar o .venv"
  printf "\n${R}   Erro no log.${F}\n\n"; read -n1 -s -r -p "   Tecla para fechar..."; exit 1
fi
reg "python .venv .. $("$PY" -V 2>&1)"
"$PY" -m pip install --upgrade pip --quiet 2>&1 | tail -2

# --- 3. requests (as APIs) e spaCy (o NER) ------------------------------------
if ! "$PY" -c "import requests" 2>/dev/null; then
  printf "   instalando requests...\n"
  "$PY" -m pip install requests --quiet 2>&1 | tail -2 | tee -a "$LOG"
fi
reg "requests ...... $("$PY" -c "import requests;print(requests.__version__)" 2>/dev/null || echo FALHOU)"

if ! "$PY" -c "import spacy" 2>/dev/null; then
  printf "   instalando spaCy - sao uns 40 pacotes, leva alguns minutos.\n"
  printf "   Se a tela ficar parada, esta trabalhando: aguarde.\n"
  "$PY" -m pip install spacy 2>&1 | tail -4 | tee -a "$LOG"
fi
VER=$("$PY" -c "import spacy;print(spacy.__version__)" 2>/dev/null)
if [ -z "$VER" ]; then
  # o erro de IMPORT e o que interessa - nao a saida do pip, que so diz
  # "requirement already satisfied" e esconde a causa
  reg "FALHOU: spaCy instalou mas nao importa. Erro real:"
  "$PY" -c "import spacy" 2>&1 | tail -12 | sed 's/^/   /' | tee -a "$LOG"
  printf "\n${R}   Erro no log.${F}\n\n"; read -n1 -s -r -p "   Tecla para fechar..."; exit 1
fi
SERIE=$(echo "$VER" | cut -d. -f1,2)
reg "spaCy ......... $VER   (modelos da serie $SERIE.0)"
reg ""

# --- 4. modelos ---------------------------------------------------------------
BASE="https://github.com/explosion/spacy-models/releases/download"
for M in es_core_news_sm pt_core_news_sm en_core_web_sm; do
  if "$PY" -c "import $M" 2>/dev/null; then reg "$M ... ja instalado"; continue; fi
  printf "   baixando %s...\n" "$M"
  URL="$BASE/$M-$SERIE.0/$M-$SERIE.0-py3-none-any.whl"
  if "$PY" -m pip install "$URL" --quiet 2>/dev/null; then
    reg "$M ... OK ($SERIE.0)"
  elif "$PY" -m spacy download $M 2>/dev/null; then
    reg "$M ... OK (via spacy download)"
  else
    reg "$M ... FALHOU  ($URL)"
    "$PY" -m pip install "$URL" 2>&1 | tail -6 | sed 's/^/      /' >> "$LOG"
  fi
done

# --- 5. prova real ------------------------------------------------------------
reg ""; reg "---------- teste: pessoa x titulo x instituicao ----------"
"$PY" - 2>&1 <<'PY' | tee -a "$LOG"
import spacy
FRASES = [("SE LIDER","titulo"), ("PAUL DAVID TRIPP","pessoa"),
          ("EL DOLOR DE LA PERDIDA","titulo"), ("HERMAN BAVINCK","pessoa"),
          ("DOGMATICA REFORMADA","titulo"), ("William Cunningham","pessoa"),
          ("Sociedad de Traduccion Reformada Holandesa","instituicao"),
          ("Editorial Portavoz","instituicao")]
carregou=[]
for m in ("es_core_news_sm","pt_core_news_sm"):
    try: carregou.append((m,spacy.load(m)))
    except Exception as e: print(f"  {m}: nao carregou ({str(e)[:60]})")
if not carregou:
    print("  NENHUM MODELO CARREGOU"); raise SystemExit
for nome,nlp in carregou:
    print(f"\n  [{nome}]")
    for f,esperado in FRASES:
        ents=[(e.text,e.label_) for e in nlp(f).ents]
        print(f"    {f[:42]:44} esperado={esperado:12} -> {ents}")
PY

reg ""; reg "=============================== fim ==============================="
printf "\n${V}   Pronto.${F}  Log em: %s\n" "$LOG"
printf "   Ambiente em: %s\n" "$VENV"
printf "   Agora rode o LIVROS.command.\n\n"
read -n 1 -s -r -p "   Tecla para fechar..."
