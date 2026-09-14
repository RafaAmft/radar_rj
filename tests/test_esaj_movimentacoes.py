"""
Testes unitários e de integração para o extrator de movimentações do e-SAJ com filtro de relevância.
"""

from __future__ import annotations

from src.ingestao.tribunais.esaj import ConsultorEsaj


def test_classificar_movimentacao_ruidos():
    consultor = ConsultorEsaj()

    # Certidões e atos puramente cartorários devem ser descartados
    relevante, tipo, autor = consultor.classificar_movimentacao(
        "Certidão de Remessa da Intimação Para o Portal Eletrônico Expedida",
        "Remessa eletrônica ao portal",
    )
    assert relevante is False
    assert tipo == "RUIDO"

    relevante, tipo, autor = consultor.classificar_movimentacao(
        "Ato Ordinatório - Não Publicável",
        "Ato interno sem publicação",
    )
    assert relevante is False


def test_classificar_movimentacao_marcos_estrategicos():
    consultor = ConsultorEsaj()

    # Decisão / Despacho relevante
    relevante, tipo, autor = consultor.classificar_movimentacao(
        "Decisão Interlocutória",
        "Vistos. Defiro o processamento da recuperação judicial...",
    )
    assert relevante is True
    assert tipo == "DECISAO_PROCESSAMENTO"
    assert autor == "JUIZO"

    # Homologação
    relevante, tipo, autor = consultor.classificar_movimentacao(
        "Sentença",
        "Homologado o plano de recuperação judicial aprovado em assembleia.",
    )
    assert relevante is True
    assert tipo == "HOMOLOGACAO"
    assert autor == "JUIZO"

    # Relatório Mensal do AJ
    relevante, tipo, autor = consultor.classificar_movimentacao(
        "Petição Juntada",
        "Apresentação do Relatório Mensal de Atividades (RMA) pelo Administrador Judicial.",
    )
    assert relevante is True
    assert tipo == "RMA_AJ"
    assert autor == "AJ"

    # Assembleia Geral de Credores
    relevante, tipo, autor = consultor.classificar_movimentacao(
        "Petição Juntada",
        "Juntada da Ata da Assembleia Geral de Credores (AGC).",
    )
    assert relevante is True
    assert tipo == "AGC"
    assert autor == "AJ"

    # Manifestação do MP
    relevante, tipo, autor = consultor.classificar_movimentacao(
        "Petição Juntada",
        "Tipo da Petição: Manifestação do MP.",
    )
    assert relevante is True
    assert tipo == "MANIFESTACAO_MP"
    assert autor == "MP"


def test_extrair_codigo_processo():
    consultor = ConsultorEsaj()

    url = "https://esaj.tjsp.jus.br/cpopg/show.do?processo.codigo=2S0012IW70000&processo.foro=100"
    assert consultor.extrair_codigo_processo("", url) == "2S0012IW70000"

    html = "var codigoProcesso = '2S0012IW70000';"
    assert consultor.extrair_codigo_processo(html, "") == "2S0012IW70000"
