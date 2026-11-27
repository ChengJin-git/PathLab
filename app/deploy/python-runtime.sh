#!/bin/bash
# Shared interpreter selection for deployment entrypoints.
# Call after setting SERVER_DIR and PROJECT_DIR; exports the selected PYTHON variable.

select_pathlab_python() {
    if [ -f "$SERVER_DIR/.venv/pathlab.env" ]; then
        local explicit_python="${PATHLAB_PYTHON:-}"
        source "$SERVER_DIR/.venv/pathlab.env"
        if [ -n "$explicit_python" ]; then export PATHLAB_PYTHON="$explicit_python"; fi
    fi

    local autoresearch_python="$SERVER_DIR/backend/autoresearch/.venv/bin/python"
    local project_python="$PROJECT_DIR/venv/bin/python3"
    if [ -n "${PATHLAB_PYTHON:-}" ]; then
        if [ -x "$PATHLAB_PYTHON" ]; then
            PYTHON="$PATHLAB_PYTHON"
        elif command -v "$PATHLAB_PYTHON" > /dev/null 2>&1; then
            PYTHON="$(command -v "$PATHLAB_PYTHON")"
        else
            echo "Error: PATHLAB_PYTHON is set but not executable/found: $PATHLAB_PYTHON" >&2
            return 1
        fi
    elif [ -x "$autoresearch_python" ]; then
        PYTHON="$autoresearch_python"
    elif [ -x "$project_python" ]; then
        PYTHON="$project_python"
    elif [ -n "${CONDA_PREFIX:-}" ] && [ -x "$CONDA_PREFIX/bin/python3" ]; then
        PYTHON="$CONDA_PREFIX/bin/python3"
    elif command -v python3 > /dev/null 2>&1; then
        PYTHON="$(command -v python3)"
    else
        echo "Error: Python3 not found" >&2
        return 1
    fi
}
