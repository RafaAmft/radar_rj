"""
Testes unitários para o catálogo das 50 maiores RJs e consultas analíticas do dashboard.
"""

from __future__ import annotations

import pytest

from src.banco.repositorio import BancoDados
from src.dados.catalogo_top50 import CATALOGO_TOP_50_RJS


def test_catalogo_top50_estrutura() -> None:
    """Valida a consistência e completude do catálogo curado das maiores RJs."""
    assert len(CATALOGO_TOP_50_RJS) >= 50

    for caso in CATALOGO_TOP_50_RJS:
        assert caso["slug"]
        assert caso["nome_razao_social"]
        assert caso["tribunal"] in ["TJSP", "TJRJ", "TJMG", "TJPE", "TJMT", "TJPR", "TJRS"]
        assert caso["valor_causa"] > 0
        assert caso["administrador_judicial"]
        assert isinstance(caso["marcos"], list)
        assert len(caso["marcos"]) > 0
        for marco in caso["marcos"]:
            assert marco["data_evento"]
            assert marco["tipo_evento"]
            assert marco["titulo"]


def test_repositorio_marcos_e_dashboard() -> None:
    """Testa métodos de inserção de marcos e consultas analíticas para o dashboard."""
    banco = BancoDados(":memory:")
    banco.inicializar_schema()

    empresa_id = banco.salvar_empresa(
        slug="caso-teste-rj",
        nome_razao_social="Caso Teste S.A.",
        cnpj="00.123.456/0001-99",
        setor="Agronegócio",
    )

    processo_id = banco.salvar_processo(
        empresa_id=empresa_id,
        slug="proc-caso-teste-rj",
        numero_cnj="1234567-89.2024.8.26.0100",
        vara_comarca="1ª Vara de Falências / SP",
        administrador_judicial="AJ Teste & Associados",
        tipo_processo="recuperacao_judicial",
        valor_causa=500000000.0,
        tribunal="TJSP",
        status_processual="Plano Homologado",
        data_distribuicao="2024-01-10",
    )

    # Inserir marcos
    banco.salvar_marco_processual(
        processo_id=processo_id,
        data_evento="2024-01-10",
        tipo_evento="PETICAO_INICIAL",
        titulo="Ajuizamento da Petição Inicial",
        autor="RECUPERANDA",
        descricao="Distribuição com passivo de 500M",
    )
    banco.salvar_marco_processual(
        processo_id=processo_id,
        data_evento="2024-01-20",
        tipo_evento="DECISAO_PROCESSAMENTO",
        titulo="Deferimento do Processamento",
        autor="JUIZO",
    )
    banco.salvar_marco_processual(
        processo_id=processo_id,
        data_evento="2024-05-15",
        tipo_evento="RMA_AJ",
        titulo="Relatório Mensal de Atividades",
        autor="AJ",
        descricao="Fiscalização de caixa e faturamento",
    )

    # Testar linha do tempo
    timeline = banco.obter_linha_do_tempo(processo_id)
    assert len(timeline) == 3
    assert timeline[0]["tipo_evento"] == "PETICAO_INICIAL"
    assert timeline[1]["tipo_evento"] == "DECISAO_PROCESSAMENTO"
    assert timeline[2]["tipo_evento"] == "RMA_AJ"

    # Testar ranking top processos
    top = banco.obter_top_processos(limite=10)
    assert len(top) == 1
    assert top[0]["nome_razao_social"] == "Caso Teste S.A."
    assert top[0]["valor_causa"] == 500000000.0
    assert top[0]["total_marcos"] == 3

    # Testar filtros
    top_tjsp = banco.obter_top_processos(tribunal="TJSP")
    assert len(top_tjsp) == 1

    top_tjmg = banco.obter_top_processos(tribunal="TJMG")
    assert len(top_tjmg) == 0

    top_busca = banco.obter_top_processos(busca="Caso Teste")
    assert len(top_busca) == 1

    # Testar dossiê consolidado
    dossie = banco.obter_dossie_processo(processo_id)
    assert dossie is not None
    assert dossie["nome_razao_social"] == "Caso Teste S.A."
    assert len(dossie["linha_do_tempo"]) == 3
    assert dossie["resumo_credores"]["total_credores"] == 0
