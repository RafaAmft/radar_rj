"""
Consultor para tribunais que utilizam o sistema Eproc.
Suporta TJRS, TJSC, TJTO e TRF4.
Combina parsing de capas públicas do Eproc com fallback estruturado do DataJud (CNJ).
"""

from __future__ import annotations

import logging
import re
from typing import Any

import requests
from bs4 import BeautifulSoup

from src.ingestao.tribunais.base import (
    ConsultorTribunalBase,
    formatar_numero_cnj,
    identificar_tribunal_por_cnj,
    limpar_numero_cnj,
)
from src.ingestao.tribunais.datajud import ClienteDataJud
from src.ingestao.tribunais.modelos import (
    ParteProcessual,
    ProcessoTribunalInfo,
)

logger = logging.getLogger(__name__)

URLS_EPROC: dict[str, str] = {
    "tjrs": "https://eproc1g.tjrs.jus.br/eproc/externo_controlador.php?acao=processo_consulta_publica",
    "tjsc": "https://eproc1g.tjsc.jus.br/eproc/externo_controlador.php?acao=processo_consulta_publica",
    "tjto": "https://eproc1.tjto.jus.br/eprocV2_prod_1grau/externo_controlador.php?acao=processo_consulta_publica",
    "trf4": "https://eproc.trf4.jus.br/eproc2trf4/externo_controlador.php?acao=processo_consulta_publica",
}


class ConsultorEproc(ConsultorTribunalBase):
    """Consultor especializado para Tribunais que utilizam o Eproc."""

    def __init__(
        self,
        cliente_datajud: ClienteDataJud | None = None,
        timeout: int = 15,
        session: requests.Session | None = None,
    ) -> None:
        self.datajud = cliente_datajud or ClienteDataJud()
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "pt-BR,pt;q=0.9",
            }
        )

    def suporta_tribunal(self, sigla_tribunal: str) -> bool:
        """Verifica se o tribunal é suportado pelo consultor Eproc."""
        sigla = sigla_tribunal.lower().strip()
        return sigla in URLS_EPROC

    def consultar_processo(
        self, numero_cnj: str, html_conteudo: str | None = None
    ) -> ProcessoTribunalInfo | None:
        """
        Consulta um processo no Eproc pelo número CNJ.
        Se html_conteudo for fornecido diretamente, parseia o HTML.
        Caso contrário, tenta consulta web direta ou aciona o fallback do DataJud.
        """
        numero_formatado = formatar_numero_cnj(numero_cnj)
        numero_limpo = limpar_numero_cnj(numero_cnj)
        sigla_tribunal, uf, _ = identificar_tribunal_por_cnj(numero_formatado)

        if not self.suporta_tribunal(sigla_tribunal):
            logger.warning("[ConsultorEproc] Tribunal '%s' não suportado.", sigla_tribunal)
            return None

        # 1. Se foi passado HTML diretamente (mock ou teste)
        if html_conteudo:
            return self.parsear_html_processo(
                html=html_conteudo,
                numero_cnj=numero_formatado,
                tribunal=sigla_tribunal,
            )

        # 2. Tentar consulta web direta ao Eproc
        url_base = URLS_EPROC.get(sigla_tribunal)
        if url_base:
            try:
                html = self._requisitar_eproc(url_base, numero_limpo)
                if html and self._html_contem_dados_processo(html):
                    info = self.parsear_html_processo(
                        html=html,
                        numero_cnj=numero_formatado,
                        tribunal=sigla_tribunal,
                    )
                    if info:
                        return info
            except Exception as e:
                logger.debug(
                    "[ConsultorEproc] Falha na consulta web direta Eproc (%s): %s",
                    sigla_tribunal,
                    e,
                )

        # 3. Fallback inteligente: buscar via DataJud e enriquecer com contexto Eproc
        logger.info(
            "[ConsultorEproc] Acionando enriquecimento via DataJud para %s (%s)",
            numero_formatado,
            sigla_tribunal.upper(),
        )
        info_datajud = self.datajud.buscar_por_numero(
            numero_cnj=numero_formatado, tribunal=sigla_tribunal
        )

        if info_datajud:
            info_datajud.url_consulta = url_base or ""
            return info_datajud

        return None

    def _requisitar_eproc(self, url_base: str, numero_limpo: str) -> str | None:
        """Tenta buscar processo na consulta pública do Eproc."""
        params = {
            "acao": "processo_seleciona",
            "num_processo": numero_limpo,
        }
        r = self.session.get(url_base, params=params, timeout=self.timeout)
        if r.status_code == 200:
            return r.text
        return None

    def _html_contem_dados_processo(self, html: str) -> bool:
        """Verifica se o HTML possui elementos típicos da capa do Eproc."""
        return (
            "infraTable" in html
            or "tbPartes" in html
            or "lblClasseProcessual" in html
            or "autor" in html.lower()
        )

    def parsear_html_processo(
        self, html: str, numero_cnj: str, tribunal: str
    ) -> ProcessoTribunalInfo:
        """Realiza o parsing da capa pública do Eproc."""
        soup = BeautifulSoup(html, "html.parser")
        numero_formatado = formatar_numero_cnj(numero_cnj)
        numero_limpo = limpar_numero_cnj(numero_cnj)

        classe = "Recuperação Judicial"
        classe_elem = (
            soup.find(id="lblClasseProcessual")
            or soup.find(id="lblClasse")
            or soup.find(string=re.compile(r"Classe:", re.I))
        )
        if classe_elem:
            texto = classe_elem.get_text().strip()
            classe = re.sub(r"^Classe:\s*", "", texto, flags=re.I).strip()

        vara = ""
        vara_elem = (
            soup.find(id="lblOrgaoJulgador")
            or soup.find(id="lblVara")
            or soup.find(string=re.compile(r"Órgão Julgador|Vara:", re.I))
        )
        if vara_elem:
            texto = vara_elem.get_text().strip()
            vara = re.sub(r"^(?:Órgão Julgador|Vara):\s*", "", texto, flags=re.I).strip()

        valor_causa = 0.0
        valor_elem = (
            soup.find(id="lblValorCausa")
            or soup.find(string=re.compile(r"Valor da Causa:", re.I))
        )
        if valor_elem:
            texto = valor_elem.get_text().strip()
            m = re.search(r"R?\$?\s*([\d\.,]+)", texto)
            if m:
                num_str = m.group(1).replace(".", "").replace(",", ".")
                try:
                    valor_causa = float(num_str)
                except ValueError:
                    pass

        partes: list[ParteProcessual] = []
        devedores: list[str] = []
        credores: list[str] = []

        # Tabela de partes no Eproc (id="tbPartes" ou tabelas com class "infraTable")
        tabelas = soup.find_all("table", class_=re.compile(r"infraTable|tabelaPartes", re.I))
        if not tabelas:
            tabelas = soup.find_all("table")

        for tabela in tabelas:
            linhas = tabela.find_all("tr")
            for linha in linhas:
                colunas = linha.find_all(["td", "th"])
                if len(colunas) >= 2:
                    papel_raw = colunas[0].get_text().strip().lower()
                    nome_raw = colunas[1].get_text().strip()
                    if not nome_raw or "polo" in nome_raw.lower():
                        continue

                    # Identificar papel
                    if any(t in papel_raw for t in ["autor", "recuperand", "requerente", "ativo"]):
                        papel = "recuperanda"
                        devedores.append(nome_raw)
                    elif any(t in papel_raw for t in ["réu", "requerido", "credor", "passivo", "interessado"]):
                        papel = "credor"
                        credores.append(nome_raw)
                    elif "administrador" in papel_raw or "perito" in papel_raw:
                        papel = "administrador_judicial"
                    else:
                        papel = "outros"

                    partes.append(ParteProcessual(nome=nome_raw, papel=papel))

        url_consulta = URLS_EPROC.get(tribunal, "")

        return ProcessoTribunalInfo(
            numero_cnj=numero_formatado,
            numero_limpo=numero_limpo,
            tribunal=tribunal.upper(),
            grau="1G",
            classe_codigo=129,
            classe_nome=classe,
            orgao_julgador=vara,
            vara=vara,
            valor_causa=valor_causa,
            partes=partes,
            devedores=devedores,
            credores=credores,
            url_consulta=url_consulta,
        )
