"""
Cliente para a API Pública do DataJud (Conselho Nacional de Justiça - CNJ).
Sensor nacional que monitora novos ajuizamentos de processos de insolvência.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import requests

from src.ingestao.tribunais.base import (
    formatar_numero_cnj,
    identificar_tribunal_por_cnj,
    limpar_numero_cnj,
)
from src.ingestao.tribunais.modelos import (
    MovimentacaoProcessual,
    ProcessoTribunalInfo,
)

logger = logging.getLogger(__name__)

URL_BASE_DATAJUD = "https://api-publica.datajud.cnj.jus.br"
API_KEY_PADRAO = (
    "cDZHYzlZa0JadVREZDJCendQbXY6SkJlTzNjLV9TRENyQk1RdnFKZGRQdw=="
)


class ClienteDataJud:
    """Cliente para consultas na API Pública do DataJud (Elasticsearch do CNJ)."""

    def __init__(
        self,
        api_key: str | None = None,
        url_base: str = URL_BASE_DATAJUD,
        timeout: int = 20,
    ) -> None:
        self.url_base = url_base.rstrip("/")
        chave = api_key or os.environ.get("DATAJUD_API_KEY", API_KEY_PADRAO)
        self.auth_header = (
            chave if chave.startswith("APIKey ") else f"APIKey {chave}"
        )
        self.timeout = timeout

    def _obter_headers(self) -> dict[str, str]:
        return {
            "Authorization": self.auth_header,
            "Content-Type": "application/json",
            "User-Agent": "RadarAtivos/1.0",
        }

    def _obter_endpoint_tribunal(self, tribunal: str) -> str:
        sigla = tribunal.lower().strip()
        return f"{self.url_base}/api_publica_{sigla}/_search"

    def buscar_por_numero(
        self, numero_cnj: str, tribunal: str | None = None
    ) -> ProcessoTribunalInfo | None:
        """
        Busca um processo específico pelo número CNJ no DataJud.
        Se o tribunal não for informado, deduz automaticamente do código CNJ.
        """
        numero_limpo = limpar_numero_cnj(numero_cnj)
        if not tribunal:
            sigla_deduzida, _, _ = identificar_tribunal_por_cnj(numero_limpo)
            if sigla_deduzida == "desconhecido":
                logger.error(
                    "Não foi possível identificar o tribunal pelo CNJ: %s",
                    numero_cnj,
                )
                return None
            tribunal = sigla_deduzida

        endpoint = self._obter_endpoint_tribunal(tribunal)
        payload = {
            "query": {
                "match": {
                    "numeroProcesso": numero_limpo
                }
            }
        }

        try:
            logger.info(
                "[DataJud] Consultando processo %s em %s...",
                numero_limpo,
                tribunal.upper(),
            )
            resp = requests.post(
                endpoint,
                headers=self._obter_headers(),
                json=payload,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            dados = resp.json()

            hits = dados.get("hits", {}).get("hits", [])
            if not hits:
                logger.warning(
                    "[DataJud] Processo %s não encontrado no %s",
                    numero_limpo,
                    tribunal.upper(),
                )
                return None

            return self._parsear_hit_datajud(hits[0]["_source"])

        except Exception as e:
            logger.error(
                "[DataJud] Erro ao consultar processo %s: %s", numero_cnj, e
            )
            return None

    def listar_novos_processos(
        self,
        tribunal: str,
        classes: list[int] | None = None,
        limite: int = 50,
    ) -> list[ProcessoTribunalInfo]:
        """
        Lista processos de insolvência ajuizados recentemente em determinado tribunal.
        Classes padrão: 129 (RJ), 128 (RE), 110 (Falência), 12134 (Tutela Antecedente).
        """
        if classes is None:
            classes = [129, 128, 110, 12134]

        endpoint = self._obter_endpoint_tribunal(tribunal)
        payload = {
            "size": min(limite, 100),
            "query": {
                "terms": {
                    "classe.codigo": classes
                }
            },
            "sort": [
                {"dataAjuizamento": {"order": "desc"}}
            ]
        }

        try:
            logger.info(
                "[DataJud] Listando até %d novos processos no %s (classes: %s)...",
                limite,
                tribunal.upper(),
                classes,
            )
            resp = requests.post(
                endpoint,
                headers=self._obter_headers(),
                json=payload,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            dados = resp.json()

            hits = dados.get("hits", {}).get("hits", [])
            logger.info(
                "[DataJud] %d processos retornados para %s",
                len(hits),
                tribunal.upper(),
            )

            resultados: list[ProcessoTribunalInfo] = []
            for hit in hits:
                parsed = self._parsear_hit_datajud(hit.get("_source", {}))
                if parsed:
                    resultados.append(parsed)

            return resultados

        except Exception as e:
            logger.error(
                "[DataJud] Erro ao listar processos do tribunal %s: %s",
                tribunal,
                e,
            )
            return []

    def _parsear_hit_datajud(
        self, src: dict[str, Any]
    ) -> ProcessoTribunalInfo | None:
        """Converte o documento _source do DataJud em ProcessoTribunalInfo."""
        num_raw = str(src.get("numeroProcesso", ""))
        if not num_raw:
            return None

        numero_formatado = formatar_numero_cnj(num_raw)
        numero_limpo = limpar_numero_cnj(num_raw)

        classe_info = src.get("classe", {})
        classe_codigo = classe_info.get("codigo")
        classe_nome = classe_info.get("nome", "")

        orgao_info = src.get("orgaoJulgador", {})
        orgao_nome = orgao_info.get("nome", "")

        assuntos_raw = src.get("assuntos", [])
        assuntos = [a.get("nome", "") for a in assuntos_raw if a.get("nome")]

        movimentos: list[MovimentacaoProcessual] = []
        for m in src.get("movimentos", []):
            compl = ""
            if "complementosTabelados" in m and m["complementosTabelados"]:
                compl = ", ".join(
                    str(c.get("nome", ""))
                    for c in m["complementosTabelados"]
                    if c.get("nome")
                )

            movimentos.append(
                MovimentacaoProcessual(
                    data_hora=m.get("dataHora", ""),
                    nome=m.get("nome", ""),
                    codigo_cnj=m.get("codigo"),
                    complemento=compl,
                    orgao_julgador=m.get("orgaoJulgador", {}).get("nome", "")
                    if isinstance(m.get("orgaoJulgador"), dict)
                    else "",
                )
            )

        return ProcessoTribunalInfo(
            numero_cnj=numero_formatado,
            numero_limpo=numero_limpo,
            tribunal=src.get("tribunal", "").upper(),
            grau=src.get("grau", "G1"),
            sistema=src.get("sistema", {}).get("nome", ""),
            classe_codigo=classe_codigo,
            classe_nome=classe_nome,
            assuntos=assuntos,
            orgao_julgador=orgao_nome,
            data_distribuicao=str(src.get("dataAjuizamento", "")),
            data_atualizacao=str(src.get("dataHoraUltimaAtualizacao", "")),
            movimentacoes=movimentos,
            metadados_extra={"fonte": "datajud_cnj"},
        )
