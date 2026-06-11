# Contributing to Perseus

Full contributor guidelines, dev setup, repo layout, and task workflow:
👉 **[docs/CONTRIBUTING.md](docs/CONTRIBUTING.md)**

Quick start:
```bash
git clone https://github.com/tcconnally/perseus.git
cd perseus
git config core.hooksPath .githooks   # auto-rebuild perseus.py on commit
pip install -r requirements.txt
python scripts/build.py               # regenerate perseus.py after editing src/
python -m pytest tests/ -q            # 1,030+ tests
```

Edit `src/perseus/`, not `perseus.py` directly — it's a generated artifact.

**Pre-commit hook:** The `.githooks/pre-commit` hook auto-rebuilds `perseus.py`
when you commit changes to `src/perseus/`. The `.githooks/pre-push` hook catches
remaining edge cases (cherry-pick, rebase, amend). Run `git config core.hooksPath .githooks`
once after cloning to activate both. Without them, CI will still auto-fix your branch —
but running hooks locally keeps your commit history clean.
