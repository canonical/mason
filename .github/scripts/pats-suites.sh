#!/usr/bin/env bash
# picks the ci suites a pull request needs: pats-suites.sh <pats.yaml> [--all]
# reads the changed files on stdin, one per line, unless --all. prints the
# suites as a json array (`["ci-a","ci-b"]`), for a job matrix: `[]` when no
# suite applies.
#
# a ci suite is a suite named ci-<skill> in <pats.yaml>. a change under
# skills/<skill>/ picks ci-<skill>, a change to the eval or to the pats ci
# picks them all, anything else none. only declared ci-* names are printed,
# since <pats.yaml> and the file names may come from a fork.
set -eu

SUITE_RE='^ci-[a-z0-9][a-z0-9-]*$'

function _fail() {
    printf 'pats-suites: %s\n' "$1" >&2
    exit 2
}

# _ci_suites: the ci-* suites <pats.yaml> declares, one per line, each once.
function _ci_suites() {
    yq -r '.[] | select(.kind == "suite") | .items | keys | .[]' "$1" |
        grep -E "$SUITE_RE" | sort -u || true
}

function main() {
    case "${1:-}" in
        ("" | -h | --help) _fail "usage: pats-suites.sh <pats.yaml> [--all] < changed-files" ;;
    esac
    local config="$1" all=0 wanted=" " file skill suite names=""
    [ -f "$config" ] || _fail "no such file: $config"
    case "${2:-}" in
        ("") ;;
        (--all) all=1 ;;
        (*) _fail "unknown argument: $2" ;;
    esac

    if [ "$all" = 0 ]; then
        while IFS= read -r file; do
            case "$file" in
                (tests/skills/README.md) ;;
                (tests/skills/* | .github/workflows/pats.yml | .github/workflows/pats-forks.yml | .github/scripts/pats-suites.sh)
                    all=1 ;;
                (skills/*/*)
                    skill="${file#skills/}"
                    wanted+="ci-${skill%%/*} " ;;
            esac
        done
    fi

    while IFS= read -r suite; do
        if [ "$all" = 1 ] || [[ "$wanted" == *" $suite "* ]]; then
            names+="${names:+,}\"$suite\""
        fi
    done < <(_ci_suites "$config")
    printf '[%s]\n' "$names"
}

main "$@"
