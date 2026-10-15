import sys
from pathlib import Path


project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "backend" / "vendor"))
sys.path.insert(0, str(project_root))

import uvicorn


if __name__ == "__main__":
    # Use the project interpreter/module path explicitly so an older global
    # backend process cannot silently serve a different application version.
    uvicorn.run("backend.main:app", host="127.0.0.1", port=8000, reload=False, log_level="info")
