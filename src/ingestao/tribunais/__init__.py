"""
Pacote de Ingestão e Monitoramento de Tribunais de Justiça.
"""

from src.ingestao.tribunais.base import (
    ConsultorTribunalBase,
    formatar_numero_cnj,
    identificar_tribunal_por_cnj,
    limpar_numero_cnj,
)
from src.ingestao.tribunais.datajud import ClienteDataJud
from src.ingestao.tribunais.esaj import ConsultorEsaj
from src.ingestao.tribunais.modelos import (
    MovimentacaoProcessual,
    ParteProcessual,
    ProcessoTribunalInfo,
)
from src.ingestao.tribunais.pipeline import PipelineTribunais

__all__ = [
    "ConsultorTribunalBase",
    "ClienteDataJud",
    "ConsultorEsaj",
    "PipelineTribunais",
    "ProcessoTribunalInfo",
    "ParteProcessual",
    "MovimentacaoProcessual",
    "formatar_numero_cnj",
    "limpar_numero_cnj",
    "identificar_tribunal_por_cnj",
]
