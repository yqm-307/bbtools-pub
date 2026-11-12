"""Git commit-msg entry."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'core'))
from runner import entry, guarded

if __name__ == '__main__':
    sys.exit(guarded(lambda: entry('commit')))
