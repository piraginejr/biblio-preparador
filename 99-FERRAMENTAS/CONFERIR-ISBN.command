#!/bin/bash
# =============================================================================
#  CONFERIR-ISBN - descobre qual e o ISBN correto de um livro
# =============================================================================
#  Abra com DOIS CLIQUES.
#
#  Quando o ISBN impresso nao fecha o digito verificador, o erro pode estar
#  em QUALQUER um dos treze digitos. Este utilitario gera todas as correcoes
#  de um digito que produzem um ISBN valido e pergunta a base da CBL qual
#  delas existe de verdade - e se corresponde a este livro.
#
#  Nao altera nada. So consulta e mostra.
#
#  O resultado fica em _resultado-isbn.txt.
# =============================================================================

cd "$(dirname "$0")" || exit 1
V=$'\033[0;32m'; A=$'\033[0;33m'; R=$'\033[0;31m'; N=$'\033[1m'; F=$'\033[0m'
LOG="$(pwd)/_resultado-isbn.txt"

VENV="$HOME/.biblio-venv"
if [ -x "$VENV/bin/python" ]; then PY="$VENV/bin/python"; else PY="$(command -v python3)"; fi
[ -x "$PY" ] || { printf "${R}   python3 nao encontrado${F}\n\n"; read -n1 -s; exit 1; }

clear
printf "${N}   CONFERIR ISBN${F}\n\n"
echo "   Digite o ISBN como esta impresso no livro (com ou sem tracos)."
echo "   Enter em branco usa o do livro 'Eu, um Discipulador'."
echo ""
read -p "   ISBN: " ENTRADA
ENTRADA="${ENTRADA:-978-65-07-24846-2}"
echo ""

"$PY" - "$ENTRADA" 2>&1 <<'PY' | tee "$LOG"
import importlib.util, pathlib, re, sys

base = pathlib.Path.cwd()
spec = importlib.util.spec_from_file_location("prep", base / "preparar-livros.py")
prep = importlib.util.module_from_spec(spec)
sys.modules["prep"] = prep
spec.loader.exec_module(prep)

try:
    import consultar_cbl as cbl
except Exception as erro:                       # pragma: no cover
    cbl = None
    print(f"  (consultar_cbl indisponivel: {erro})")

lido = re.sub(r"[^0-9Xx]", "", sys.argv[1])
print(f"  ISBN impresso: {lido}")

if prep.isbn_valido(lido):
    print("  O digito verificador FECHA - o numero impresso e valido.")
    candidatos = [lido]
else:
    print("  O digito verificador NAO fecha. Gerando correcoes de um digito:\n")
    candidatos = []
    for i in range(len(lido)):
        for d in "0123456789":
            if d == lido[i]:
                continue
            c = lido[:i] + d + lido[i + 1:]
            if prep.isbn_valido(c) and c.startswith(("978", "979")):
                candidatos.append(c)
                print(f"    pos {i+1:2}: {lido[i]} -> {d}   {c}")
    print(f"\n  {len(candidatos)} candidatos validos.")

if not cbl:
    raise SystemExit

cache = base.parent / "livros" / "_controle" / "cache-cbl"
cache.mkdir(parents=True, exist_ok=True)

print("\n  Consultando a Agencia Brasileira do ISBN (CBL)...\n")
achados = []
for c in candidatos:
    try:
        r = cbl.consultar(c, cache) or {}
    except Exception as erro:
        print(f"    {c}  erro: {str(erro)[:52]}")
        continue
    if not r:
        print(f"    {c}  -")
        continue
    achados.append((c, r))
    titulo = (r.get("titulo") or r.get("Title") or "")[:46]
    autor = (r.get("autores") or r.get("autor") or r.get("Author") or "")[:30]
    editora = (r.get("editora") or r.get("Publisher") or "")[:30]
    ano = r.get("ano") or r.get("Year") or ""
    print(f"    {c}  ENCONTRADO")
    print(f"       titulo : {titulo}")
    print(f"       autor  : {autor}")
    print(f"       editora: {editora}   ano: {ano}")

print()
if len(achados) == 1:
    print(f"  Um unico candidato existe na base: {achados[0][0]}")
    print("  Confira acima se o titulo e o autor sao os do seu livro.")
elif len(achados) > 1:
    print(f"  {len(achados)} candidatos existem na base - NAO da para decidir")
    print("  automaticamente. Compare titulo e autor e escolha.")
else:
    print("  Nenhum candidato foi encontrado na CBL.")
    print("  Isso e comum em obra de igreja com tiragem propria: o ISBN pode")
    print("  ter sido impresso com erro e nunca registrado, ou o registro")
    print("  ainda nao estar publico. Nesse caso o livro entra SEM ISBN, o")
    print("  que e legitimo - o numero e dado da edicao, nao requisito.")
PY

echo ""
printf "${V}   Resultado gravado em:${F} %s\n\n" "$LOG"
read -n 1 -s -r -p "   Tecla para fechar..."
