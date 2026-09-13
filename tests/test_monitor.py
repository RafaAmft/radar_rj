"""
Testes unitários para o Monitor de Tribunais e Robô Contínuo.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.ingestao.tribunais.modelos import ProcessoTribunalInfo
from src.monitor.agendador import MonitorTribunais, RelatorioCiclo


@pytest.fixture
def caminho_estado_temp(tmp_path: Path) -> Path:
    return tmp_path / "monitor_estado_teste.json"


@pytest.fixture
def mock_pipeline() -> MagicMock:
    pipe = MagicMock()
    pipe.datajud.listar_novos_processos.return_value = [
        ProcessoTribunalInfo(
            numero_cnj="1000001-11.2024.8.26.0100",
            numero_limpo="10000011120248260100",
            tribunal="TJSP",
            classe_nome="Recuperação Judicial",
            orgao_julgador="1ª Vara",
        ),
        ProcessoTribunalInfo(
            numero_cnj="1000002-22.2024.8.26.0100",
            numero_limpo="10000022220248260100",
            tribunal="TJSP",
            classe_nome="Recuperação Judicial",
            orgao_julgador="1ª Vara",
        ),
    ]
    pipe.processar_processo_especifico.return_value = ProcessoTribunalInfo(
        numero_cnj="1000001-11.2024.8.26.0100",
        numero_limpo="10000011120248260100",
        tribunal="TJSP",
        classe_nome="Recuperação Judicial",
        valor_causa=5000000.0,
    )
    return pipe


class TestMonitorTribunais:
    """Testes para o orquestrador do monitor contínuo."""

    def test_carregar_e_salvar_estado(self, caminho_estado_temp: Path) -> None:
        monitor = MonitorTribunais(caminho_estado=caminho_estado_temp)
        estado_inicial = monitor.carregar_estado()
        assert estado_inicial["total_ciclos"] == 0
        assert estado_inicial["tribunais"] == {}

        estado_modificado = {
            "versao": "1.0",
            "total_ciclos": 3,
            "tribunais": {
                "tjsp": {"processos_vistos": ["10000011120248260100"]}
            },
        }
        monitor.salvar_estado(estado_modificado)

        estado_recarregado = monitor.carregar_estado()
        assert estado_recarregado["total_ciclos"] == 3
        assert "tjsp" in estado_recarregado["tribunais"]
        assert "10000011120248260100" in estado_recarregado["tribunais"]["tjsp"]["processos_vistos"]

    def test_executar_ciclo_unico_novos_processos(
        self, mock_pipeline: MagicMock, caminho_estado_temp: Path
    ) -> None:
        mock_rec = MagicMock()
        mock_rec.reconciliar_processos.return_value = 1

        monitor = MonitorTribunais(
            pipeline=mock_pipeline,
            caminho_estado=caminho_estado_temp,
            tribunais_padrao=["tjsp"],
            reconciliador=mock_rec,
        )

        relatorio = monitor.executar_ciclo(
            tribunais=["tjsp"],
            limite_por_tribunal=5,
            salvar_banco=False,
            salvar_raw=False,
            disparar_cruzamento=True,
        )

        assert relatorio.total_encontrados == 2
        assert relatorio.total_novos == 2
        assert relatorio.total_enriquecidos == 2
        assert relatorio.cruzamentos_realizados == 1
        assert relatorio.total_erros == 0
        assert len(relatorio.processos_processados) == 2

        # Verificar se o estado foi persistido em disco
        estado_salvo = monitor.carregar_estado()
        assert estado_salvo["total_ciclos"] == 1
        assert "10000011120248260100" in estado_salvo["tribunais"]["tjsp"]["processos_vistos"]

    def test_executar_ciclo_ignora_processos_ja_vistos(
        self, mock_pipeline: MagicMock, caminho_estado_temp: Path
    ) -> None:
        monitor = MonitorTribunais(
            pipeline=mock_pipeline,
            caminho_estado=caminho_estado_temp,
            tribunais_padrao=["tjsp"],
        )

        # Primeiro ciclo: encontra 2 novos
        relatorio1 = monitor.executar_ciclo(tribunais=["tjsp"], salvar_banco=False)
        assert relatorio1.total_novos == 2

        # Segundo ciclo com os mesmos dados retornados pela API: deve encontrar 0 novos
        relatorio2 = monitor.executar_ciclo(tribunais=["tjsp"], salvar_banco=False)
        assert relatorio2.total_encontrados == 2
        assert relatorio2.total_novos == 0
        assert relatorio2.total_enriquecidos == 0

    def test_executar_daemon_limite_max_ciclos(
        self, mock_pipeline: MagicMock, caminho_estado_temp: Path
    ) -> None:
        monitor = MonitorTribunais(
            pipeline=mock_pipeline,
            caminho_estado=caminho_estado_temp,
            tribunais_padrao=["tjsp"],
        )

        relatorios = monitor.executar_daemon(
            intervalo_segundos=0,
            max_ciclos=2,
            tribunais=["tjsp"],
            salvar_banco=False,
            disparar_cruzamento=False,
        )

        assert len(relatorios) == 2
        estado = monitor.carregar_estado()
        assert estado["total_ciclos"] == 2
