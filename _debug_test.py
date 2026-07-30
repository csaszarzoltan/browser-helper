"""Debug test to verify the module being loaded."""
import sys, os, inspect

# Locate profile_manager
from profile_manager import ProfileManager
print(f"ProfileManager loaded from: {inspect.getfile(ProfileManager)}")
