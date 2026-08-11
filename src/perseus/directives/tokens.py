import subprocess


def resolve_tokens(context: str) -> str:
    """Embed a token budget for the rendered context.

    Reports ONLY the measured token count of what Perseus actually renders.

    It deliberately does not emit any savings/multiplier figure: such a number
    cannot be measured from a single rendered block — Perseus does not know the
    counterfactual discovery cost at render time, so any such ratio is invented,
    not measured. A hard-coded multiplier sitting next to
    our verified, ledger-backed savings numbers is a direct credibility risk
    (see #756). Measured savings live in the cost-savings certification
    (``benchmark/cost_savings/results/``), read from the meter — never from a
    multiplier baked into product output.
    """
    try:
        # Prefer the ledger CLI's exact tokenizer when available (the
        # pre-2026-08-09 `plutus tokens` binary was renamed with the product;
        # the ledger CLI currently exposes no `tokens` subcommand, so this
        # path is dormant and the word-count fallback below is the effective
        # one until it does).
        process = subprocess.run(
            ["ledger", "tokens"],
            input=context.encode("utf-8"),
            capture_output=True,
            check=True,
        )
        token_count = int(process.stdout.strip())
        return f"## Context Budget\n{token_count} tokens rendered"
    except (subprocess.CalledProcessError, FileNotFoundError, ValueError):
        # Fallback: rough word-count estimate when the ledger tokenizer is absent.
        words = context.split()
        token_count = int(len(words) * 1.3)
        return (
            "## Context Budget\n"
            f"~{token_count} tokens rendered "
            "(word-count estimate; install perseus-ledger for an exact count)"
        )
