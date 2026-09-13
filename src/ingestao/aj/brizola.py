"""
Scraper do Administrador Judicial Brizola e Japur Administração Judicial.

Coleta processos de Recuperação Judicial e Falência da Região Sul (RS, SC, PR)
através da API REST oficial da Brizola & Japur e baixa peças-chave (PRJs, QGCs, Atas).
"""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import Any

import requests

from src.ingestao.aj.base import DocumentoInfo, ProcessoInfo, ScraperAJBase
from src.ingestao.download import HEADERS_PADRAO, carregar_config_fonte


logger = logging.getLogger(__name__)


def _gerar_slug(texto: str) -> str:
    """Gera um slug URL-safe a partir de um nome ou título."""
    t_norm = unicodedata.normalize("NFKD", texto.lower())
    sem_acento = "".join(c for c in t_norm if not unicodedata.combining(c))
    slug = re.sub(r"[^a-z0-9]+", "-", sem_acento).strip("-")
    return slug or "processo"


class ScraperBrizola(ScraperAJBase):
    """Scraper para o portal de Administração Judicial da Brizola e Japur."""

    def __init__(self, config: dict[str, Any] | None = None):
        if config is None:
            config = carregar_config_fonte("aj_brizola")
        super().__init__(config)
        self.url_base = self.config["urls"]["base"]
        self.url_api_clients = self.config["urls"]["api_clients"]
        self.url_api_detail = self.config["urls"]["api_client_detail"]

    def listar_processos(self, max_paginas: int = 10) -> list[ProcessoInfo]:
        """
        Descobre os processos de RJ e Falência ativos na API da Brizola & Japur.

        Args:
            max_paginas: Limite máximo de páginas da API para consultar.

        Returns:
            Lista de objetos ProcessoInfo com os metadados de cada caso.
        """
        logger.info("[%s] Obtendo catálogo de processos via API: %s...", self.nome_aj, self.url_api_clients)
        processos: list[ProcessoInfo] = []
        pagina_atual = 1
        last_page = 1

        while pagina_atual <= last_page and pagina_atual <= max_paginas:
            params = {"per_page": 50, "page": pagina_atual}
            try:
                resp = requests.get(
                    self.url_api_clients,
                    params=params,
                    headers=HEADERS_PADRAO,
                    timeout=20,
                )
                resp.raise_for_status()
                dados = resp.json()
            except Exception as e:
                logger.error("[%s] Falha ao consultar página %d da API: %s", self.nome_aj, pagina_atual, e)
                break

            content = dados.get("content", {})
            paging = content.get("paging", {})
            last_page = paging.get("lastPage", 1)
            itens = content.get("data", [])

            for item in itens:
                client_id = item.get("id")
                nome = str(item.get("name", "")).strip()
                if not nome or not client_id:
                    continue

                cnj = str(item.get("process_number", "")).strip()
                district = item.get("district") or {}
                vara = str(district.get("name", "")).strip()

                tipo_num = item.get("type", 1)
                tipo_proc = "recuperacao_judicial" if tipo_num == 1 else "falencia"

                slug = _gerar_slug(f"{nome}-{client_id}")
                url_detalhe = self.url_api_detail.format(id=client_id)

                processos.append(
                    ProcessoInfo(
                        slug=slug,
                        nome_empresa=nome,
                        vara=vara,
                        numero_cnj=cnj,
                        url_detalhe=url_detalhe,
                        tipo_processo=tipo_proc,
                    )
                )

            logger.info(
                "[%s] Página %d/%d processada (%d processos acumulados)...",
                self.nome_aj,
                pagina_atual,
                last_page,
                len(processos),
            )
            pagina_atual += 1

        logger.info("[%s] Catálogo concluído: %d processos encontrados.", self.nome_aj, len(processos))
        return processos

    def obter_documentos_processo(self, processo: ProcessoInfo) -> list[DocumentoInfo]:
        """
        Consulta os detalhes e peças processuais disponíveis para um caso na API.

        Args:
            processo: Objeto ProcessoInfo com url_detalhe para a API do caso.

        Returns:
            Lista de DocumentoInfo classificados e prontos para download.
        """
        logger.info("[%s] Obtendo peças de '%s' via API...", self.nome_aj, processo.nome_empresa)
        try:
            resp = requests.get(
                processo.url_detalhe,
                headers=HEADERS_PADRAO,
                timeout=20,
            )
            resp.raise_for_status()
            dados = resp.json()
        except Exception as e:
            logger.error("[%s] Erro ao consultar detalhes de %s: %s", self.nome_aj, processo.slug, e)
            return []

        content = dados.get("content", {})
        docs_raw = content.get("documents", [])
        documentos: list[DocumentoInfo] = []

        for d in docs_raw:
            url_doc = d.get("doc_url") or ""
            titulo = str(d.get("name", "")).strip()
            if not url_doc or not titulo:
                continue

            categoria = self.classificar_documento(titulo)
            nome_arquivo = f"{_gerar_slug(titulo)}.pdf"
            documentos.append(
                DocumentoInfo(
                    titulo=titulo,
                    url_download=url_doc,
                    categoria=categoria,
                    nome_arquivo=nome_arquivo,
                )
            )


        logger.info(
            "[%s] Encontrados %d documentos para '%s'.",
            self.nome_aj,
            len(documentos),
            processo.nome_empresa,
        )
        return documentos
