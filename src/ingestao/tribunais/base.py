"""
Base e utilitários para consultores de Tribunais de Justiça.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Any

from src.ingestao.tribunais.modelos import ProcessoTribunalInfo

# Tabela oficial de mapeamento do código de tribunal (TR) na Justiça Estadual (J=8)
MAPA_CNJ_TRIBUNAIS: dict[str, dict[str, str]] = {
    "01": {"sigla": "tjac", "uf": "AC", "sistema": "esaj"},
    "02": {"sigla": "tjal", "uf": "AL", "sistema": "esaj"},
    "03": {"sigla": "tjap", "uf": "AP", "sistema": "pje"},
    "04": {"sigla": "tjam", "uf": "AM", "sistema": "esaj"},
    "05": {"sigla": "tjba", "uf": "BA", "sistema": "pje"},
    "06": {"sigla": "tjce", "uf": "CE", "sistema": "pje"},
    "07": {"sigla": "tjdf", "uf": "DF", "sistema": "pje"},
    "08": {"sigla": "tjes", "uf": "ES", "sistema": "pje"},
    "09": {"sigla": "tjgo", "uf": "GO", "sistema": "projudi"},
    "10": {"sigla": "tjma", "uf": "MA", "sistema": "pje"},
    "11": {"sigla": "tjmt", "uf": "MT", "sistema": "pje"},
    "12": {"sigla": "tjms", "uf": "MS", "sistema": "esaj"},
    "13": {"sigla": "tjmg", "uf": "MG", "sistema": "pje"},
    "14": {"sigla": "tjpa", "uf": "PA", "sistema": "pje"},
    "15": {"sigla": "tjpb", "uf": "PB", "sistema": "pje"},
    "16": {"sigla": "tjpr", "uf": "PR", "sistema": "projudi"},
    "17": {"sigla": "tjpe", "uf": "PE", "sistema": "pje"},
    "18": {"sigla": "tjpi", "uf": "PI", "sistema": "pje"},
    "19": {"sigla": "tjrj", "uf": "RJ", "sistema": "pje"},
    "20": {"sigla": "tjrn", "uf": "RN", "sistema": "pje"},
    "21": {"sigla": "tjrs", "uf": "RS", "sistema": "eproc"},
    "22": {"sigla": "tjro", "uf": "RO", "sistema": "pje"},
    "23": {"sigla": "tjrr", "uf": "RR", "sistema": "projudi"},
    "24": {"sigla": "tjsc", "uf": "SC", "sistema": "esaj"},
    "25": {"sigla": "tjse", "uf": "SE", "sistema": "projudi"},
    "26": {"sigla": "tjsp", "uf": "SP", "sistema": "esaj"},
    "27": {"sigla": "tjto", "uf": "TO", "sistema": "eproc"},
}

PADRAO_CNJ_FORMATADO = re.compile(r"^(\d{7})-(\d{2})\.(\d{4})\.(\d)\.(\d{2})\.(\d{4})$")
PADRAO_CNJ_NUMEROS = re.compile(r"^(\d{7})(\d{2})(\d{4})(\d)(\d{2})(\d{4})$")


def formatar_numero_cnj(numero: str) -> str:
    """Garante que o número CNJ esteja no formato NNNNNNN-DD.AAAA.J.TR.OOOO."""
    limpo = re.sub(r"\D", "", str(numero))
    if len(limpo) == 20:
        return f"{limpo[:7]}-{limpo[7:9]}.{limpo[9:13]}.{limpo[13]}.{limpo[14:16]}.{limpo[16:20]}"
    return numero.strip()


def limpar_numero_cnj(numero: str) -> str:
    """Retorna apenas os 20 dígitos do CNJ."""
    return re.sub(r"\D", "", str(numero))


def identificar_tribunal_por_cnj(numero_cnj: str) -> tuple[str, str, str]:
    """
    Identifica o tribunal de origem e o sistema processual a partir do número CNJ.

    Retorna:
        Tuple (sigla_tribunal, uf, sistema) ex: ('tjsp', 'SP', 'esaj').
        Se desconhecido, retorna ('desconhecido', '', '').
    """
    limpo = limpar_numero_cnj(numero_cnj)
    if len(limpo) != 20:
        return ("desconhecido", "", "")

    ramo = limpo[13]      # J (8 = Estadual)
    codigo_tr = limpo[14:16]  # TR (01 a 27)

    if ramo == "8" and codigo_tr in MAPA_CNJ_TRIBUNAIS:
        info = MAPA_CNJ_TRIBUNAIS[codigo_tr]
        return (info["sigla"], info["uf"], info["sistema"])

    return ("desconhecido", "", "")


class ConsultorTribunalBase(ABC):
    """Classe base abstrata para consultores de tribunais."""

    @abstractmethod
    def consultar_processo(self, numero_cnj: str) -> ProcessoTribunalInfo | None:
        """Consulta um processo pelo número CNJ e retorna os dados enriquecidos."""
        pass

    @abstractmethod
    def suporta_tribunal(self, sigla_tribunal: str) -> bool:
        """Informa se este consultor suporta o tribunal especificado."""
        pass
