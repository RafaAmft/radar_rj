"""
Consultor para tribunais que utilizam o sistema PJe (Processo Judicial Eletrônico).
Suporta TJMG, TJMT, TJDF, TJPA, TJPE, TJBA, TJCE, TJES, TJMA, TJPB, TJPI, TJRN, TJRO, TJAP, TJRJ.
Combina parsing de consultas públicas web com fallback estruturado do DataJud (CNJ).
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urlencode

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
    MovimentacaoProcessual,
    ParteProcessual,
    ProcessoTribunalInfo,
)

logger = logging.getLogger(__name__)

# Mapeamento de URLs base de consulta pública do PJe por tribunal
URLS_PJE: dict[str, str] = {
    "tjmg": "https://pje.tjmg.jus.br/pje/ConsultaPublica/listView.seam",
    "tjmt": "https://mti.pje.jus.br/pje/ConsultaPublica/listView.seam",
    "tjdf": "https://pje.tjdft.jus.br/consultapublica/ConsultaPublica/listView.seam",
    "tjdft": "https://pje.tjdft.jus.br/consultapublica/ConsultaPublica/listView.seam",
    "tjba": "https://pje.tjba.jus.br/pje/ConsultaPublica/listView.seam",
    "tjce": "https://pje.tjce.jus.br/pje1grau/ConsultaPublica/listView.seam",
    "tjes": "https://pje.tjes.jus.br/pje/ConsultaPublica/listView.seam",
    "tjma": "https://pje.tjma.jus.br/pje/ConsultaPublica/listView.seam",
    "tjpa": "https://pje.tjpa.jus.br/pje/ConsultaPublica/listView.seam",
    "tjpb": "https://pje.tjpb.jus.br/pje/ConsultaPublica/listView.seam",
    "tjpe": "https://pje.tjpe.jus.br/pje/ConsultaPublica/listView.seam",
    "tjpi": "https://pje.tjpi.jus.br/1g/ConsultaPublica/listView.seam",
    "tjrj": "https://tjrj.pje.jus.br/1g/ConsultaPublica/listView.seam",
    "tjrn": "https://pje.tjrn.jus.br/pje/ConsultaPublica/listView.seam",
    "tjro": "https://pjepg.tjro.jus.br/consulta/ConsultaPublica/listView.seam",
    "tjap": "https://pje.tjap.jus.br/pje/ConsultaPublica/listView.seam",
}


class ConsultorPje(ConsultorTribunalBase):
    """Consultor especializado para Tribunais que utilizam o PJe."""

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
                "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8",
            }
        )

    def suporta_tribunal(self, sigla_tribunal: str) -> bool:
        """Verifica se o tribunal é suportado pelo consultor PJe."""
        sigla = sigla_tribunal.lower().strip()
        return sigla in URLS_PJE

    def consultar_processo(
        self, numero_cnj: str, html_conteudo: str | None = None
    ) -> ProcessoTribunalInfo | None:
        """
        Consulta um processo no PJe pelo número CNJ.
        Se html_conteudo for fornecido diretamente (ex: em testes ou scraping autenticado),
        realiza o parsing do HTML.
        Caso contrário, tenta consulta web direta ou aciona o fallback do DataJud.
        """
        numero_formatado = formatar_numero_cnj(numero_cnj)
        numero_limpo = limpar_numero_cnj(numero_cnj)
        sigla_tribunal, uf, _ = identificar_tribunal_por_cnj(numero_formatado)

        if not self.suporta_tribunal(sigla_tribunal):
            logger.warning("[ConsultorPje] Tribunal '%s' não suportado.", sigla_tribunal)
            return None

        # 1. Se foi passado HTML diretamente (mock ou teste)
        if html_conteudo:
            return self.parsear_html_processo(
                html=html_conteudo,
                numero_cnj=numero_formatado,
                tribunal=sigla_tribunal,
            )

        # 2. Tentar consulta web direta ao PJe
        url_base = URLS_PJE.get(sigla_tribunal)
        if url_base:
            try:
                html = self._requisitar_pje(url_base, numero_formatado)
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
                    "[ConsultorPje] Falha na consulta web direta PJe (%s): %s",
                    sigla_tribunal,
                    e,
                )

        # 3. Fallback inteligente: buscar via DataJud e enriquecer com contexto PJe
        logger.info(
            "[ConsultorPje] Acionando enriquecimento via DataJud para %s (%s)",
            numero_formatado,
            sigla_tribunal.upper(),
        )
        info_datajud = self.datajud.buscar_por_numero(
            numero_cnj=numero_formatado, tribunal=sigla_tribunal
        )

        if info_datajud:
            # Enriquecer URL de consulta pública do PJe
            info_datajud.url_consulta = url_base or ""
            return info_datajud

        return None

    def _requisitar_pje(self, url_base: str, numero_cnj: str) -> str | None:
        """Tenta submeter busca pontual ao portal PJe."""
        # Consulta GET inicial
        r = self.session.get(url_base, timeout=self.timeout)
        if r.status_code != 200:
            return None

        # Se a página contiver campos de busca ou tabela com o processo
        return r.text

    def _html_contem_dados_processo(self, html: str) -> bool:
        """Verifica se o HTML retornado contém dados reais do processo."""
        soup = BeautifulSoup(html, "html.parser")
        # Verifica se há tabela de processos ou detalhes do processo
        return bool(
            soup.find("table", class_=re.compile(r"rich-table|processo", re.I))
            or soup.find(id=re.compile(r"processo|dadosProcesso", re.I))
            or "polo ativo" in html.lower()
        )

    def parsear_html_processo(
        self, html: str, numero_cnj: str, tribunal: str
    ) -> ProcessoTribunalInfo:
        """Realiza o parsing dos dados estruturados da página do PJe."""
        soup = BeautifulSoup(html, "html.parser")
        numero_formatado = formatar_numero_cnj(numero_cnj)
        numero_limpo = limpar_numero_cnj(numero_cnj)

        classe = "Recuperação Judicial"
        classe_elem = soup.find(string=re.compile(r"Classe Judicial|Classe:", re.I))
        if classe_elem and classe_elem.parent:
            texto_classe = classe_elem.parent.get_text()
            m = re.search(r"Classe(?:\s+Judicial)?:\s*([^\n\r]+)", texto_classe, re.I)
            if m:
                classe = m.group(1).strip()

        vara = ""
        vara_elem = soup.find(string=re.compile(r"Órgão Julgador|Vara:", re.I))
        if vara_elem and vara_elem.parent:
            texto_vara = vara_elem.parent.get_text()
            m = re.search(r"(?:Órgão Julgador|Vara):\s*([^\n\r]+)", texto_vara, re.I)
            if m:
                vara = m.group(1).strip()

        valor_causa = 0.0
        valor_elem = soup.find(string=re.compile(r"Valor da causa:", re.I))
        if valor_elem and valor_elem.parent:
            texto_valor = valor_elem.parent.get_text()
            m = re.search(r"Valor da causa:\s*R?\$?\s*([\d\.,]+)", texto_valor, re.I)
            if m:
                num_str = m.group(1).replace(".", "").replace(",", ".")
                try:
                    valor_causa = float(num_str)
                except ValueError:
                    pass

        partes: list[ParteProcessual] = []
        devedores: list[str] = []
        credores: list[str] = []

        # Extração de partes (Polo Ativo, Polo Passivo, Outros)
        tabelas_partes = soup.find_all("table", class_=re.compile(r"rich-table|partes", re.I))
        for tabela in tabelas_partes:
            linhas = tabela.find_all("tr")
            for linha in linhas:
                colunas = linha.find_all(["td", "th"])
                if len(colunas) >= 2:
                    papel_raw = colunas[0].get_text().strip().lower()
                    nome_raw = colunas[1].get_text().strip()
                    if not nome_raw:
                        continue

                    # Identificar papel
                    if "ativo" in papel_raw or "autor" in papel_raw or "recuperand" in papel_raw:
                        papel = "recuperanda"
                        devedores.append(nome_raw)
                    elif "passivo" in papel_raw or "réu" in papel_raw or "credor" in papel_raw:
                        papel = "credor"
                        credores.append(nome_raw)
                    elif "administrador" in papel_raw or "perito" in papel_raw:
                        papel = "administrador_judicial"
                    else:
                        papel = "outros"

                    partes.append(ParteProcessual(nome=nome_raw, papel=papel))

        url_consulta = URLS_PJE.get(tribunal, "")

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
