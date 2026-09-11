"""
Scraper do Administrador Judicial AJ Ruiz Consultoria e Administração Judicial.

Coleta processos de Recuperação Judicial e Falência do portal da AJ Ruiz
(https://www.ajruiz.com.br) e baixa peças-chave (PRJs, QGCs, Decisões, Editais).
"""

from __future__ import annotations

import logging
import re
import unicodedata
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urljoin

import requests
from bs4 import BeautifulSoup

from src.ingestao.aj.base import DocumentoInfo, ProcessoInfo, ScraperAJBase
from src.ingestao.download import HEADERS_PADRAO, carregar_config_fonte

logger = logging.getLogger(__name__)


def _gerar_slug(texto: str) -> str:
    """Gera um slug URL-safe a partir de um nome ou título."""
    t_norm = unicodedata.normalize("NFKD", texto.lower())
    sem_acento = "".join(c for c in t_norm if not unicodedata.combining(c))
    slug = re.sub(r"[^a-z0-9]+", "-", sem_acento).strip("-")
    return slug or "processo"


class ScraperRuiz(ScraperAJBase):
    """Scraper para o portal de Administração Judicial da AJ Ruiz."""

    def __init__(self, config: dict[str, Any] | None = None):
        if config is None:
            config = carregar_config_fonte("aj_ruiz")
        super().__init__(config)
        self.url_base = self.config["urls"]["base"]
        self.url_lista = self.config["urls"]["lista_processos"]
        # Cache em memória dos documentos mapeados por slug
        self._documentos_cache: dict[str, list[DocumentoInfo]] = {}

    def listar_processos(self) -> list[ProcessoInfo]:
        """
        Descobre todos os processos listados na página pública da AJ Ruiz.

        Returns:
            Lista de objetos ProcessoInfo com os metadados de cada caso.
        """
        logger.info("[%s] Obtendo catálogo de processos em %s...", self.nome_aj, self.url_lista)
        resp = requests.get(
            self.url_lista,
            headers=HEADERS_PADRAO,
            timeout=20,
        )
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        rows = soup.find_all(class_="views-row")

        logger.info("[%s] %d blocos views-row identificados no portal.", self.nome_aj, len(rows))

        processos_map: dict[str, ProcessoInfo] = {}
        self._documentos_cache.clear()

        padrao_cnj = re.compile(r"\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}")

        for row in rows:
            textos = [t.strip() for t in row.stripped_strings if len(t.strip()) > 1]
            if not textos:
                continue

            # Nome da Empresa geralmente é o primeiro elemento de texto em destaque
            nome_empresa = textos[0]
            if len(nome_empresa) < 3 or nome_empresa.lower().startswith("documento"):
                continue

            # Buscar número CNJ no texto do bloco
            bloco_texto = " ".join(textos)
            match_cnj = padrao_cnj.search(bloco_texto)
            numero_cnj = match_cnj.group(0) if match_cnj else ""

            # Buscar Juízo / Vara
            vara = ""
            for t in textos:
                if t.lower().startswith("juízo:") or t.lower().startswith("vara:"):
                    vara = t.split(":", 1)[-1].strip()
                    break

            slug = _gerar_slug(nome_empresa)

            if slug not in processos_map:
                processos_map[slug] = ProcessoInfo(
                    slug=slug,
                    nome_empresa=nome_empresa,
                    vara=vara,
                    numero_cnj=numero_cnj,
                    url_detalhe=self.url_lista,
                )
                self._documentos_cache[slug] = []

            # Extrair PDFs deste bloco
            for a in row.find_all("a", href=True):
                href = a["href"].strip()
                if not href.lower().endswith(".pdf"):
                    continue

                url_download = urljoin(self.url_base, href)
                nome_arquivo_url = unquote(Path(href).name)
                nome_limpo = re.sub(r'[<>:"/\\|?*]', "_", nome_arquivo_url)

                titulo_doc = a.get_text(strip=True) or Path(nome_arquivo_url).stem
                texto_classificacao = f"{titulo_doc} - {nome_arquivo_url}"
                categoria = self.classificar_documento(texto_classificacao)

                doc_info = DocumentoInfo(
                    titulo=titulo_doc,
                    url_download=url_download,
                    categoria=categoria,
                    nome_arquivo=nome_limpo,
                )

                # Evitar duplicatas de URL para o mesmo processo
                urls_existentes = {d.url_download for d in self._documentos_cache[slug]}
                if url_download not in urls_existentes:
                    self._documentos_cache[slug].append(doc_info)

        lista_final = list(processos_map.values())
        logger.info(
            "[%s] %d processos consolidados com %d documentos mapeados.",
            self.nome_aj,
            len(lista_final),
            sum(len(docs) for docs in self._documentos_cache.values()),
        )
        return lista_final

    def obter_documentos_processo(self, processo: ProcessoInfo) -> list[DocumentoInfo]:
        """
        Retorna todos os documentos PDF catalogados para o processo.
        """
        if processo.slug in self._documentos_cache:
            return self._documentos_cache[processo.slug]

        # Fallback: se o cache não estiver populado, popula via listar_processos
        self.listar_processos()
        return self._documentos_cache.get(processo.slug, [])


def executar(
    slugs_empresa: list[str] | None = None,
    categorias: list[str] | None = None,
    limite: int | None = None,
    limite_docs: int | None = None,
    dry_run: bool = False,
) -> dict[str, int]:
    """
    Função orquestradora do extrator da AJ Ruiz para a CLI.

    Args:
        slugs_empresa: Filtro de slugs ou nomes de empresas (ex: ['atlas', 'flytour']).
        categorias: Filtro de categorias de documentos (ex: ['PRJ', 'QGC']).
        limite: Máximo de processos a processar.
        limite_docs: Máximo de documentos por processo a baixar.
        dry_run: Se True, apenas simula sem baixar.

    Returns:
        Dicionário com contagem de documentos baixados por empresa.
    """
    scraper = ScraperRuiz()
    processos = scraper.listar_processos()

    if slugs_empresa:
        processos_filtrados = []
        for p in processos:
            for s in slugs_empresa:
                s_lower = s.lower()
                if s_lower in p.slug.lower() or s_lower in p.nome_empresa.lower():
                    processos_filtrados.append(p)
                    break
        processos = processos_filtrados

    if limite:
        processos = processos[:limite]

    logger.info(
        "[%s] Iniciando extração para %d processos selecionados.",
        scraper.nome_aj,
        len(processos),
    )

    resultados: dict[str, int] = {}
    for proc in processos:
        total_baixados = scraper.baixar_processo(
            proc,
            categorias_filtro=categorias,
            limite_docs=limite_docs,
            dry_run=dry_run,
        )
        resultados[proc.slug] = total_baixados

    return resultados
