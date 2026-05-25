
import sys
import os
sys.path.insert(0, os.path.abspath("src"))
try:
    from perseus.renderer import _expand_aliases
    print("Success")
except ImportError as e:
    print(f"Failed: {e}")
    print(f"sys.path: {sys.path}")
    import perseus
    print(f"perseus file: {perseus.__file__}")
