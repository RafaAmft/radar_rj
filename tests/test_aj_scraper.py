"""
Testes unitários para o módulo de scrapers de Administradores Judiciais (AJs).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import responses

from src.ingestao.aj.base import DocumentoInfo, ProcessoInfo, ScraperAJBase
from src.ingestao.aj.exm import ScraperEXM, executar


class TestClassificacaoDocumento:
    """Valida a categorização jurídica automática das peças processuais."""

    @pytest.mark.parametrize(
        "titulo,esperado",
        [
            ("Plano de Recuperação Judicial Consolidado", "PRJ"),
            ("PRJ com Modificativo e Anexos", "PRJ"),
            ("Primeiro Aditivo ao Plano de Recuperação", "PRJ"),
            ("Modificativo ao Plano Homologado", "PRJ"),
            ("Relação de Credores - Art. 7º, § 2º da Lei 11.101", "QGC"),
            ("Quadro Geral de Credores - Consolidado", "QGC"),
            ("Segunda Relação de Credores e Habilitações", "QGC"),
            ("Edital de Credores do Administrador Judicial", "QGC"),
            ("Ata de Assembleia Geral de Credores - 1ª Convocação", "AGC"),
            ("Convocação de Assembleia Geral de Credores", "AGC"),
            ("Ata da AGC com Deliberação do Plano", "AGC"),
            ("Relatório Mensal de Atividades - RMA Junho/2024", "RMA"),
            ("RMA da Recuperanda - Maio de 2024", "RMA"),
            ("Relatório de Atividades da Recuperanda", "RMA"),
            ("Edital de Leilão de Imóveis e Bens", "EDITAL"),
            ("Alienação de Ativos da UPI", "EDITAL"),
            ("Segunda Praça e Leilão Judicial Eletrônico", "EDITAL"),
            ("Petição Inicial e Documentos Societários", "OUTROS"),
            ("Decisão de Deferimento do Processamento", "OUTROS"),
        ],
    )
    def test_classificar_documento(self, titulo: str, esperado: str):
        cat = ScraperAJBase.classificar_documento(titulo)
        assert cat == esperado


class TestScraperEXM:
    """Testes para o scraper da EXM Partners."""

    HTML_LISTA_MOCK = """
    <html>
      <body>
        <div class="lista">
          <a href="processos-em-andamento/empresa-alfa-sa/">Empresa Alfa S.A.</a>
          <a href="processos-em-andamento/empresa-alfa-sa/">1ª Vara Cível de São Paulo</a>
          <a href="processos-em-andamento/empresa-alfa-sa/">1000000-00.2023.8.26.0100</a>

          <a href="processos-em-andamento/beta-agroindustrial-ltda/">Beta Agroindustrial Ltda</a>
          <a href="processos-em-andamento/beta-agroindustrial-ltda/">Vara Única de Sorriso/MT</a>
          <a href="processos-em-andamento/beta-agroindustrial-ltda/">2000000-00.2023.8.11.0040</a>
        </div>
      </body>
    </html>
    """

    HTML_DETALHE_MOCK = """
    <html>
      <head><title>Processo Alfa</title></head>
      <body>
        <h1>Empresa Alfa S.A.</h1>
        <button onclick="carregar('processos-mostra-iframe.php?id=101')">Planos</button>
        <button onclick="carregar('processos-mostra-iframe.php?id=102')">Credores</button>
        <a href="arquivos/edital_leilao.pdf">Edital de Leilão</a>
      </body>
    </html>
    """

    HTML_IFRAME_101_MOCK = """
    <html>
      <body>
        <h2>Plano de Recuperação Judicial</h2>
        <ul>
          <li><a href="arquivos/plano_apresentado.pdf">Plano de Recuperação Consolidado</a></li>
        </ul>
      </body>
    </html>
    """

    HTML_IFRAME_102_MOCK = """
    <html>
      <body>
        <h2>Relação de Credores</h2>
        <ul>
          <li><a href="arquivos/qgc_art7.pdf">Quadro Geral de Credores Art 7</a></li>
        </ul>
      </body>
    </html>
    """

    @responses.activate
    def test_listar_processos(self):
        config = {
            "nome": "EXM Partners",
            "urls": {
                "base": "https://www.exmpartners.com.br",
                "lista_processos": "https://www.exmpartners.com.br/servicos/administracao-judicial",
            },
            "delay_entre_downloads": 0.0,
            "saida_dir": "aj/exm",
        }
        responses.add(
            responses.GET,
            "https://www.exmpartners.com.br/servicos/administracao-judicial",
            body=self.HTML_LISTA_MOCK,
            status=200,
        )

        scraper = ScraperEXM(config)
        processos = scraper.listar_processos()

        assert len(processos) == 2
        p1, p2 = processos[0], processos[1]

        assert p1.slug == "empresa-alfa-sa"
        assert p1.nome_empresa == "Empresa Alfa S.A."
        assert p1.vara == "1ª Vara Cível de São Paulo"
        assert p1.numero_cnj == "1000000-00.2023.8.26.0100"
        assert p1.url_detalhe == "https://www.exmpartners.com.br/processos-em-andamento/empresa-alfa-sa/"

        assert p2.slug == "beta-agroindustrial-ltda"
        assert p2.nome_empresa == "Beta Agroindustrial Ltda"

    @responses.activate
    def test_obter_documentos_processo(self):
        config = {
            "nome": "EXM Partners",
            "urls": {
                "base": "https://www.exmpartners.com.br",
                "lista_processos": "https://www.exmpartners.com.br/servicos/administracao-judicial",
            },
            "delay_entre_downloads": 0.0,
            "saida_dir": "aj/exm",
        }
        processo = ProcessoInfo(
            slug="empresa-alfa-sa",
            nome_empresa="Empresa Alfa S.A.",
            vara="1ª Vara Cível",
            numero_cnj="1000000-00.2023.8.26.0100",
            url_detalhe="https://www.exmpartners.com.br/processos-em-andamento/empresa-alfa-sa/",
        )

        responses.add(
            responses.GET,
            processo.url_detalhe,
            body=self.HTML_DETALHE_MOCK,
            status=200,
        )
        responses.add(
            responses.GET,
            "https://www.exmpartners.com.br/processos-mostra-iframe.php?id=101",
            body=self.HTML_IFRAME_101_MOCK,
            status=200,
        )
        responses.add(
            responses.GET,
            "https://www.exmpartners.com.br/processos-mostra-iframe.php?id=102",
            body=self.HTML_IFRAME_102_MOCK,
            status=200,
        )

        scraper = ScraperEXM(config)
        docs = scraper.obter_documentos_processo(processo)

        assert len(docs) == 3
        categorias = {d.categoria for d in docs}
        assert "PRJ" in categorias
        assert "QGC" in categorias
        assert "EDITAL" in categorias

        doc_prj = next(d for d in docs if d.categoria == "PRJ")
        assert doc_prj.nome_arquivo == "plano_apresentado.pdf"
        assert doc_prj.url_download == "https://www.exmpartners.com.br/arquivos/plano_apresentado.pdf"

    @responses.activate
    def test_baixar_processo_idempotencia_e_manifesto(self, tmp_path: Path):
        config = {
            "nome": "EXM Partners",
            "urls": {
                "base": "https://www.exmpartners.com.br",
                "lista_processos": "https://www.exmpartners.com.br/servicos/administracao-judicial",
            },
            "delay_entre_downloads": 0.0,
            "saida_dir": "aj/exm",
        }
        scraper = ScraperEXM(config)
        scraper.dir_saida_base = tmp_path

        processo = ProcessoInfo(
            slug="teste-empresa",
            nome_empresa="Empresa Teste",
            vara="Vara Cível",
            numero_cnj="12345",
            url_detalhe="https://www.exmpartners.com.br/processo-teste",
        )

        pdf_fake = b"%PDF-1.4 fake pdf content for testing"
        url_pdf = "https://www.exmpartners.com.br/arquivos/plano.pdf"

        responses.add(
            responses.GET,
            processo.url_detalhe,
            body="""<a href="arquivos/plano.pdf">Plano de Recuperação Judicial</a>""",
            status=200,
        )
        responses.add(
            responses.GET,
            url_pdf,
            body=pdf_fake,
            status=200,
        )

        # 1ª execução: baixa e registra no manifesto
        total = scraper.baixar_processo(processo)
        assert total == 1

        arquivo_salvo = tmp_path / "teste-empresa" / "PRJ" / "plano.pdf"
        assert arquivo_salvo.exists()
        assert arquivo_salvo.read_bytes() == pdf_fake

        manifesto_file = tmp_path / "teste-empresa" / "ingestion_manifest.json"
        assert manifesto_file.exists()
        with open(manifesto_file, encoding="utf-8") as f:
            dados_manifesto = json.load(f)
        assert any(e["arquivo_local"] == "PRJ/plano.pdf" for e in dados_manifesto["entradas"])

        # 2ª execução: idempotência deve pular download
        total_reexec = scraper.baixar_processo(processo)
        assert total_reexec == 0

    @patch("src.ingestao.aj.exm.ScraperEXM")
    def test_executar_com_filtros_e_dry_run(self, mock_scraper_cls):
        mock_instance = MagicMock()
        mock_scraper_cls.return_value = mock_instance

        p1 = ProcessoInfo("alfa-agro", "Alfa Agro Ltda", "Vara 1", "001", "http://ex1")
        p2 = ProcessoInfo("beta-metalurgica", "Beta Metal", "Vara 2", "002", "http://ex2")
        mock_instance.listar_processos.return_value = [p1, p2]
        mock_instance.baixar_processo.return_value = 5

        # Filtro por slug
        res = executar(slugs_empresa=["alfa"], dry_run=True)

        assert "alfa-agro" in res
        assert "beta-metalurgica" not in res
        mock_instance.baixar_processo.assert_called_once_with(
            p1,
            categorias_filtro=None,
            limite_docs=None,
            dry_run=True,
        )
