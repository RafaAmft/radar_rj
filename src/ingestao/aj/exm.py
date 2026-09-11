"""
Scraper do Administrador Judicial EXM Partners.

Coleta processos de Recuperação Judicial e Falência e baixa peças chave
(Planos de Recuperação Judicial, Quadros de Credores, Atas de AGC e RMAs).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from src.ingestao.aj.base import DocumentoInfo, ProcessoInfo, ScraperAJBase
from src.ingestao.download import HEADERS_PADRAO, carregar_config_fonte

logger = logging.getLogger(__name__)


class ScraperEXM(ScraperAJBase):
    """Scraper para o portal de Administração Judicial da EXM Partners."""

    def __init__(self, config: dict[str, Any] | None = None):
        if config is None:
            config = carregar_config_fonte("aj_exm")
        super().__init__(config)
        self.url_base = self.config["urls"]["base"]
        self.url_lista = self.config["urls"]["lista_processos"]

    def listar_processos(self) -> list[ProcessoInfo]:
        """
        Descobre todos os processos de RJ e Falência listados na EXM Partners.

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
        links_processos = soup.find_all(
            "a", href=lambda h: h and "processos-em-andamento/" in h
        )

        # Na EXM, cada processo gera múltiplos <a> com o mesmo href:
        # [0] Nome da Empresa, [1] Vara/Comarca, [2] Número CNJ
        grupos_href: dict[str, list[str]] = {}
        for a in links_processos:
            href = a["href"].strip()
            texto = a.get_text(strip=True)
            if texto and href not in grupos_href:
                grupos_href[href] = []
            if texto and texto not in grupos_href[href]:
                grupos_href[href].append(texto)

        processos: list[ProcessoInfo] = []
        for href, textos in grupos_href.items():
            slug = href.split("processos-em-andamento/")[-1].strip("/")
            if not slug:
                continue

            nome_empresa = textos[0] if len(textos) > 0 else slug
            vara = textos[1] if len(textos) > 1 else ""
            numero_cnj = textos[2] if len(textos) > 2 else ""

            # Normalização de URL absoluta
            url_detalhe = urljoin(self.url_base, href)

            processos.append(
                ProcessoInfo(
                    slug=slug,
                    nome_empresa=nome_empresa,
                    vara=vara,
                    numero_cnj=numero_cnj,
                    url_detalhe=url_detalhe,
                )
            )

        logger.info(
            "[%s] %d processos de recuperação/falência identificados.",
            self.nome_aj,
            len(processos),
        )
        return processos

    def obter_documentos_processo(self, processo: ProcessoInfo) -> list[DocumentoInfo]:
        """
        Raspa todos os documentos PDF das seções de um caso na EXM.
        """
        logger.info("[%s] Acessando página do processo: %s", self.nome_aj, processo.url_detalhe)
        resp = requests.get(
            processo.url_detalhe,
            headers=HEADERS_PADRAO,
            timeout=20,
        )
        resp.raise_for_status()

        # Extrair chamadas carregar('processos-mostra-iframe.php?id=...')
        endpoints = re.findall(r"carregar\('([^']+)'\)", resp.text)
        documentos: list[DocumentoInfo] = []
        urls_vistas: set[str] = set()

        # Checar se há links diretos de PDF na página principal
        soup_main = BeautifulSoup(resp.text, "html.parser")
        for a in soup_main.find_all("a", href=True):
            href = a["href"].strip()
            if not href.lower().endswith(".pdf"):
                continue
            url_download = urljoin(self.url_base, href)
            if url_download in urls_vistas:
                continue
            urls_vistas.add(url_download)
            titulo_doc = a.get_text(strip=True) or Path(href).stem
            nome_limpo = re.sub(r'[<>:"/\\|?*]', "_", Path(href).name)
            texto_classificacao = f"{titulo_doc} - {Path(href).stem}"
            categoria = self.classificar_documento(texto_classificacao)
            documentos.append(
                DocumentoInfo(
                    titulo=titulo_doc,
                    url_download=url_download,
                    categoria=categoria,
                    nome_arquivo=nome_limpo,
                )
            )

        for ep in endpoints:
            if not ep.startswith("processos-mostra-iframe.php"):
                continue

            ep_url = urljoin(self.url_base, ep)
            try:
                r_ep = requests.get(
                    ep_url,
                    headers=HEADERS_PADRAO,
                    timeout=15,
                )
                if r_ep.status_code != 200:
                    continue

                soup_ep = BeautifulSoup(r_ep.text, "html.parser")
                h2 = soup_ep.find(["h2", "h3"])
                secao = h2.get_text(strip=True) if h2 else ""

                for a in soup_ep.find_all("a", href=True):
                    href = a["href"].strip()
                    if not href.lower().endswith(".pdf"):
                        continue

                    url_download = urljoin(self.url_base, href)
                    if url_download in urls_vistas:
                        continue
                    urls_vistas.add(url_download)

                    titulo_doc = a.get_text(strip=True) or Path(href).stem
                    nome_arquivo = Path(href).name
                    nome_limpo = re.sub(r'[<>:"/\\|?*]', "_", nome_arquivo)
                    texto_classificacao = f"{secao} - {titulo_doc} - {Path(href).stem}"
                    categoria = self.classificar_documento(texto_classificacao)

                    documentos.append(
                        DocumentoInfo(
                            titulo=titulo_doc,
                            url_download=url_download,
                            categoria=categoria,
                            nome_arquivo=nome_limpo,
                        )
                    )

            except requests.RequestException as e:
                logger.debug("[%s] Falha ao consultar endpoint %s: %s", self.nome_aj, ep, e)

        return documentos


def executar(
    slugs_empresa: list[str] | None = None,
    categorias: list[str] | None = None,
    limite: int | None = None,
    limite_docs: int | None = None,
    dry_run: bool = False,
) -> dict[str, int]:
    """
    Função pública orquestradora do extrator da EXM Partners para a CLI.

    Args:
        slugs_empresa: Filtro de slugs de processos (ex: ['tg-agro', 'san-rafael']).
        categorias: Filtro de categorias de documentos (ex: ['PRJ', 'QGC']).
        limite: Máximo de processos a processar.
        limite_docs: Máximo de documentos por processo a baixar.
        dry_run: Se True, apenas simula sem baixar.

    Returns:
        Dicionário com contagem de documentos baixados por empresa.
    """
    scraper = ScraperEXM()
    processos = scraper.listar_processos()

    if slugs_empresa:
        # Filtrar por substring no slug ou no nome da empresa
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
        "[EXM Partners] Iniciando extração para %d processos selecionados.",
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
