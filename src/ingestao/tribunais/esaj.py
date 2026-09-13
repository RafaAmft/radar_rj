"""
Consultor pontual para Tribunais de Justiça que utilizam o sistema e-SAJ (Softplan).
Cobre: TJSP, TJSC, TJMS, TJAL, TJAM, TJAC.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from src.ingestao.tribunais.base import (
    ConsultorTribunalBase,
    formatar_numero_cnj,
    identificar_tribunal_por_cnj,
    limpar_numero_cnj,
)
from src.ingestao.tribunais.modelos import ParteProcessual, ProcessoTribunalInfo

logger = logging.getLogger(__name__)

URLS_CPOPG_ESAJ = {
    "tjsp": "https://esaj.tjsp.jus.br/cpopg",
    "tjsc": "https://esaj.tjsc.jus.br/cpopg",
    "tjms": "https://esaj.tjms.jus.br/cpopg",
    "tjal": "https://www.tjal.jus.br/cpopg",
    "tjam": "https://consultasaj.tjam.jus.br/cpopg",
    "tjac": "https://esaj.tjac.jus.br/cpopg",
}


class ConsultorEsaj(ConsultorTribunalBase):
    """Consultor para processos em tribunais que operam e-SAJ."""

    def __init__(self, timeout: int = 15) -> None:
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        })

    def suporta_tribunal(self, sigla_tribunal: str) -> bool:
        return sigla_tribunal.lower().strip() in URLS_CPOPG_ESAJ

    def consultar_processo(self, numero_cnj: str) -> ProcessoTribunalInfo | None:
        """
        Consulta a capa do processo no e-SAJ pelo número CNJ.
        Extrai valor da causa, foro, vara e lista detalhada de partes.
        """
        numero_formatado = formatar_numero_cnj(numero_cnj)
        numero_limpo = limpar_numero_cnj(numero_cnj)

        sigla_tribunal, uf, sistema = identificar_tribunal_por_cnj(numero_formatado)
        if not self.suporta_tribunal(sigla_tribunal):
            logger.warning(
                "[e-SAJ] Tribunal '%s' não utiliza o sistema e-SAJ.",
                sigla_tribunal.upper(),
            )
            return None

        url_base = URLS_CPOPG_ESAJ[sigla_tribunal]
        url_busca = f"{url_base}/search.do"
        url_open = f"{url_base}/open.do"

        # NNNNNNN-DD.AAAA.J.TR.OOOO
        partes_cnj = numero_formatado.split(".")
        num_dig_ano = partes_cnj[0]  # NNNNNNN-DD.AAAA
        foro_unificado = partes_cnj[-1]  # OOOO

        params = {
            "conversationId": "",
            "cbPesquisa": "NUMPROC",
            "numeroDigitoAnoUnificado": num_dig_ano,
            "foroNumeroUnificado": foro_unificado,
            "dadosConsulta.valorConsultaNuUnificado": numero_formatado,
            "dadosConsulta.tipoNuProcesso": "UNIFICADO",
        }

        try:
            logger.info(
                "[e-SAJ] Consultando capa do processo %s no %s...",
                numero_formatado,
                sigla_tribunal.upper(),
            )
            # Obter cookies iniciais na tela de abertura
            self.session.get(url_open, timeout=self.timeout)

            resp = self.session.get(url_busca, params=params, timeout=self.timeout)
            resp.raise_for_status()

            html = resp.text
            soup = BeautifulSoup(html, "html.parser")

            # O e-SAJ carrega bibliotecas de captcha no <head> mesmo em acessos liberados.
            # Confirmamos bloqueio real apenas se os dados do processo estiverem ausentes.
            tem_dados = bool(
                soup.find(id="classeProcesso")
                or soup.find(id="tableTodasPartes")
                or soup.find(id="tablePartesPrincipais")
                or soup.find(id="foroProcesso")
            )

            if not tem_dados and ("captcha" in html.lower() or "recaptcha" in html.lower()):
                logger.warning(
                    "[e-SAJ] Desafio de Captcha bloqueou a consulta do processo %s",
                    numero_formatado,
                )
                return None

            return self.parsear_html_processo(
                html=html,
                numero_cnj=numero_formatado,
                tribunal=sigla_tribunal.upper(),
                url_consulta=resp.url,
            )

        except Exception as e:
            logger.error(
                "[e-SAJ] Erro na consulta do processo %s: %s", numero_formatado, e
            )
            return None

    def parsear_html_processo(
        self,
        html: str,
        numero_cnj: str,
        tribunal: str = "TJSP",
        url_consulta: str = "",
    ) -> ProcessoTribunalInfo:
        """Parseia o HTML da página show.do ou search.do do e-SAJ."""
        soup = BeautifulSoup(html, "html.parser")
        numero_limpo = limpar_numero_cnj(numero_cnj)

        classe = soup.find(id="classeProcesso")
        assunto = soup.find(id="assuntoProcesso")
        foro = soup.find(id="foroProcesso")
        vara = soup.find(id="varaProcesso")
        juiz = soup.find(id="juizProcesso")
        valor_elem = soup.find(id="valorAcaoProcesso")

        classe_txt = classe.get_text().strip() if classe else ""
        assunto_txt = assunto.get_text().strip() if assunto else ""
        foro_txt = foro.get_text().strip() if foro else ""
        vara_txt = vara.get_text().strip() if vara else ""
        juiz_txt = juiz.get_text().strip() if juiz else ""

        valor_causa = None
        if valor_elem:
            valor_raw = valor_elem.get_text().strip()
            # Limpar "R$ 90.419.751,76" -> 90419751.76
            num_match = re.search(r"([\d\.,]+)", valor_raw)
            if num_match:
                limpo = num_match.group(1).replace(".", "").replace(",", ".")
                try:
                    valor_causa = float(limpo)
                except ValueError:
                    pass

        # Extrair partes
        partes_elem = soup.find(id="tableTodasPartes") or soup.find(
            id="tablePartesPrincipais"
        )
        partes: list[ParteProcessual] = []
        devedores: list[str] = []
        credores: list[str] = []
        admin_judicial = ""

        if partes_elem:
            for tr in partes_elem.find_all("tr"):
                tds = [td.get_text(separator=" ", strip=True) for td in tr.find_all("td")]
                if len(tds) >= 2:
                    papel_raw = tds[0].strip().rstrip(":")
                    detalhe_raw = tds[1].strip()

                    # Separar nome da parte e advogados
                    partes_adv = re.split(r"\s+Advogad[oa]:\s*", detalhe_raw)
                    nome_parte = partes_adv[0].strip()
                    advogados = [a.strip() for a in partes_adv[1:] if a.strip()]

                    papel_lower = papel_raw.lower()
                    if any(
                        p in papel_lower
                        for p in ["falido", "reqdo", "recuperanda", "autor", "requerente"]
                    ):
                        papel_norm = "devedor"
                        if nome_parte and nome_parte not in devedores:
                            devedores.append(nome_parte)
                    elif "credor" in papel_lower:
                        papel_norm = "credor"
                        if nome_parte and nome_parte not in credores:
                            credores.append(nome_parte)
                    elif "administrador" in papel_lower:
                        papel_norm = "administrador_judicial"
                        if not admin_judicial:
                            admin_judicial = nome_parte
                    else:
                        papel_norm = papel_lower

                    if nome_parte:
                        partes.append(
                            ParteProcessual(
                                nome=nome_parte,
                                papel=papel_norm,
                                advogados=advogados,
                            )
                        )

        return ProcessoTribunalInfo(
            numero_cnj=numero_cnj,
            numero_limpo=numero_limpo,
            tribunal=tribunal,
            grau="G1",
            sistema="esaj",
            classe_nome=classe_txt,
            assuntos=[assunto_txt] if assunto_txt else [],
            orgao_julgador=f"{vara_txt} - {foro_txt}".strip(" -"),
            comarca=foro_txt,
            vara=vara_txt,
            juiz=juiz_txt,
            valor_causa=valor_causa,
            partes=partes,
            devedores=devedores,
            credores=credores,
            administrador_judicial=admin_judicial,
            url_consulta=url_consulta,
            metadados_extra={"fonte": "esaj_cpopg"},
        )
