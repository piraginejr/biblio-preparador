#!/bin/bash
# =============================================================================
#  BIBLIO VISUAL - interface local do Biblio Preparador
# =============================================================================

cd "$(dirname "$0")" || exit 1

VENV="$HOME/.biblio-venv"
if [ -x "$VENV/bin/python" ]; then
  PY="$VENV/bin/python"
else
  PY="$(command -v python3)"
fi

if [ ! -x "$PY" ]; then
  echo "python3 nao encontrado"
  read -n1 -s -r -p "Tecla para fechar..."
  exit 1
fi

LIVROS="$(cd .. && pwd)/livros"
mkdir -p "$LIVROS"

PYTHONPYCACHEPREFIX=/private/tmp/biblio-pycache \
  "$PY" biblio_app_visual.py --raiz "$LIVROS" --porta 65087 --abrir
