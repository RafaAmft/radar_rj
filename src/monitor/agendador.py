"""
Robô contínuo e agendador para monitoramento de novos processos em Tribunais de Justiça.
Mantém controle de estado incremental para evitar reprocessamentos desnecessários.
"""

from __future__ import annotations

import json
import logging
import signal
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.banco.repositorio import BancoDados
from src.ingestao.download import DIR_DATA_RAW
from src.ingestao.tribunais.pipeline import PipelineTribunais

logger = logging.getLogger(__name__)

ARQUIVO_ESTADO_PADRAO = DIR_DATA_RAW / "monitor_estado.json"
TRIBUNAIS_PADRAO = ["tjsp", "tjmg", "tjrs", "tjmt", "tjsc", "tjrj"]


@dataclass
class RelatorioCiclo:
    """Relatório consolidado da execução de um ciclo de monitoramento."""

    inicio: str
    fim: str
    tribunais: list[str]
    total_encontrados: int = 0
    total_novos: int = 0
    total_enriquecidos: int = 0
    total_erros: int = 0
    processos_processados: list[str] = field(default_factory=list)
    cruzamentos_realizados: int = 0

    def para_dict(self) -> dict[str, Any]:
        return asdict(self)


class MonitorTribunais:
    """
    Monitor contínuo de Tribunais de Justiça.
    Executa ciclos de varredura periódica no sensor DataJud e consultores especializados.
    """

    def __init__(
        self,
        pipeline: PipelineTribunais | None = None,
        caminho_estado: Path | str | None = None,
        tribunais_padrao: list[str] | None = None,
        reconciliador: Any | None = None,
    ) -> None:
        self.pipeline = pipeline or PipelineTribunais()
        self.caminho_estado = (
            Path(caminho_estado) if caminho_estado else ARQUIVO_ESTADO_PADRAO
        )
        self.tribunais_padrao = tribunais_padrao or TRIBUNAIS_PADRAO
        self.reconciliador = reconciliador
        self._parar_daemon = False

    def carregar_estado(self) -> dict[str, Any]:
        """Carrega o histórico incremental de execução por tribunal."""
        if not self.caminho_estado.exists():
            return {"versao": "1.0", "tribunais": {}, "total_ciclos": 0}

        try:
            with open(self.caminho_estado, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning("[Monitor] Erro ao carregar estado de %s: %s", self.caminho_estado, e)
            return {"versao": "1.0", "tribunais": {}, "total_ciclos": 0}

    def salvar_estado(self, estado: dict[str, Any]) -> None:
        """Salva o histórico incremental em disco."""
        try:
            self.caminho_estado.parent.mkdir(parents=True, exist_ok=True)
            with open(self.caminho_estado, "w", encoding="utf-8") as f:
                json.dump(estado, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error("[Monitor] Falha ao salvar estado em %s: %s", self.caminho_estado, e)

    def executar_ciclo(
        self,
        tribunais: list[str] | None = None,
        limite_por_tribunal: int = 10,
        salvar_banco: bool = True,
        salvar_raw: bool = True,
        disparar_cruzamento: bool = True,
    ) -> RelatorioCiclo:
        """
        Executa um único ciclo de monitoramento nos tribunais especificados.
        """
        inicio = datetime.now(timezone.utc).isoformat()
        tribunais_alvo = [t.lower().strip() for t in (tribunais or self.tribunais_padrao)]

        relatorio = RelatorioCiclo(
            inicio=inicio,
            fim="",
            tribunais=tribunais_alvo,
        )

        estado = self.carregar_estado()
        tribunais_estado = estado.setdefault("tribunais", {})

        logger.info(
            "[Monitor] Iniciando ciclo de monitoramento em %d tribunais: %s",
            len(tribunais_alvo),
            ", ".join(tribunais_alvo).upper(),
        )

        novos_processos_geral: list[str] = []

        for sigla in tribunais_alvo:
            info_tribunal = tribunais_estado.setdefault(sigla, {
                "processos_vistos": [],
                "ultimo_ajuizamento": "",
                "total_execucoes": 0,
            })
            processos_vistos = set(info_tribunal.get("processos_vistos", []))

            logger.info("[Monitor] Varrendo %s (limite: %d)...", sigla.upper(), limite_por_tribunal)
            try:
                candidatos = self.pipeline.datajud.listar_novos_processos(
                    tribunal=sigla, limite=limite_por_tribunal
                )
                relatorio.total_encontrados += len(candidatos)

                for candidato in candidatos:
                    cnj_limpo = candidato.numero_limpo
                    if cnj_limpo in processos_vistos:
                        # Processo já analisado em ciclo anterior
                        continue

                    relatorio.total_novos += 1
                    logger.info(
                        "[Monitor] Novo processo detectado em %s: %s (%s)",
                        sigla.upper(),
                        candidato.numero_cnj,
                        candidato.classe_nome,
                    )

                    # Enriquecer e persistir via pipeline
                    try:
                        info_enriquecida = self.pipeline.processar_processo_especifico(
                            numero_cnj=candidato.numero_cnj,
                            tribunal=sigla,
                            salvar_banco=salvar_banco,
                            salvar_raw=salvar_raw,
                        )
                        if info_enriquecida:
                            relatorio.total_enriquecidos += 1
                            relatorio.processos_processados.append(candidato.numero_cnj)
                            novos_processos_geral.append(candidato.numero_cnj)
                    except Exception as e_proc:
                        relatorio.total_erros += 1
                        logger.error(
                            "[Monitor] Erro ao enriquecer processo %s: %s",
                            candidato.numero_cnj,
                            e_proc,
                        )

                    # Registrar como visto (guarda no máximo os últimos 1000 CNJs por tribunal)
                    processos_vistos.add(cnj_limpo)

                # Atualizar estado do tribunal
                info_tribunal["processos_vistos"] = list(processos_vistos)[-1000:]
                info_tribunal["ultima_execucao"] = datetime.now(timezone.utc).isoformat()
                info_tribunal["total_execucoes"] = info_tribunal.get("total_execucoes", 0) + 1

            except Exception as e_trib:
                relatorio.total_erros += 1
                logger.error("[Monitor] Falha na varredura do tribunal %s: %s", sigla.upper(), e_trib)

        # 3. Disparar reconciliação / cruzamento automático se solicitado
        if disparar_cruzamento and novos_processos_geral:
            logger.info(
                "[Monitor] Disparando reconciliação automática para %d novos processos...",
                len(novos_processos_geral),
            )
            cruzamentos = self._executar_cruzamento(novos_processos_geral)
            relatorio.cruzamentos_realizados = cruzamentos

        # Atualizar estado global
        estado["total_ciclos"] = estado.get("total_ciclos", 0) + 1
        estado["ultimo_ciclo"] = inicio
        self.salvar_estado(estado)

        relatorio.fim = datetime.now(timezone.utc).isoformat()
        logger.info(
            "[Monitor] Ciclo concluído. Encontrados: %d, Novos: %d, Enriquecidos: %d, Cruzamentos: %d, Erros: %d",
            relatorio.total_encontrados,
            relatorio.total_novos,
            relatorio.total_enriquecidos,
            relatorio.cruzamentos_realizados,
            relatorio.total_erros,
        )
        return relatorio

    def _executar_cruzamento(self, processos_cnj: list[str]) -> int:
        """Invoca o reconciliador de fontes para cruzamento com scrapers de AJ."""
        if self.reconciliador:
            try:
                return self.reconciliador.reconciliar_processos(processos_cnj)
            except Exception as e:
                logger.error("[Monitor] Erro na chamada do reconciliador injetado: %s", e)
                return 0

        # Tentar import dinâmico do ReconciliadorFontes
        try:
            from src.cruzamento.reconciliador import ReconciliadorFontes
            rec = ReconciliadorFontes(banco=self.pipeline.banco)
            return rec.reconciliar_processos(processos_cnj)
        except ImportError:
            logger.debug("[Monitor] ReconciliadorFontes ainda não disponível.")
            return 0
        except Exception as e:
            logger.error("[Monitor] Falha na reconciliação de fontes: %s", e)
            return 0

    def executar_daemon(
        self,
        intervalo_segundos: int = 300,
        max_ciclos: int | None = None,
        tribunais: list[str] | None = None,
        limite_por_tribunal: int = 10,
        salvar_banco: bool = True,
        disparar_cruzamento: bool = True,
    ) -> list[RelatorioCiclo]:
        """
        Executa o monitor em modo daemon/loop contínuo.
        Respeita sinal SIGINT (Ctrl+C) para finalização graciosa.
        """
        self._parar_daemon = False

        def _handler_sinal(signum: int, frame: Any) -> None:
            logger.info("[Monitor Daemon] Sinal de parada recebido (%d). Finalizando...", signum)
            self._parar_daemon = True

        try:
            signal.signal(signal.SIGINT, _handler_sinal)
            signal.signal(signal.SIGTERM, _handler_sinal)
        except (ValueError, AttributeError):
            # No Windows ou threads secundárias, alguns sinais podem não estar disponíveis
            pass

        ciclos_executados = 0
        relatorios: list[RelatorioCiclo] = []

        logger.info(
            "[Monitor Daemon] Iniciando serviço em segundo plano (Intervalo: %ds, Max Ciclos: %s)",
            intervalo_segundos,
            str(max_ciclos) if max_ciclos else "Infinito",
        )

        while not self._parar_daemon:
            ciclos_executados += 1
            logger.info("[Monitor Daemon] === Executando Ciclo #%d ===", ciclos_executados)

            relatorio = self.executar_ciclo(
                tribunais=tribunais,
                limite_por_tribunal=limite_por_tribunal,
                salvar_banco=salvar_banco,
                salvar_raw=True,
                disparar_cruzamento=disparar_cruzamento,
            )
            relatorios.append(relatorio)

            if max_ciclos and ciclos_executados >= max_ciclos:
                logger.info("[Monitor Daemon] Limite de %d ciclos atingido. Encerrando.", max_ciclos)
                break

            if self._parar_daemon:
                break

            logger.info("[Monitor Daemon] Aguardando %d segundos até a próxima varredura...", intervalo_segundos)
            # Sleep fracionado para responder rapidamente a sinais de parada
            passos = max(1, intervalo_segundos)
            for _ in range(passos):
                if self._parar_daemon:
                    break
                time.sleep(1)

        logger.info("[Monitor Daemon] Serviço encerrado com sucesso. Total de ciclos: %d", ciclos_executados)
        return relatorios
