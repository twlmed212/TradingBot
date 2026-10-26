import sys
from pathlib import Path

# server code runs with server/ as its root (on the EC2 host it is /opt/deskbot)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
