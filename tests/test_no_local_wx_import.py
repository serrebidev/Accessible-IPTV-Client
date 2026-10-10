import ast
import os

MAIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "main.py")


def test_main_never_imports_wx_inside_a_function():
    # A local "import wx" makes wx a local name for the whole function, so any
    # earlier wx use in it raises UnboundLocalError (v1.149.0 startup crash).
    tree = ast.parse(open(MAIN, encoding="utf-8").read())
    bad = []
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for node in ast.walk(fn):
                if isinstance(node, ast.Import) and any(a.name == "wx" and not a.asname for a in node.names):
                    bad.append(node.lineno)
    assert not bad, f"local 'import wx' in main.py at line(s) {bad}"
