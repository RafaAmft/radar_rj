"""
Pipeline orquestrador de Tribunais de Justiça.
Integra o sensor nacional DataJud (CNJ) com consultores de sistemas (e-SAJ, etc.)
e persiste os resultados enriquecidos no banco relacional radar.db.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from src.banco.repositorio import BancoDados
from src.ingestao.download import DIR_DATA_RAW, calcular_sha256_bytes
from src.ingestao.manifesto import ManifestoManager
from src.ingestao.tribunais.base import (
    formatar_numero_cnj,
    identificar_tribunal_por_cnj,
    limpar_numero_cnj,
)
from src.ingestao.tribunais.datajud import ClienteDataJud
from src.ingestao.tribunais.esaj import ConsultorEsaj
from src.ingestao.tribunais.modelos import ProcessoTribunalInfo

logger = logging.getLogger(__name__)


def gerar_slug(texto: str) -> str:
    """Gera um slug limpo para empresa ou processo."""
    slug = texto.lower().strip()
    slug = re.sub(r"[àáâãäå]", "a", slug)
    slug = re.sub(r"[èéêë]", "e", slug)
    slug = re.sub(r"[ìíîï]", "i", slug)
    slug = re.sub(r"[òóôõö]", "o", slug)
    slug = re.sub(r"[ùúûü]", "u", slug)
    slug = re.sub(r"[ç]", "c", slug)
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    return slug.strip("-")


class PipelineTribunais:
    """Orquestrador unificado de Tribunais de Justiça."""

    def __init__(
        self,
        cliente_datajud: ClienteDataJud | None = None,
        consultor_esaj: ConsultorEsaj | None = None,
        banco: BancoDados | None = None,
    ) -> None:
        self.datajud = cliente_datajud or ClienteDataJud()
        self.esaj = consultor_esaj or ConsultorEsaj()
        self.banco = banco or BancoDados()

    def processar_processo_especifico(
        self,
        numero_cnj: str,
        tribunal: str | None = None,
        salvar_banco: bool = True,
        salvar_raw: bool = True,
    ) -> ProcessoTribunalInfo | None:
        """
        Rastreia e enriquece um processo específico:
        1. Consulta o DataJud para obter dados de distribuição e movimentações.
        2. Consulta o consultor específico do tribunal (e-SAJ, etc.) para capa, partes e valor.
        3. Unifica e persiste no banco de dados.
        """
        numero_formatado = formatar_numero_cnj(numero_cnj)
        numero_limpo = limpar_numero_cnj(numero_cnj)

        sigla_tribunal, uf, sistema = identificar_tribunal_por_cnj(numero_formatado)
        if tribunal:
            sigla_tribunal = tribunal.lower()

        logger.info(
            "[Pipeline] Iniciando processamento do processo %s (%s - %s)",
            numero_formatado,
            sigla_tribunal.upper(),
            sistema.upper(),
        )

        # 1. Consulta no DataJud (CNJ)
        info_datajud = self.datajud.buscar_por_numero(
            numero_cnj=numero_formatado, tribunal=sigla_tribunal
        )

        # 2. Consulta no Consultor do Tribunal (ex: e-SAJ)
        info_consultor: ProcessoTribunalInfo | None = None
        if sistema == "esaj" and self.esaj.suporta_tribunal(sigla_tribunal):
            info_consultor = self.esaj.consultar_processo(numero_formatado)

        # 3. Unificar dados
        info_final = self._unificar_dados_processo(
            numero_formatado=numero_formatado,
            numero_limpo=numero_limpo,
            sigla_tribunal=sigla_tribunal,
            sistema=sistema,
            info_datajud=info_datajud,
            info_consultor=info_consultor,
        )

        if not info_final:
            logger.warning(
                "[Pipeline] Não foi possível obter dados para o processo %s",
                numero_formatado,
            )
            return None

        # 4. Persistir no Banco de Dados
        if salvar_banco:
            self.persistir_no_banco(info_final)

        # 5. Salvar payload RAW e registrar no manifesto
        if salvar_raw:
            self.salvar_manifesto_e_raw(info_final)

        return info_final

    def rastrear_novos_processos(
        self,
        tribunais: list[str],
        limite_por_tribunal: int = 10,
        classes: list[int] | None = None,
        salvar_banco: bool = True,
    ) -> list[ProcessoTribunalInfo]:
        """
        Varre múltiplos tribunais via DataJud em busca de novos processos de insolvência
        e enriquece cada caso identificado nos consultores de sistemas correspondentes.
        """
        resultados: list[ProcessoTribunalInfo] = []

        for tib in tribunais:
            sigla = tib.lower().strip()
            logger.info(
                "[Pipeline] Rastreando novos processos no tribunal %s...",
                sigla.upper(),
            )
            novos = self.datajud.listar_novos_processos(
                tribunal=sigla, classes=classes, limite=limite_por_tribunal
            )

            for proc in novos:
                # Enriquecer com consultor do sistema se suportado
                _, _, sistema = identificar_tribunal_por_cnj(proc.numero_cnj)
                info_consultor = None
                if sistema == "esaj" and self.esaj.suporta_tribunal(sigla):
                    info_consultor = self.esaj.consultar_processo(proc.numero_cnj)

                proc_unificado = self._unificar_dados_processo(
                    numero_formatado=proc.numero_cnj,
                    numero_limpo=proc.numero_limpo,
                    sigla_tribunal=sigla,
                    sistema=sistema,
                    info_datajud=proc,
                    info_consultor=info_consultor,
                )

                if proc_unificado:
                    if salvar_banco:
                        self.persistir_no_banco(proc_unificado)
                    resultados.append(proc_unificado)

        return resultados

    def _unificar_dados_processo(
        self,
        numero_formatado: str,
        numero_limpo: str,
        sigla_tribunal: str,
        sistema: str,
        info_datajud: ProcessoTribunalInfo | None,
        info_consultor: ProcessoTribunalInfo | None,
    ) -> ProcessoTribunalInfo | None:
        """Mescla com inteligência os dados do DataJud e do consultor do tribunal."""
        if not info_datajud and not info_consultor:
            return None

        # Priorizar dados de partes e valores do consultor, e dados de ajuizamento/movimentos do DataJud
        tribunal = (
            (info_consultor.tribunal if info_consultor else None)
            or (info_datajud.tribunal if info_datajud else None)
            or sigla_tribunal.upper()
        )
        grau = (
            info_datajud.grau
            if info_datajud
            else (info_consultor.grau if info_consultor else "G1")
        )
        classe_nome = (
            (info_consultor.classe_nome if info_consultor and info_consultor.classe_nome else None)
            or (info_datajud.classe_nome if info_datajud else "")
        )
        orgao_julgador = (
            (info_consultor.orgao_julgador if info_consultor and info_consultor.orgao_julgador else None)
            or (info_datajud.orgao_julgador if info_datajud else "")
        )
        comarca = info_consultor.comarca if info_consultor else ""
        vara = info_consultor.vara if info_consultor else ""
        valor_causa = info_consultor.valor_causa if info_consultor else None
        data_dist = info_datajud.data_distribuicao if info_datajud else ""
        movimentos = info_datajud.movimentacoes if info_datajud else []

        partes = info_consultor.partes if info_consultor else []
        devedores = info_consultor.devedores if info_consultor else []
        credores = info_consultor.credores if info_consultor else []
        admin_judicial = info_consultor.administrador_judicial if info_consultor else ""
        url_consulta = info_consultor.url_consulta if info_consultor else ""

        return ProcessoTribunalInfo(
            numero_cnj=numero_formatado,
            numero_limpo=numero_limpo,
            tribunal=tribunal,
            grau=grau,
            sistema=sistema,
            classe_codigo=info_datajud.classe_codigo if info_datajud else None,
            classe_nome=classe_nome,
            assuntos=info_datajud.assuntos if info_datajud else [],
            orgao_julgador=orgao_julgador,
            comarca=comarca,
            vara=vara,
            juiz=info_consultor.juiz if info_consultor else "",
            valor_causa=valor_causa,
            data_distribuicao=data_dist,
            partes=partes,
            devedores=devedores,
            credores=credores,
            administrador_judicial=admin_judicial,
            movimentacoes=movimentos,
            url_consulta=url_consulta,
            metadados_extra={
                "tem_datajud": bool(info_datajud),
                "tem_consultor": bool(info_consultor),
            },
        )

    def persistir_no_banco(self, info: ProcessoTribunalInfo) -> dict[str, int]:
        """Salva a empresa e o processo no banco relacional SQLite radar.db."""
        empresa_nome = info.devedores[0] if info.devedores else f"Processo {info.numero_cnj}"
        slug_empresa = gerar_slug(empresa_nome)
        slug_proc = f"proc-{gerar_slug(info.tribunal)}-{info.numero_limpo[:10]}"

        repo = self.banco
        # 1. Salvar Empresa
        empresa_id = repo.salvar_empresa(
            slug=slug_empresa,
            nome_razao_social=empresa_nome,
            cnpj="",
            setor="",
            origem_fonte=f"tribunal_{info.tribunal.lower()}",
        )

        # 2. Salvar Processo
        proc_id = repo.salvar_processo(
            empresa_id=empresa_id,
            slug=slug_proc,
            numero_cnj=info.numero_cnj,
            vara_comarca=info.orgao_julgador,
            administrador_judicial=info.administrador_judicial,
            tipo_processo="recuperacao_judicial",
            url_detalhe=info.url_consulta,
        )

        # 3. Salvar Documento de Capa/Andamentos
        doc_id = repo.salvar_documento(
            empresa_id=empresa_id,
            processo_id=proc_id,
            slug_documento=f"capa-{info.tribunal.lower()}-{info.numero_limpo}",
            titulo=f"Capa e Andamentos Judiciais - {info.numero_cnj}",
            categoria="OUTROS",
            url_download=info.url_consulta,
            caminho_arquivo=f"judiciario/{info.tribunal.lower()}/{info.numero_limpo}.json",
        )

        logger.info(
            "[Pipeline] Processo %s salvo no banco (Empresa ID: %d, Processo ID: %d)",
            info.numero_cnj,
            empresa_id,
            proc_id,
        )
        return {"empresa_id": empresa_id, "processo_id": proc_id, "documento_id": doc_id}

    def salvar_manifesto_e_raw(self, info: ProcessoTribunalInfo) -> Path:
        """Salva os dados do processo em JSON no data/raw/ e registra no manifesto."""
        empresa_slug = gerar_slug(info.devedores[0] if info.devedores else "desconhecido")
        dir_saida = DIR_DATA_RAW / empresa_slug / "judiciario" / info.tribunal.lower()
        dir_saida.mkdir(parents=True, exist_ok=True)

        arquivo_json = dir_saida / f"{info.numero_limpo}.json"
        conteudo_dict = {
            "numero_cnj": info.numero_cnj,
            "numero_limpo": info.numero_limpo,
            "tribunal": info.tribunal,
            "grau": info.grau,
            "sistema": info.sistema,
            "classe_codigo": info.classe_codigo,
            "classe_nome": info.classe_nome,
            "assuntos": info.assuntos,
            "orgao_julgador": info.orgao_julgador,
            "comarca": info.comarca,
            "vara": info.vara,
            "juiz": info.juiz,
            "valor_causa": info.valor_causa,
            "data_distribuicao": info.data_distribuicao,
            "devedores": info.devedores,
            "credores": info.credores,
            "administrador_judicial": info.administrador_judicial,
            "total_movimentacoes": len(info.movimentacoes),
            "url_consulta": info.url_consulta,
        }

        json_bytes = json.dumps(conteudo_dict, ensure_ascii=False, indent=2).encode("utf-8")
        arquivo_json.write_bytes(json_bytes)

        manifesto = ManifestoManager(DIR_DATA_RAW / empresa_slug, empresa=empresa_slug)
        manifesto.registrar(
            url_origem=info.url_consulta or f"datajud://{info.tribunal}/{info.numero_limpo}",
            arquivo_local=str(arquivo_json.relative_to(DIR_DATA_RAW / empresa_slug)).replace("\\", "/"),
            hash_sha256=calcular_sha256_bytes(json_bytes),
            tipo_fonte=f"tribunal_{info.tribunal.lower()}",
            status="ok",
            metadados_extra={
                "numero_cnj": info.numero_cnj,
                "valor_causa": info.valor_causa,
                "total_credores": len(info.credores),
            },
        )

        return arquivo_json


def executar(
    processo: str | None = None,
    tribunais: list[str] | None = None,
    limite: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """
    Ponto de entrada do extrator de tribunais para a CLI.

    Args:
        processo: Número CNJ específico (opcional).
        tribunais: Lista de siglas de tribunais a rastrear (default: ['tjsp']).
        limite: Limite de processos por tribunal na varredura (default: 5).
        dry_run: Se True, não persiste em banco ou disco.

    Returns:
        Dict com status e métricas da execução.
    """
    pipeline = PipelineTribunais()

    if processo:
        logger.info("[Tribunais] Executando consulta pontual para o processo: %s", processo)
        if dry_run:
            logger.info("[DRY-RUN] Consultaria DataJud e Tribunal para %s", processo)
            return {"status": "dry_run", "processo": processo}

        res = pipeline.processar_processo_especifico(
            numero_cnj=processo,
            salvar_banco=True,
            salvar_raw=True,
        )
        if res:
            return {
                "status": "ok",
                "processo": res.numero_cnj,
                "tribunal": res.tribunal,
                "valor_causa": res.valor_causa,
                "devedores": len(res.devedores),
                "credores": len(res.credores),
            }
        return {"status": "nao_encontrado", "processo": processo}

    # Varredura de novos processos
    tribs = tribunais or ["tjsp"]
    lim = limite or 5
    logger.info("[Tribunais] Rastreando tribunais: %s (limite: %d)", tribs, lim)

    if dry_run:
        logger.info("[DRY-RUN] Varreria DataJud e Consultores para tribunais %s", tribs)
        return {"status": "dry_run", "tribunais": tribs, "limite": lim}

    resultados = pipeline.rastrear_novos_processos(
        tribunais=tribs,
        limite_por_tribunal=lim,
        salvar_banco=True,
    )
    return {
        "status": "ok",
        "tribunais_processados": tribs,
        "total_encontrados": len(resultados),
        "processos": [p.numero_cnj for p in resultados],
    }

