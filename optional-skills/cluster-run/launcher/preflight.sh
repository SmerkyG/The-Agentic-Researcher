if [[ "$AR_SANDBOX" != "none" ]]; then
    echo "Error: cluster-run optional skill requires --sandbox none." >&2
    exit 1
fi

if ! command -v cluster-run >/dev/null 2>&1; then
    echo "Error: cluster-run optional skill selected, but 'cluster-run' is not on PATH." >&2
    exit 1
fi

if ! cluster-run --help >/dev/null 2>&1; then
    echo "Error: cluster-run is on PATH but did not run successfully." >&2
    exit 1
fi
