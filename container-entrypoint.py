import os
from pathlib import Path

# Existing bot modules use paths relative to their working directory.
for name, target in {
    "discord.png": "/app/discord.png",
    "lively-folder-427321-q7-eecd6c0329ea.json": "/run/secrets/google-service-account.json",
}.items():
    path = Path("/data") / name
    if not path.is_symlink():
        if path.exists():
            raise RuntimeError(f"Move {path} out of the data folder before starting")
        path.symlink_to(target)

os.execvp("python", ["python", "/app/main.py"])
