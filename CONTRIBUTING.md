# Contributing to Perseus

Full contributor guidelines, dev setup, repo layout, and task workflow:
👉 **[docs/CONTRIBUTING.md](docs/CONTRIBUTING.md)**

Quick start:
```bash
git clone https://github.com/tcconnally/perseus.git
cd perseus
pip install -r requirements.txt
python scripts/build.py       # regenerate perseus.py after editing src/
python -m pytest tests/ -q    # 894 tests (<!-- test-count: 894 -->)
```

Edit `src/perseus/`, not `perseus.py` directly — it's a generated artifact.
