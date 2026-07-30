"""Check syntax of profile_manager.py."""
import py_compile
try:
    py_compile.compile("src/profile_manager.py", doraise=True)
    print("OK - no syntax errors")
except py_compile.PyCompileError as e:
    print(f"SYNTAX ERROR: {e}")
