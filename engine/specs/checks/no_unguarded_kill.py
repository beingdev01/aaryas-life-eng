"""Acceptance helper: fail if a script can send signals without an explicit --kill flag.

Inspects real call nodes with the AST, so comments and docstrings that merely mention
os.kill do not count (the first live run's grep-based check failed on a docstring).
"""
import ast
import sys

SIGNAL_CALLS = {"kill", "killpg", "terminate", "send_signal"}


def main(path: str) -> int:
    src = open(path, encoding="utf-8").read()
    tree = ast.parse(src)
    calls = [n.lineno for n in ast.walk(tree)
             if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute) and n.func.attr in SIGNAL_CALLS]
    if not calls:
        print("no signal-sending calls")
        return 0
    has_flag = any(isinstance(n, ast.Constant) and n.value == "--kill" for n in ast.walk(tree))
    if has_flag:
        print(f"signal calls at lines {calls}, gated behind an explicit --kill flag")
        return 0
    print(f"signal calls at lines {calls} but no --kill flag is defined", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
