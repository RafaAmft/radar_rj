"""
Testes unitários do Scraper da Brizola e Japur Administração Judicial.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.ingestao.aj.base import ProcessoInfo
from src.ingestao.aj.brizola import ScraperBrizola


@pytest.fixture
def config_brizola_mock() -> dict:
    return {
        "nome": "Brizola e Japur Mock",
        "slug": "aj_brizola",
        "tipo": "administrador_judicial",
        "urls": {
            "base": "https://brizolaejapur.com.br",
            "api_clients": "https://api.brizolaejapur.com.br/api/clients",
            "api_client_detail": "https://api.brizolaejapur.com.br/api/clients/{id}",
        },
        "delay_entre_requisicoes": 0.0,
    }


class TestScraperBrizola:
    """Testes do scraper da Brizola e Japur."""

    def test_listar_processos_com_paginacao(self, config_brizola_mock: dict) -> None:
        scraper = ScraperBrizola(config=config_brizola_mock)

        # Mock da API da Brizola retornando 2 processos
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "content": {
                "paging": {"page": 1, "perPage": 50, "lastPage": 1, "total": 2},
                "data": [
                    {
                        "id": 101,
                        "name": "Cooperativa Agropecuária Sul Ltda",
                        "process_number": "5001234-56.2023.8.21.0001",
                        "type": 1,
                        "district": {"name": "Porto Alegre"},
                    },
                    {
                        "id": 102,
                        "name": "Indústria Metalúrgica Catarinense S.A.",
                        "process_number": "0009876-54.2022.8.24.0020",
                        "type": 2,
                        "district": {"name": "Criciúma"},
                    },
                ],
            }
        }

        with patch("requests.get", return_value=mock_resp):
            processos = scraper.listar_processos(max_paginas=1)

        assert len(processos) == 2

        p1 = processos[0]
        assert p1.nome_empresa == "Cooperativa Agropecuária Sul Ltda"
        assert p1.numero_cnj == "5001234-56.2023.8.21.0001"
        assert p1.vara == "Porto Alegre"
        assert p1.tipo_processo == "recuperacao_judicial"
        assert "101" in p1.url_detalhe

        p2 = processos[1]
        assert p2.nome_empresa == "Indústria Metalúrgica Catarinense S.A."
        assert p2.tipo_processo == "falencia"
        assert p2.vara == "Criciúma"

    def test_obter_documentos_processo(self, config_brizola_mock: dict) -> None:
        scraper = ScraperBrizola(config=config_brizola_mock)
        processo = ProcessoInfo(
            slug="cooperativa-agropecuaria-101",
            nome_empresa="Cooperativa Agropecuária Sul Ltda",
            vara="Porto Alegre",
            numero_cnj="5001234-56.2023.8.21.0001",
            url_detalhe="https://api.brizolaejapur.com.br/api/clients/101",
        )

        # Mock da API de detalhe com peças judiciais
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "content": {
                "id": 101,
                "name": "Cooperativa Agropecuária Sul Ltda",
                "documents": [
                    {
                        "id": 1,
                        "name": "Petição Inicial da Recuperação Judicial",
                        "doc_url": "https://brizolaejapur-docs.nyc3.digitaloceanspaces.com/doc1.pdf",
                    },
                    {
                        "id": 2,
                        "name": "Quadro Geral de Credores - Edital Art. 52",
                        "doc_url": "https://brizolaejapur-docs.nyc3.digitaloceanspaces.com/qgc.pdf",
                    },
                    {
                        "id": 3,
                        "name": "Plano de Recuperação Judicial (PRJ)",
                        "doc_url": "https://brizolaejapur-docs.nyc3.digitaloceanspaces.com/prj.pdf",
                    },
                    {
                        "id": 4,
                        "name": "Relatório Mensal de Atividades - Junho 2024",
                        "doc_url": "https://brizolaejapur-docs.nyc3.digitaloceanspaces.com/rma.pdf",
                    },
                ],
            }
        }

        with patch("requests.get", return_value=mock_resp):
            docs = scraper.obter_documentos_processo(processo)

        assert len(docs) == 4

        categorias = {d.titulo: d.categoria for d in docs}
        assert categorias["Petição Inicial da Recuperação Judicial"] == "OUTROS"
        assert categorias["Quadro Geral de Credores - Edital Art. 52"] == "QGC"
        assert categorias["Plano de Recuperação Judicial (PRJ)"] == "PRJ"
        assert categorias["Relatório Mensal de Atividades - Junho 2024"] == "RMA"

    def test_tratar_erro_api_graciosamente(self, config_brizola_mock: dict) -> None:
        scraper = ScraperBrizola(config=config_brizola_mock)
        with patch("requests.get", side_effect=Exception("Timeout na API")):
            processos = scraper.listar_processos(max_paginas=1)
            assert processos == []

            docs = scraper.obter_documentos_processo(
                ProcessoInfo(
                    slug="proc-erro",
                    nome_empresa="Erro Ltda",
                    vara="",
                    numero_cnj="",
                    url_detalhe="https://api.brizolaejapur.com.br/api/clients/999",
                )
            )
            assert docs == []
