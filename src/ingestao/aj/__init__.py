"""Módulo de coleta de dados de Administradores Judiciais (AJs)."""

from src.ingestao.aj.base import ScraperAJBase
from src.ingestao.aj.exm import ScraperEXM, executar

__all__ = ["ScraperAJBase", "ScraperEXM", "executar"]
