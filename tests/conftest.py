# Pytest configuration file for the tests directory
# This can help pytest discover modules correctly.
import sys
import os

# Add the project root directory to the Python path
# This allows absolute imports like 'from core.config import ...' or 'from agent_shell.core...' 
# (assuming agent_shell is the root or src dir)
# Calculate the path to the project root (assuming tests/ is one level down)
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..')) 
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# You can also define shared fixtures here if needed later 