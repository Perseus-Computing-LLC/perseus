import subprocess
import os

def resolve_tokens(context: str) -> str:
    try:
        # Pipe the context to plutus tokens
        process = subprocess.run(
            ['plutus', 'tokens'],
            input=context.encode('utf-8'),
            capture_output=True,
            check=True
        )
        token_count = int(process.stdout.strip())
        # Estimate saved tokens (example ratios)
        saved_tokens = token_count * 3  # For simple facts, 3x
        ratio = 3.0
    except (subprocess.CalledProcessError, FileNotFoundError):
        # Fallback to word count estimate
        words = context.split()
        token_count = int(len(words) * 1.3)
        saved_tokens = token_count * 10 # For complex queries, 10x
        ratio = 10.0

    return f"## Context Budget\n{token_count} tokens rendered | ~{saved_tokens} saved vs runtime discovery ({ratio:.1f}x)"
