"""Testes de rate limiting e utilitários da CLI e configurações."""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from src.ingestao.cli import obter_slugs_validos
from src.ingestao.download import (
    aplicar_rate_limit,
    carregar_config_fonte,
    resetar_rate_limit,
)


class TestRateLimiting:
    """Testes da lógica de rate limiting por domínio."""

    def setup_method(self) -> None:
        """Limpa o cache de rate limit antes de cada teste."""
        resetar_rate_limit()

    def test_primeira_requisicao_sem_espera(self) -> None:
        """A primeira requisição para um domínio não deve ter espera."""
        espera = aplicar_rate_limit("https://dados.cvm.gov.br/arquivo.zip", delay_minimo=1.0)
        assert espera == 0.0

    def test_segunda_requisicao_mesmo_dominio_espera(self) -> None:
        """Requisições consecutivas imediatas ao mesmo domínio devem pausar."""
        aplicar_rate_limit("https://dados.cvm.gov.br/arquivo1.zip", delay_minimo=0.2)
        espera = aplicar_rate_limit("https://dados.cvm.gov.br/arquivo2.zip", delay_minimo=0.2)
        assert espera > 0.0

    def test_dominios_diferentes_nao_bloqueiam_mutuamente(self) -> None:
        """Requisições a domínios distintos não devem esperar uma pela outra."""
        aplicar_rate_limit("https://dados.cvm.gov.br/arquivo.zip", delay_minimo=1.0)
        # Domínio diferente imediatamente após
        espera = aplicar_rate_limit("https://esaj.tjsp.jus.br/processo", delay_minimo=1.0)
        assert espera == 0.0

    def test_delay_zero_ou_negativo_nao_espera(self) -> None:
        """Delay zero ou negativo retorna 0.0 imediatamente."""
        espera = aplicar_rate_limit("https://dados.cvm.gov.br/arquivo.zip", delay_minimo=0)
        assert espera == 0.0

    def test_resetar_rate_limit_limpa_historico(self) -> None:
        """Ao resetar, a próxima chamada ao mesmo domínio não deve esperar."""
        aplicar_rate_limit("https://dados.cvm.gov.br/arquivo.zip", delay_minimo=1.0)
        resetar_rate_limit()
        espera = aplicar_rate_limit("https://dados.cvm.gov.br/arquivo.zip", delay_minimo=1.0)
        assert espera == 0.0


class TestSlugsDinamicos:
    """Testes de resolução dinâmica de slugs na CLI."""

    def test_obter_slugs_do_yaml(self) -> None:
        """Carrega slugs das empresas configuradas no empresas.yaml."""
        slugs = obter_slugs_validos()
        assert isinstance(slugs, list)
        assert "oi" in slugs
        assert "americanas" in slugs
        assert "light" in slugs

    def test_fallback_em_caso_de_erro(self) -> None:
        """Retorna fallback padrão se houver falha ao carregar arquivo."""
        with patch("src.ingestao.cli.carregar_config_empresas", side_effect=Exception("YAML corrompido")):
            slugs = obter_slugs_validos()
            assert slugs == ["oi", "americanas", "light"]


class TestConfigFontes:
    """Testes de integridade dos arquivos YAML de configuração de fontes."""

    def test_cvm_ipe_yaml_sem_duplicacao(self) -> None:
        """Verifica se cvm_ipe.yaml carrega todas as propriedades essenciais."""
        config = carregar_config_fonte("cvm_ipe")
        assert config["nome"] == "CVM IPE"
        assert "urls" in config
        assert config["urls"]["pattern"] == "ipe_cia_aberta_{ano}.zip"
        assert config["campo_filtro"] == "Codigo_CVM"
        assert isinstance(config["categorias"], list)
        assert len(config["categorias"]) >= 4
        assert config["delay_entre_downloads"] == 1.0

    def test_cvm_dfp_itr_yaml_tem_delay(self) -> None:
        """Verifica se cvm_dfp_itr.yaml possui delay_entre_downloads configurado."""
        config = carregar_config_fonte("cvm_dfp_itr")
        assert config["delay_entre_downloads"] == 1.0
        assert "dfp_base" in config["urls"]
        assert "itr_base" in config["urls"]
