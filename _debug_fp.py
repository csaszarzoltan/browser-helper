"""Debug script to test generate_fingerprint validation."""
import sys
import tempfile
sys.path.insert(0, '/home/zoltan/browser-helper/src')
import profile_manager

d = tempfile.mkdtemp()
pm = profile_manager.ProfileManager(storage_dir=d)
pm.create_profile('t')
try:
    pm.generate_fingerprint('t', overrides={'screen_width': -100})
    print('NO EXCEPTION - BUG')
except (ValueError, TypeError) as e:
    print(f'OK - Raised {type(e).__name__}: {e}')
except Exception as e:
    print(f'OTHER ERROR: {type(e).__name__}: {e}')
