"""
Testes unitários para o Módulo de Linha do Tempo Dupla (Processo Judicial + Regulatório CVM).
"""

from __future__ import annotations

import plotly.graph_objects as go
import pytest

from src.dados.links_util import obter_acao_externa_marco
from src.visualizacao.timeline_dupla import (
    CORES_EMISSORES,
    ORDEM_FASES,
    classificar_fase_macro,
    construir_figura_timeline_dupla,
    detectar_correlacoes,
    extrair_fases_processo,
    normalizar_emissor,
)


@pytest.fixture
def marcos_exemplo():
    return [
        {
            "id": 1,
            "processo_id": 10,
            "data_evento": "2020-01-10",
            "tipo_evento": "PETICAO_INICIAL",
            "titulo": "Ajuizamento do Pedido de RJ",
            "descricao": "Distribuição inicial",
            "autor": "RECUPERANDA",
            "url_documento": None,
        },
        {
            "id": 2,
            "processo_id": 10,
            "data_evento": "2020-01-12",
            "tipo_evento": "FATO_RELEVANTE_CVM",
            "titulo": "Fato Relevante: Pedido de RJ",
            "descricao": "Comunicado ao mercado sobre o pedido de RJ",
            "autor": "CVM",
            "url_documento": None,
        },
        {
            "id": 3,
            "processo_id": 10,
            "data_evento": "2020-01-20",
            "tipo_evento": "DECISAO_PROCESSAMENTO",
            "titulo": "Deferimento do Processamento",
            "descricao": "Juízo defere processamento da recuperação judicial",
            "autor": "JUIZO",
            "url_documento": None,
        },
        {
            "id": 4,
            "processo_id": 10,
            "data_evento": "2020-04-15",
            "tipo_evento": "PRJ",
            "titulo": "Apresentação do Plano de Recuperação",
            "descricao": "Protocolo do PRJ nos autos",
            "autor": "RECUPERANDA",
            "url_documento": None,
        },
        {
            "id": 5,
            "processo_id": 10,
            "data_evento": "2020-08-10",
            "tipo_evento": "AGC",
            "titulo": "Aprovação em Assembleia Geral",
            "descricao": "Credores aprovam o plano",
            "autor": "AJ",
            "url_documento": None,
        },
        {
            "id": 6,
            "processo_id": 10,
            "data_evento": "2020-09-01",
            "tipo_evento": "HOMOLOGACAO",
            "titulo": "Sentença de Homologação do Plano",
            "descricao": "Homologação do plano com concessão da RJ",
            "autor": "JUIZO",
            "url_documento": None,
        },
        {
            "id": 7,
            "processo_id": 10,
            "data_evento": "2021-02-15",
            "tipo_evento": "RMA_AJ",
            "titulo": "Relatório Mensal de Atividades",
            "descricao": "RMA do mês de janeiro de 2021",
            "autor": "AJ",
            "url_documento": None,
        },
        {
            "id": 8,
            "processo_id": 10,
            "data_evento": "2021-02-18",
            "tipo_evento": "COMUNICADO_MERCADO_CVM",
            "titulo": "Comunicado ao Mercado: Publicação de RMA",
            "descricao": "Aviso aos acionistas sobre o RMA",
            "autor": "CVM",
            "url_documento": None,
        },
    ]


def test_normalizar_emissor():
    assert normalizar_emissor("JUIZO", "DECISAO") == "JUIZO"
    assert normalizar_emissor("CVM", "FATO_RELEVANTE") == "CVM"
    assert normalizar_emissor("PARTE", "FATO_RELEVANTE_CVM") == "CVM"
    assert normalizar_emissor("AJ", "RMA_AJ") == "AJ"
    assert normalizar_emissor("RECUPERANDA", "PRJ") == "RECUPERANDA"
    assert normalizar_emissor("MP", "PARECER") == "MP"
    assert normalizar_emissor("CREDOR", "HABILITACAO") == "OUTROS"


def test_classificar_fase_macro(marcos_exemplo):
    m_dist = marcos_exemplo[0]
    m_def = marcos_exemplo[2]
    m_prj = marcos_exemplo[3]
    m_agc = marcos_exemplo[4]
    m_hom = marcos_exemplo[5]
    m_pos = marcos_exemplo[6]

    assert classificar_fase_macro(m_dist) == "Distribuição"
    assert classificar_fase_macro(m_def) == "Deferimento"
    assert classificar_fase_macro(m_prj) == "Plano apresentado"
    assert classificar_fase_macro(m_agc) == "Assembleias"
    assert classificar_fase_macro(m_hom) == "Homologação"
    assert classificar_fase_macro(m_pos, data_homologacao="2020-09-01") == "Pós-homologação"


def test_extrair_fases_processo(marcos_exemplo):
    fases = extrair_fases_processo(marcos_exemplo)

    assert "Distribuição" in fases
    assert "Deferimento" in fases
    assert "Plano apresentado" in fases
    assert "Assembleias" in fases
    assert "Homologação" in fases
    assert "Pós-homologação" in fases

    assert fases["Distribuição"]["total"] >= 1
    assert fases["Homologação"]["total"] == 1
    assert fases["Pós-homologação"]["total"] == 2


def test_detectar_correlacoes(marcos_exemplo):
    # m[0] (Recuperanda 2020-01-10) e m[1] (CVM 2020-01-12) -> diff = 2 dias <= 5 dias!
    # m[6] (AJ 2021-02-15) e m[7] (CVM 2021-02-18) -> diff = 3 dias <= 5 dias!
    marcos_jud = [m for m in marcos_exemplo if m["autor"] != "CVM"]
    marcos_cvm = [m for m in marcos_exemplo if m["autor"] == "CVM"]

    correlacoes = detectar_correlacoes(marcos_jud, marcos_cvm, limiar_dias=5)
    assert len(correlacoes) == 2
    assert correlacoes[0]["diferenca_dias"] == 2
    assert correlacoes[1]["diferenca_dias"] == 3


def test_construir_figura_timeline_dupla(marcos_exemplo):
    fases = extrair_fases_processo(marcos_exemplo)
    fig = construir_figura_timeline_dupla(
        marcos=marcos_exemplo,
        fases_map=fases,
        mostrar_correlacoes=True,
        limiar_dias=5,
    )

    assert isinstance(fig, go.Figure)
    # Deve conter traços para correlações e para os emissores
    assert len(fig.data) >= 3
    # Deve conter rangeslider configurado no eixo X
    assert fig.layout.xaxis.rangeslider.visible is True
    # Eixo Y deve ter 2 níveis fixados (0 e 1)
    assert list(fig.layout.yaxis.tickvals) == [0, 1]


def test_obter_acao_externa_marco():
    dossie = {
        "numero_cnj": "1057756-77.2019.8.26.0100",
        "tribunal": "TJSP",
        "empresa_slug": "oi",
    }

    # Teste para marco da CVM
    marco_cvm = {"autor": "CVM", "tipo_evento": "FATO_RELEVANTE_CVM", "url_documento": ""}
    acao_cvm = obter_acao_externa_marco(marco_cvm, dossie)
    assert acao_cvm["label"] == "Ver na CVM ↗"
    assert "rad.cvm.gov.br" in acao_cvm["url"]

    # Teste para marco do Juízo
    marco_juizo = {"autor": "JUIZO", "tipo_evento": "DECISAO", "url_documento": ""}
    acao_juizo = obter_acao_externa_marco(marco_juizo, dossie)
    assert "Consultar no TJSP" in acao_juizo["label"]
    assert "esaj.tjsp.jus.br" in acao_juizo["url"]

    # Teste para marco do AJ
    marco_aj = {"autor": "AJ", "tipo_evento": "RMA_AJ", "url_documento": ""}
    acao_aj = obter_acao_externa_marco(marco_aj, dossie)
    assert "Portal do AJ" in acao_aj["label"]
    assert "recjud.com.br" in acao_aj["url"]
