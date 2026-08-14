# Fix Small Mechanical Ruff Errors

Fix these specific ruff errors in the browser-helper project:

## Errors to fix:

### 1. F841 — unused variable (3 errors)
Find all F841 errors and either remove the unused variable or prefix with `_`.

### 2. RUF059 — unused unpacked variable (4 errors)
Find all RUF059 errors and prefix the unused unpacked variable with `_`.

### 3. F601 — multi-value repeated key literal (2 errors)
Remove duplicate keys from dict literals.

### 4. UP031 — printf-string-formatting (3 errors)
Replace `%s` / `%d` / `%r` printf-style formatting with f-strings.

### 5. F821 — undefined name (1 error)
Find the undefined name and fix it (likely a missing import or typo).

### 6. B039 — mutable-contextvar-default (1 error)
Replace mutable default with `None` and create the mutable value inside the function.

### 7. SIM102 — collapsible-if (1 error)
Collapse nested `if` statements into a single `if` with `and`.

### 8. SIM115 — open-file-with-context-handler (1 error)
Use a context manager (`with open(...)`) for file operations.

### 9. PLW0602 — global-variable-not-assigned (1 error)
Fix the global variable usage (either assign it or remove the global declaration).

### 10. RUF046 — unnecessary-cast-to-int (1 error)
Remove the unnecessary `int()` cast.

## Verification
After all fixes, run:
```bash
PATH="$PWD/.venv/bin:$PATH" python -m ruff check src/ --select F841,RUF059,F601,UP031,F821,B039,SIM102,SIM115,PLW0602,RUF046
```
Should return 0 errors.
