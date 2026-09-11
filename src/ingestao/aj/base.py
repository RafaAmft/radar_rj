"""
Classe base para scrapers de portais de Administradores Judiciais (AJs).
"""

from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from src.ingestao.download import (
    DIR_DATA_RAW,
    calcular_sha256,
    download_com_retry,
)
from src.ingestao.manifesto import ManifestoManager

logger = logging.getLogger(__name__)


@dataclass
class ProcessoInfo:
    """Metadados de um processo judicial publicado pelo Administrador Judicial."""

    slug: str
    nome_empresa: str
    vara: str
    numero_cnj: str
    url_detalhe: str
    tipo_processo: str = "recuperacao_judicial"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DocumentoInfo:
    """Informações de uma peça ou documento para download."""

    titulo: str
    url_download: str
    categoria: str
    nome_arquivo: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ScraperAJBase(ABC):
    """Interface e lógica compartilhada para scrapers de AJs."""

    CATEGORIAS_PADRAO = ["PRJ", "QGC", "AGC", "RMA", "EDITAL", "OUTROS"]

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.nome_aj = config.get("nome", "Administrador Judicial")
        self.delay = config.get("delay_entre_downloads", 1.0)
        self.saida_dir_rel = config.get("saida_dir", "aj/desconhecido")
        self.dir_saida_base = DIR_DATA_RAW / self.saida_dir_rel

    @staticmethod
    def classificar_documento(titulo: str) -> str:
        """
        Classifica um documento com base em seu título e palavras-chave jurídicas.

        Categorias:
        - PRJ: Plano de Recuperação Judicial e Aditivos
        - QGC: Quadro Geral de Credores e Relação de Credores
        - AGC: Assembleia Geral de Credores e Atas
        - RMA: Relatório Mensal de Atividades
        - EDITAL: Editais de Leilão, Convocação e Prazos
        - OUTROS: Petições iniciais, relatórios circunstanciados, etc.
        """
        import unicodedata

        # Normalizar acentuação para busca uniforme sem sensibilidade a diacríticos
        t_norm = unicodedata.normalize("NFKD", titulo.lower())
        t = "".join(c for c in t_norm if not unicodedata.combining(c))

        if any(k in t for k in ["plano de recuperacao", "prj", "aditivo ao plano", "modificativo"]):
            return "PRJ"

        if any(k in t for k in ["relacao de credor", "quadro geral", "qgc", "edital de credor"]):
            return "QGC"

        if any(k in t for k in ["assembleia geral", "agc", "ata de assembleia", "ata da assembleia", "conselho de credor"]):
            return "AGC"

        if any(k in t for k in ["relatorio mensal", "rma", "atividades da recuperanda", "relatorio de atividade"]):
            return "RMA"

        if any(k in t for k in ["edital de leilao", "edital de praca", "alienacao de ativo", "leilao", "segunda praca", "edital de intima"]):
            return "EDITAL"

        return "OUTROS"

    @abstractmethod
    def listar_processos(self) -> list[ProcessoInfo]:
        """Varre o portal do AJ e retorna a lista de processos disponíveis."""
        pass

    @abstractmethod
    def obter_documentos_processo(self, processo: ProcessoInfo) -> list[DocumentoInfo]:
        """Obtém todas as peças disponíveis para download de um caso específico."""
        pass

    def baixar_processo(
        self,
        processo: ProcessoInfo,
        categorias_filtro: list[str] | None = None,
        limite_docs: int | None = None,
        dry_run: bool = False,
    ) -> int:
        """
        Baixa os documentos de um processo e os registra no manifesto de auditoria.

        Args:
            processo: Objeto ProcessoInfo com os dados do caso.
            categorias_filtro: Lista de categorias a baixar (ex: ['PRJ', 'QGC']). Se None, baixa tudo.
            limite_docs: Limite de documentos para este processo.
            dry_run: Se True, apenas simula sem realizar downloads.

        Returns:
            Quantidade de documentos salvos com sucesso.
        """
        dir_processo = self.dir_saida_base / processo.slug
        manifesto = ManifestoManager(dir_processo, empresa=processo.slug)

        logger.info(
            "[%s] Verificando peças para '%s' (%s)...",
            self.nome_aj,
            processo.nome_empresa,
            processo.numero_cnj,
        )

        try:
            documentos = self.obter_documentos_processo(processo)
        except Exception as e:
            logger.error(
                "[%s] Falha ao listar peças de '%s': %s",
                self.nome_aj,
                processo.nome_empresa,
                e,
            )
            return 0

        if categorias_filtro:
            documentos = [
                d for d in documentos if d.categoria in categorias_filtro
            ]

        if limite_docs:
            documentos = documentos[:limite_docs]

        logger.info(
            "[%s] %d documentos elegíveis para download de '%s'",
            self.nome_aj,
            len(documentos),
            processo.nome_empresa,
        )

        salvos = 0
        for doc in documentos:
            caminho_categoria = dir_processo / doc.categoria
            caminho_arquivo = caminho_categoria / doc.nome_arquivo
            arquivo_rel = f"{doc.categoria}/{doc.nome_arquivo}"

            if dry_run:
                logger.info("[DRY-RUN] Baixaria [%s]: %s -> %s", doc.categoria, doc.url_download, caminho_arquivo)
                salvos += 1
                continue

            # Idempotência: verificar manifesto e disco
            if manifesto.ja_ingerido_arquivo(arquivo_rel) and caminho_arquivo.exists():
                logger.debug("Já ingerido e existente em disco: %s", arquivo_rel)
                continue

            caminho_categoria.mkdir(parents=True, exist_ok=True)
            try:
                download_com_retry(
                    doc.url_download,
                    destino=caminho_arquivo,
                    desc=doc.nome_arquivo,
                    delay_rate_limit=self.delay,
                )
                hash_arq = calcular_sha256(caminho_arquivo)
                manifesto.registrar(
                    url_origem=doc.url_download,
                    arquivo_local=arquivo_rel,
                    hash_sha256=hash_arq,
                    tipo_fonte=f"aj_{self.config.get('saida_dir', 'aj').split('/')[-1]}",
                    metadados_extra={
                        "categoria": doc.categoria,
                        "titulo": doc.titulo,
                        "processo_cnj": processo.numero_cnj,
                        "empresa": processo.nome_empresa,
                        "vara": processo.vara,
                    },
                )
                salvos += 1
            except Exception as e:
                logger.warning(
                    "[%s] Falha ao baixar %s: %s", self.nome_aj, doc.url_download, e
                )

        return salvos
