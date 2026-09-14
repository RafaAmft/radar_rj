"""
Fachada do componente Linha do Tempo Dupla (Processo + CVM) para acesso direto.
"""

from __future__ import annotations

from src.visualizacao.timeline_dupla import (
    CORES_EMISSORES,
    ORDEM_FASES,
    classificar_fase_macro,
    construir_figura_timeline_dupla,
    detectar_correlacoes,
    extrair_fases_processo,
    normalizar_emissor,
    renderizar_timeline_dupla,
)

__all__ = [
    "CORES_EMISSORES",
    "ORDEM_FASES",
    "classificar_fase_macro",
    "construir_figura_timeline_dupla",
    "detectar_correlacoes",
    "extrair_fases_processo",
    "normalizar_emissor",
    "renderizar_timeline_dupla",
]
