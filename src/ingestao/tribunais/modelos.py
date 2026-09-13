"""
Modelos de dados para o módulo de Tribunais de Justiça.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ParteProcessual:
    """Representa uma parte envolvida em um processo judicial."""
    nome: str
    papel: str  # recuperanda, falido, autor, reu, credor, administrador_judicial, perito, outros
    advogados: list[str] = field(default_factory=list)
    documento: str = ""  # CNPJ ou CPF se disponível


@dataclass
class MovimentacaoProcessual:
    """Representa um andamento processual."""
    data_hora: str
    nome: str
    codigo_cnj: int | None = None
    complemento: str = ""
    orgao_julgador: str = ""


@dataclass
class ProcessoTribunalInfo:
    """Consolidação estruturada de um processo originário de Tribunal."""
    numero_cnj: str
    numero_limpo: str
    tribunal: str  # ex: TJSP, TJMT
    grau: str = "G1"
    sistema: str = ""  # esaj, pje, eproc, projudi
    classe_codigo: int | None = None
    classe_nome: str = ""
    assuntos: list[str] = field(default_factory=list)
    orgao_julgador: str = ""
    comarca: str = ""
    vara: str = ""
    juiz: str = ""
    valor_causa: float | None = None
    moeda: str = "BRL"
    data_distribuicao: str = ""
    data_atualizacao: str = ""
    partes: list[ParteProcessual] = field(default_factory=list)
    devedores: list[str] = field(default_factory=list)
    credores: list[str] = field(default_factory=list)
    administrador_judicial: str = ""
    movimentacoes: list[MovimentacaoProcessual] = field(default_factory=list)
    url_consulta: str = ""
    metadados_extra: dict[str, Any] = field(default_factory=dict)
