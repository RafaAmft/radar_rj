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
from src.ingestao.tribunais.modelos import (
    MovimentacaoProcessual,
    ParteProcessual,
    ProcessoTribunalInfo,
)

logger = logging.getLogger(__name__)

URLS_CPOPG_ESAJ = {
    "tjsp": "https://esaj.tjsp.jus.br/cpopg",
    "tjsc": "https://esaj.tjsc.jus.br/cpopg",
    "tjms": "https://esaj.tjms.jus.br/cpopg",
    "tjal": "https://www.tjal.jus.br/cpopg",
    "tjam": "https://consultasaj.tjam.jus.br/cpopg",
    "tjac": "https://esaj.tjac.jus.br/cpopg",
}

# Andamentos meramente burocráticos sem conteúdo decisório ou material
TERMOS_RUIDO_ESAJ = [
    "certidão de remessa da intimação para o portal eletrônico",
    "certidão de publicação expedida",
    "conclusos para despacho",
    "ato ordinatório - intimação - portal",
    "ato ordinatório - não publicável",
    "juntada de ar",
    "expedição de ar",
    "guia emitida",
    "certidão de cartório expedida certidão - manual - cadastro de partes",
    "distribuído por direcionamento",
    "recebidos os autos",
]

# Padrões para classificação de marcos estratégicos (tipo_evento e autor)
PADROES_RELEVANCIA_ESAJ = [
    (r"\b(homolog\w*|senten[çc]\w*)\b", "HOMOLOGACAO", "JUIZO"),
    (r"\b(deferi\w*.*processamento|decis[ãa]o.*processamento|processamento.*recupera[çc]\w*)\b", "DECISAO_PROCESSAMENTO", "JUIZO"),
    (r"\b(stay\s+period|suspens[ãa]o.*a[çc][õo]es|tutela.*urg[êe]ncia|cautelar)\b", "DECISAO", "JUIZO"),
    (r"\b(fal[êe]ncia|convol\w*.*fal[êe]ncia|decreto.*fal[êe]ncia)\b", "FALENCIA", "JUIZO"),
    (r"\b(decis[ãa]o|interlocut[óo]ria|deferi\w*|indeferi\w*|determina\w*)\b", "DECISAO", "JUIZO"),
    (r"\b(relat[óo]rio\s+mensal|rma\b|presta[çc][ãa]o.*contas.*aj)\b", "RMA_AJ", "AJ"),
    (r"\b(administrador\s+judicial|manifesta[çc][ãa]o.*aj|peti[çc][ãa]o.*aj\b|laudo.*aj)\b", "MANIFESTACAO_AJ", "AJ"),
    (r"\b(assemblei\w*|agc\b|delibera[çc]\w*.*credores|ata.*assemblei\w*)\b", "AGC", "AJ"),
    (r"\b(plano.*recupera[çc]\w*|prj\b|aditivo.*plano|modificativo.*plano)\b", "PRJ", "RECUPERANDA"),
    (r"\b(quadro\s+geral|rela[çc][ãa]o.*credores|edital.*art.*7|edital.*art.*52|edital.*credores)\b", "QGC", "AJ"),
    (r"\b(impugna[çc]\w*.*cr[éx]dito|habilita[çc]\w*.*cr[éx]dito)\b", "CREDOR", "CREDOR"),
    (r"\b(peti[çc][ãa]o\s+inicial|emenda.*inicial)\b", "PETICAO_INICIAL", "RECUPERANDA"),
    (r"\b(dip\b|financiamento\s+dip|aliena[çc]\w*.*upi|leil[ãa]o|leiloeir\w*)\b", "DECISAO", "JUIZO"),
    (r"\b(manifesta[çc][ãa]o.*mp|minist[éx]rio\s+p[úu]blico)\b", "MANIFESTACAO_MP", "MP"),
]


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

            info = self.parsear_html_processo(
                html=html,
                numero_cnj=numero_formatado,
                tribunal=sigla_tribunal.upper(),
                url_consulta=resp.url,
            )

            # Extração de movimentações relevantes
            codigo_processo = self.extrair_codigo_processo(html=html, url=resp.url)
            if codigo_processo:
                info.movimentacoes = self.obter_movimentacoes(
                    codigo_processo=codigo_processo,
                    sigla_tribunal=sigla_tribunal,
                    max_paginas=5,
                    apenas_relevantes=True,
                )
                logger.info(
                    "[e-SAJ] Extraídas %d movimentações relevantes para %s",
                    len(info.movimentacoes),
                    numero_formatado,
                )

            return info

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

    def extrair_codigo_processo(self, html: str, url: str = "") -> str | None:
        """Extrai o identificador único do processo (processo.codigo) no e-SAJ."""
        if url:
            m_url = re.search(r"processo\.codigo=([a-zA-Z0-9]+)", url)
            if m_url:
                return m_url.group(1)

        if not html:
            return None

        m_js = re.search(r"codigoProcesso[\s:=]+['\"]([a-zA-Z0-9]+)['\"]", html)
        if m_js:
            return m_js.group(1)

        m_query = re.search(r"queryString\s*=\s*['\"][^'\"]*processo\.codigo=([a-zA-Z0-9]+)", html)
        if m_query:
            return m_query.group(1)

        m_action = re.search(r"action=.*processo\.codigo=([a-zA-Z0-9]+)", html)
        if m_action:
            return m_action.group(1)

        return None

    def classificar_movimentacao(self, nome: str, complemento: str) -> tuple[bool, str, str]:
        """
        Aplica filtro de relevância e classifica o evento processual.
        Retorna (relevante: bool, tipo_evento: str, autor: str).
        """
        texto_completo = f"{nome} {complemento}".strip().lower()

        # 1. Verificar se é ruído de secretaria sem conteúdo decisório ou material
        for ruido in TERMOS_RUIDO_ESAJ:
            if ruido in texto_completo:
                # Se for certidão simples sem menção ao AJ, Plano ou Decisão, descarta
                if not any(k in texto_completo for k in ["decis", "homolog", "deferid", "administrador", "plano", "aj"]):
                    return False, "RUIDO", "CARTORIO"

        # 2. Identificar marcos estratégicos pelos padrões
        for padrao, tipo_evento, autor in PADROES_RELEVANCIA_ESAJ:
            if re.search(padrao, texto_completo, re.IGNORECASE):
                return True, tipo_evento, autor

        # 3. Petições de partes
        if "petição" in texto_completo or "manifestação" in texto_completo:
            return True, "PETICAO", "PARTE"

        # 4. Despachos
        if "despacho" in texto_completo:
            return True, "DESPACHO", "JUIZO"

        # Caso contrário, não é relevante para a linha do tempo executiva
        return False, "OUTROS", "CARTORIO"

    def obter_movimentacoes(
        self,
        codigo_processo: str,
        sigla_tribunal: str = "tjsp",
        max_paginas: int = 5,
        apenas_relevantes: bool = True,
    ) -> list[MovimentacaoProcessual]:
        """
        Coleta movimentações processuais paginadas via AJAX no e-SAJ,
        aplicando o filtro de relevância para descartar atos de mero expediente.
        """
        sigla = sigla_tribunal.lower().strip()
        url_base = URLS_CPOPG_ESAJ.get(sigla, URLS_CPOPG_ESAJ["tjsp"])
        url_ajax = f"{url_base}/carregarMovimentacoesAjax.do"

        movimentacoes: list[MovimentacaoProcessual] = []
        cursor: str | None = None
        pagina = 0

        while pagina < max_paginas:
            pagina += 1
            params: dict[str, str] = {"processo.codigo": codigo_processo}
            if cursor:
                params["cursor"] = cursor

            try:
                resp = self.session.get(
                    url_ajax,
                    params=params,
                    headers={"X-Requested-With": "XMLHttpRequest"},
                    timeout=self.timeout,
                )
                if resp.status_code != 200:
                    break

                soup = BeautifulSoup(resp.text, "html.parser")
                trs = soup.find_all("tr", class_="containerMovimentacao")
                if not trs:
                    break

                for tr in trs:
                    dt_elem = tr.find("td", class_="dataMovimentacao")
                    desc_elem = tr.find("td", class_="descricaoMovimentacao")

                    data_hora = dt_elem.get_text(strip=True) if dt_elem else ""
                    if not desc_elem:
                        continue

                    # Extrair título e complemento
                    link_doc = desc_elem.find("a", class_="linkMovVincProc")
                    doc_id = ""
                    if link_doc and link_doc.get("id"):
                        doc_id = str(link_doc.get("id", ""))

                    texto_desc = desc_elem.get_text(separator=" ", strip=True)
                    partes_desc = texto_desc.split(" ", 3)
                    nome_mov = " ".join(partes_desc[:3]) if len(partes_desc) >= 3 else texto_desc
                    complemento = texto_desc[len(nome_mov):].strip()

                    relevante, tipo_evento, autor = self.classificar_movimentacao(nome_mov, complemento)

                    if apenas_relevantes and not relevante:
                        continue

                    movimentacoes.append(
                        MovimentacaoProcessual(
                            data_hora=data_hora,
                            nome=nome_mov,
                            complemento=complemento or texto_desc,
                            tipo_evento=tipo_evento,
                            autor=autor,
                            documento_id=doc_id,
                            relevante=relevante,
                        )
                    )

                # Verificar cursor para próxima página
                cursor_inp = soup.find("input", id="cursorMovimentacoesPaginado")
                if cursor_inp and cursor_inp.get("value"):
                    novo_cursor = cursor_inp["value"].strip()
                    if novo_cursor == cursor:
                        break
                    cursor = novo_cursor
                else:
                    break

            except Exception as e:
                logger.warning("[e-SAJ] Erro ao carregar página %d de movimentações: %s", pagina, e)
                break

        return movimentacoes

    def obter_movimentacoes_por_url(
        self,
        url_show: str,
        max_paginas: int = 5,
        apenas_relevantes: bool = True,
    ) -> list[MovimentacaoProcessual]:
        """
        Acessa diretamente uma URL show.do do e-SAJ e extrai as movimentações filtradas.
        """
        try:
            resp = self.session.get(url_show, timeout=self.timeout)
            resp.raise_for_status()
            codigo = self.extrair_codigo_processo(html=resp.text, url=resp.url)
            if not codigo:
                return []

            sigla = "tjsp"
            for s in URLS_CPOPG_ESAJ:
                if s in url_show.lower():
                    sigla = s
                    break

            return self.obter_movimentacoes(
                codigo_processo=codigo,
                sigla_tribunal=sigla,
                max_paginas=max_paginas,
                apenas_relevantes=apenas_relevantes,
            )
        except Exception as e:
            logger.error("[e-SAJ] Erro ao obter movimentações por URL: %s", e)
            return []
