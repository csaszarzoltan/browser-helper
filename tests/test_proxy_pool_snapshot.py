"""The pool must not iterate its dict while another thread can change it.

The concurrent test in test_proxy_edge_cases.py failed on one full-suite run with
"dictionary changed size during iteration": _save_atomically walks the dict and calls
Python code for each entry, so an add on another thread lands in the middle of the walk.
This test makes that interleaving happen on purpose.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def test_saving_while_an_entry_is_being_serialised_does_not_break_the_walk(tmp_path):
    from proxy_manager import ProxyPool

    pool = ProxyPool(storage_path=str(tmp_path / "pool.json"))
    pool.add_proxy("socks5://first.test:1080")
    pool.add_proxy("socks5://second.test:1080")
    real_entry_to_dict = pool._entry_to_dict
    injected = []

    def add_during_the_walk(entry):
        # Another thread adding a proxy while the save loop is between two entries.
        if not injected:
            injected.append(True)
            pool.add_proxy("socks5://third.test:1080")
        return real_entry_to_dict(entry)

    pool._entry_to_dict = add_during_the_walk
    pool._save_atomically()
    assert injected
    assert len(pool.get_pool()) == 3
