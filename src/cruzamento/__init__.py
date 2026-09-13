"""
Pacote de Cruzamento e Reconciliação Inteligente de Fontes.
Liga processos judiciais a Administradores Judiciais, CVM e Quadros de Credores.
"""

from src.cruzamento.reconciliador import (
    ReconciliadorFontes,
    ResultadoMatch,
    ResultadoReconciliacao,
    calcular_similaridade,
    normalizar_nome_empresa,
)

__all__ = [
    "ReconciliadorFontes",
    "ResultadoMatch",
    "ResultadoReconciliacao",
    "calcular_similaridade",
    "normalizar_nome_empresa",
]
