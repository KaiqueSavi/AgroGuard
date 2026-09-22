"""
AgroGuard IA — Logging estruturado da API (Sprint 3/4)
=======================================================

Logger 'agroguard' em JSON lines (uma linha por evento) para stdout e para
`logs/agroguard.log`. Nunca loga segredos — apenas o `kid` da chave usada,
nunca o segredo em si.
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "logs"
LOG_FILE = LOG_DIR / "agroguard.log"


class _FormatadorJSON(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "nivel": record.levelname,
            "evento": record.getMessage(),
        }
        campos = getattr(record, "campos", None)
        if campos:
            base["campos"] = campos
        return json.dumps(base, ensure_ascii=False, default=str)


def _montar_logger() -> logging.Logger:
    logger = logging.getLogger("agroguard")
    if logger.handlers:
        return logger  # já configurado (evita handlers duplicados em reload)

    logger.setLevel(logging.INFO)
    logger.propagate = False

    formatador = _FormatadorJSON()

    saida = logging.StreamHandler(sys.stdout)
    saida.setFormatter(formatador)
    logger.addHandler(saida)

    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        arquivo = logging.FileHandler(LOG_FILE, encoding="utf-8")
        arquivo.setFormatter(formatador)
        logger.addHandler(arquivo)
    except OSError:  # pragma: no cover — ambiente sem permissão de escrita
        pass

    return logger


logger = _montar_logger()


def logar(evento: str, request_id: str | None = None, nivel: str = "info", **campos: Any) -> None:
    """Loga um evento estruturado. `request_id` entra em `campos` quando informado."""
    if request_id is not None:
        campos = {"request_id": request_id, **campos}
    registro = getattr(logger, nivel.lower(), logger.info)
    registro(evento, extra={"campos": campos})
