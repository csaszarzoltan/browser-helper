"""Debug matching the test exactly."""
import sys
import os
import tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

# Check where profile_manager is loaded from
import profile_manager as pm_mod
print(f"profile_manager loaded from: {pm_mod.__file__}")

d = tempfile.mkdtemp()
pm = pm_mod.ProfileManager(storage_dir=d)
pm.create_profile('test')
try:
    fp = pm.generate_fingerprint('test', overrides={'screen_width': -100})
    print(f'NO EXCEPTION - result screen_width={fp.get("screen_width")}')
except (ValueError, TypeError) as e:
    print(f'OK - Raised {type(e).__name__}: {e}')
except Exception as e:
    print(f'OTHER: {type(e).__name__}: {e}')

# Clean up
import shutil
shutil.rmtree(d, ignore_errors=True)
