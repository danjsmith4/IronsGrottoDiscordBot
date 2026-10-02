import os
from pathlib import Path

# Existing bot modules use paths relative to their working directory.
for name, target in {
    "discord.png": "/app/discord.png",
}.items():
    path = Path("/data") / name
    if not path.is_symlink():
        if path.exists():
            raise RuntimeError(f"Move {path} out of the data folder before starting")
        path.symlink_to(target)

os.execvp("python", ["python", "/app/main.py"])
