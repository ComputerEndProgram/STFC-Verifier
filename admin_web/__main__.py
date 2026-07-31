from __future__ import annotations

import uvicorn

from admin_web.config import AdminWebConfig


def main() -> None:
    cfg = AdminWebConfig.from_env()
    uvicorn.run("admin_web.app:app", host=cfg.host, port=cfg.port)


if __name__ == "__main__":
    main()
