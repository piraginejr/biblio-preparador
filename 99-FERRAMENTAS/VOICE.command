#!/bin/bash
#
# =============================================================================
#  LANCADOR - Cadastro da revista Voice no PIB-Biblio
# =============================================================================
#  Abra com DOIS CLIQUES. Nao precisa digitar nada no terminal.
#  Este arquivo e o cadastrar-voice.py devem ficar na MESMA pasta.
# =============================================================================

cd "$(dirname "$0")" || exit 1

V=$'\033[0;32m'; A=$'\033[0;33m'; R=$'\033[0;31m'
AZ=$'\033[0;34m'; N=$'\033[1m'; F=$'\033[0m'

linha() { printf "${AZ}  %s${F}\n" "------------------------------------------------------------"; }

clear
echo ""
printf "${N}${AZ}   VOICE  ->  PIB-Biblio${F}\n"
linha
echo ""

# ---------------------------------------------------------------------------
# 1. o script python esta aqui?
# ---------------------------------------------------------------------------
if [ ! -f "cadastrar-voice.py" ]; then
  printf "${R}   Nao encontrei o arquivo cadastrar-voice.py${F}\n\n"
  echo "   Ele precisa estar nesta mesma pasta:"
  echo "   $(pwd)"
  echo ""
  echo "   Mova os dois arquivos para a mesma pasta e abra este de novo."
  echo ""
  read -n 1 -s -r -p "   Pressione qualquer tecla para fechar..."
  exit 1
fi

# ---------------------------------------------------------------------------
# 2. dependencias
# ---------------------------------------------------------------------------
printf "${N}   Verificando o que e necessario...${F}\n\n"

FALTA=0

if ! command -v python3 >/dev/null 2>&1; then
  printf "${R}   [x] python3 nao encontrado${F}\n"
  FALTA=1
else
  printf "${V}   [ok]${F} python3\n"
fi

if ! python3 -c "import requests" >/dev/null 2>&1; then
  printf "${A}   [!] biblioteca requests ausente - instalando...${F}\n"
  pip3 install requests --quiet 2>/dev/null || \
    pip3 install requests --quiet --break-system-packages 2>/dev/null
  if python3 -c "import requests" >/dev/null 2>&1; then
    printf "${V}   [ok]${F} requests instalada\n"
  else
    printf "${R}   [x] nao consegui instalar a requests${F}\n"
    FALTA=1
  fi
else
  printf "${V}   [ok]${F} requests\n"
fi

for prog in pdftoppm pdftotext pdfinfo; do
  if ! command -v $prog >/dev/null 2>&1; then
    printf "${A}   [!] %s ausente (vem do poppler)${F}\n" "$prog"
    if command -v brew >/dev/null 2>&1; then
      echo "       instalando poppler, isso pode demorar alguns minutos..."
      brew install poppler
    else
      printf "${R}       Homebrew nao encontrado. Instale em https://brew.sh${F}\n"
      FALTA=1
    fi
    break
  fi
done
command -v pdftoppm >/dev/null 2>&1 && printf "${V}   [ok]${F} poppler\n"

if [ "$FALTA" = "1" ]; then
  echo ""
  printf "${R}   Faltam dependencias. Resolva os itens acima e abra de novo.${F}\n\n"
  read -n 1 -s -r -p "   Pressione qualquer tecla para fechar..."
  exit 1
fi

# ---------------------------------------------------------------------------
# 3. menu
# ---------------------------------------------------------------------------
while true; do
  echo ""
  linha
  printf "${N}   O QUE VOCE QUER FAZER?${F}\n"
  linha
  echo ""
  echo "     1)  Simular          - mostra o que seria feito, NAO envia nada"
  echo "     2)  Testar login     - so confere usuario e senha"
  echo "     3)  Gerar as capas   - extrai a capa de cada PDF, NAO envia nada"
  echo ""
  printf "   ${R}--- via HTTP: NAO USE. Grava sem autor/assunto/lingua ---${F}\n"
  echo ""
  echo "     4)  [nao use] Cadastrar 1 edicao"
  echo "     5)  [nao use] Cadastrar 3 edicoes"
  echo "     6)  [nao use] Cadastrar TODAS"
  echo "     7)  [nao use] Modo vigilancia"
  echo ""
  printf "   ${V}--- via NAVEGADOR: USE ESTAS. Metodo comprovado ---${F}\n"
  echo ""
  echo "     8)  >> Cadastrar 1 edicao"
  echo "     9)  >> Cadastrar 3 edicoes      (lote pequeno)"
  echo "    10)  >> Cadastrar TODAS as que faltam"
  echo "    11)  >> Cadastrar 1, com o navegador VISIVEL"
  echo "    12)  >> TESTE: 1 edicao de 1962 - autor NOVO (entidade FGBMFI)"
  echo ""
  echo "     0)  Sair"
  echo ""
  read -p "   Digite o numero e aperte Enter: " op
  echo ""
  linha
  echo ""

  case "$op" in
    1) python3 cadastrar-voice.py ;;
    2) python3 cadastrar-voice.py --testar-login ;;
    3) python3 cadastrar-voice.py --so-capas ;;
    4) python3 cadastrar-voice.py --executar --limite 1 ;;
    5) python3 cadastrar-voice.py --executar --limite 3 ;;
    6)
       printf "${A}   Isso vai cadastrar todas as edicoes pendentes.${F}\n"
       read -p "   Tem certeza? (digite SIM): " c
       if [ "$c" = "SIM" ]; then
         python3 cadastrar-voice.py --executar
       else
         echo "   Cancelado."
       fi
       ;;
    7) python3 cadastrar-voice.py --executar --vigiar 10 ;;

    8|9|10|11|12)
       if ! python3 -c "import playwright" >/dev/null 2>&1; then
         printf "${A}   Playwright ausente - instalando...${F}\n\n"
         pip3 install playwright --quiet 2>/dev/null || \
           pip3 install playwright --quiet --break-system-packages 2>/dev/null
         python3 -m playwright install chromium
         echo ""
       fi
       case "$op" in
         8)  python3 cadastrar-voice-navegador.py --executar --limite 1 ;;
         9)  python3 cadastrar-voice-navegador.py --executar --limite 3 ;;
         11) python3 cadastrar-voice-navegador.py --executar --limite 1 --visivel ;;
         12) python3 cadastrar-voice-navegador.py --executar --limite 1 --visivel --apenas 1962 ;;
         10)
            printf "${A}   Isso vai cadastrar todas as edicoes pendentes.${F}\n"
            read -p "   Tem certeza? (digite SIM): " c
            [ "$c" = "SIM" ] && python3 cadastrar-voice-navegador.py --executar \
                             || echo "   Cancelado."
            ;;
       esac
       ;;

    0) echo "   Ate logo."; echo ""; exit 0 ;;
    *) printf "${A}   Opcao invalida.${F}\n" ;;
  esac

  echo ""
  linha
  read -n 1 -s -r -p "   Pressione qualquer tecla para voltar ao menu..."
  clear
done
