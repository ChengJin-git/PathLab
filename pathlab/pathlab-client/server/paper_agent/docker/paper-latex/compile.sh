#!/usr/bin/env bash
# PathLab paper-generation LaTeX compile entrypoint.
#
# Modes:
#   hello                      — emit a tiny hello-world PDF (smoke test)
#   compile <template_name>    — compile /work/<template_name>/main.tex
#                                Output: /work/<template_name>/main.pdf
#                                Logs:   /work/<template_name>/main.log,
#                                        /work/<template_name>/main.compile_summary.txt
#
# Inputs (mounted at /work):
#   /work/<template_name>/main.tex
#   /work/<template_name>/refs.bib            (optional)
#   /work/<template_name>/figures/...
#   /work/<template_name>/*.cls / *.bst       (template-bundled files)

set -euo pipefail

MODE="${1:-hello}"

emit_summary() {
    local template_dir="$1"
    local exit_code="$2"
    {
        echo "compile_summary"
        echo "  template_dir=${template_dir}"
        echo "  exit_code=${exit_code}"
        echo "  pdf_present=$(test -f "${template_dir}/main.pdf" && echo yes || echo no)"
        echo "  log_tail (last 20 lines):"
        if [[ -f "${template_dir}/main.log" ]]; then
            tail -n 20 "${template_dir}/main.log" || true
        else
            echo "    (no log file produced)"
        fi
    } > "${template_dir}/main.compile_summary.txt"
}

case "${MODE}" in
    hello)
        # Minimal sanity check: write a one-line tex, compile, dump first
        # line of generated pdf metadata so the M1 smoke test can grep it.
        TMPDIR="$(mktemp -d)"
        cat > "${TMPDIR}/main.tex" <<'TEX'
\documentclass{article}
\begin{document}
PathLab paper-latex hello world.
\end{document}
TEX
        ( cd "${TMPDIR}" && latexmk -pdf -interaction=nonstopmode main.tex >/dev/null )
        if [[ -f "${TMPDIR}/main.pdf" ]]; then
            echo "OK: $(qpdf --show-pages "${TMPDIR}/main.pdf" 2>/dev/null | head -1)"
            exit 0
        fi
        echo "FAIL: hello compile produced no main.pdf" >&2
        exit 1
        ;;
    compile)
        TEMPLATE_NAME="${2:?template_name required, e.g. miccai}"
        TEMPLATE_DIR="/work/${TEMPLATE_NAME}"
        if [[ ! -d "${TEMPLATE_DIR}" ]]; then
            echo "FAIL: template directory not found: ${TEMPLATE_DIR}" >&2
            exit 2
        fi
        if [[ ! -f "${TEMPLATE_DIR}/main.tex" ]]; then
            echo "FAIL: ${TEMPLATE_DIR}/main.tex missing" >&2
            exit 3
        fi

        # latexmk handles BibTeX / re-runs automatically. We pin a quiet,
        # non-interactive run so failures don't hang the worker.
        cd "${TEMPLATE_DIR}"
        rc=0
        latexmk -pdf -interaction=nonstopmode -file-line-error main.tex || rc=$?
        emit_summary "${TEMPLATE_DIR}" "${rc}"
        exit "${rc}"
        ;;
    *)
        echo "FAIL: unknown mode '${MODE}' (expected: hello | compile <template>)" >&2
        exit 64
        ;;
esac
