"""
Testes unitários e de integração da camada de Banco de Dados Relacional (SQLite).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.banco.loader import LoaderDados
from src.banco.repositorio import BancoDados


@pytest.fixture
def banco_memoria() -> BancoDados:
    """Cria um banco SQLite isolado em memória para testes rápidos."""
    banco = BancoDados(":memory:")
    banco.inicializar_schema()
    return banco


class TestSchemaEConexao:
    """Validação de integridade do DDL e conexão com SQLite."""

    def test_inicializacao_tabelas_e_indices(self, banco_memoria: BancoDados) -> None:
        conn = banco_memoria.conectar()
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;"
        )
        tabelas = [row["name"] for row in cur.fetchall()]

        assert "empresas" in tabelas
        assert "processos" in tabelas
        assert "documentos" in tabelas
        assert "credores" in tabelas

        # Checar índices essenciais
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' ORDER BY name;"
        )
        indices = [row["name"] for row in cur.fetchall()]
        assert "idx_credores_documento_limpo" in indices
        assert "idx_credores_valor" in indices

    def test_context_manager(self) -> None:
        with BancoDados(":memory:") as db:
            db.inicializar_schema()
            conn = db.conectar()
            assert conn is not None
        assert db._conn is None


class TestOperacoesCRUD:
    """Testes de inserção, atualização e relacionamentos de chave estrangeira."""

    def test_salvar_empresa_e_idempotencia(self, banco_memoria: BancoDados) -> None:
        emp_id1 = banco_memoria.salvar_empresa(
            slug="oi",
            nome_razao_social="Oi S.A. - Em Recuperação Judicial",
            cnpj="76.535.764/0001-43",
            setor="Telecomunicações",
            origem_fonte="cvm",
        )
        assert emp_id1 > 0

        # Atualização com mesmo slug deve atualizar e manter o mesmo ID
        emp_id2 = banco_memoria.salvar_empresa(
            slug="oi",
            nome_razao_social="Oi S.A.",
            cnpj="76.535.764/0001-43",
            setor="Telecomunicações e TI",
        )
        assert emp_id1 == emp_id2

        empresa = banco_memoria.obter_empresa_por_slug("oi")
        assert empresa is not None
        assert empresa["nome_razao_social"] == "Oi S.A."
        assert empresa["setor"] == "Telecomunicações e TI"

    def test_salvar_processo_e_documento(self, banco_memoria: BancoDados) -> None:
        emp_id = banco_memoria.salvar_empresa(
            slug="atlas",
            nome_razao_social="Atlas Agroindustrial Ltda",
        )
        proc_id = banco_memoria.salvar_processo(
            empresa_id=emp_id,
            slug="proc-atlas-re",
            numero_cnj="1000000-00.2024.8.26.0100",
            vara_comarca="1ª Vara de Falências e Recuperações SP",
            administrador_judicial="AJ Ruiz",
            tipo_processo="recuperacao_extrajudicial",
        )
        assert proc_id > 0

        doc_id = banco_memoria.salvar_documento(
            empresa_id=emp_id,
            processo_id=proc_id,
            titulo="Relação de Credores.pdf",
            categoria="QGC",
            sha256="abc123hash",
            total_paginas=111,
        )
        assert doc_id > 0

        stats = banco_memoria.obter_estatisticas_gerais()
        assert stats["total_empresas"] == 1
        assert stats["total_processos"] == 1
        assert stats["total_documentos"] == 1


class TestConsultasAnaliticasECredores:
    """Testes de inserção em lote de credores e consultas agregadas financeiras."""

    @pytest.fixture
    def banco_com_dados(self, banco_memoria: BancoDados) -> BancoDados:
        emp_id = banco_memoria.salvar_empresa(
            slug="empresa-teste",
            nome_razao_social="Empresa Teste S.A.",
        )
        proc_id = banco_memoria.salvar_processo(
            empresa_id=emp_id,
            slug="proc-teste",
            numero_cnj="0001234-56.2024.8.26.0100",
        )
        doc_id = banco_memoria.salvar_documento(
            empresa_id=emp_id,
            processo_id=proc_id,
            titulo="QGC Consolidado",
            categoria="QGC",
        )

        credores_amostra = [
            {
                "nome": "Banco Alfa S.A.",
                "documento": "11.111.111/0001-11",
                "documento_limpo": "11111111000111",
                "tipo_documento": "CNPJ",
                "classe": "III - Quirografário",
                "valor": 1500000.0,
                "cidade": "São Paulo",
                "uf": "SP",
                "pagina": 1,
            },
            {
                "nome": "João Trabalhador",
                "documento": "222.222.222-22",
                "documento_limpo": "22222222222",
                "tipo_documento": "CPF",
                "classe": "I - Trabalhista",
                "valor": 45000.0,
                "cidade": "Campinas",
                "uf": "SP",
                "pagina": 2,
            },
            {
                "nome": "Fornecedor Beta Ltda",
                "documento": "33.333.333/0001-33",
                "documento_limpo": "33333333000133",
                "tipo_documento": "CNPJ",
                "classe": "III - Quirografário",
                "valor": 750000.0,
                "cidade": "Ribeirão Preto",
                "uf": "SP",
                "pagina": 3,
            },
            {
                "nome": "Gráfica Gama ME",
                "documento": "44.444.444/0001-44",
                "documento_limpo": "44444444000144",
                "tipo_documento": "CNPJ",
                "classe": "IV - ME/EPP",
                "valor": 12000.0,
                "cidade": "Santos",
                "uf": "SP",
                "pagina": 4,
            },
        ]

        banco_memoria.salvar_credores_lote(
            credores=credores_amostra,
            processo_id=proc_id,
            documento_id=doc_id,
        )
        return banco_memoria

    def test_obter_resumo_passivo_empresa(self, banco_com_dados: BancoDados) -> None:
        resumo = banco_com_dados.obter_resumo_passivo_empresa("empresa-teste")

        assert resumo["total_credores"] == 4
        assert resumo["valor_total_apurado"] == 2307000.0
        assert resumo["totais_por_classe"]["III - Quirografário"] == 2250000.0
        assert resumo["totais_por_classe"]["I - Trabalhista"] == 45000.0
        assert resumo["totais_por_classe"]["IV - ME/EPP"] == 12000.0
        assert resumo["quantidade_por_classe"]["III - Quirografário"] == 2

    def test_buscar_credores_por_filtros(self, banco_com_dados: BancoDados) -> None:
        # Busca por nome
        banco_res = banco_com_dados.buscar_credores(nome="Alfa")
        assert len(banco_res) == 1
        assert banco_res[0]["credor_nome"] == "Banco Alfa S.A."
        assert banco_res[0]["valor_original"] == 1500000.0

        # Busca por documento limpo
        cpf_res = banco_com_dados.buscar_credores(documento="22222222222")
        assert len(cpf_res) == 1
        assert cpf_res[0]["credor_nome"] == "João Trabalhador"

        # Busca por classe
        quirog_res = banco_com_dados.buscar_credores(classe="Quirografário")
        assert len(quirog_res) == 2

        # Busca por valor mínimo (maiores que R$ 100k)
        grandes_res = banco_com_dados.buscar_credores(valor_minimo=100000.0)
        assert len(grandes_res) == 2
        assert grandes_res[0]["valor_original"] == 1500000.0
        assert grandes_res[1]["valor_original"] == 750000.0

    def test_ranking_maiores_credores(self, banco_com_dados: BancoDados) -> None:
        ranking = banco_com_dados.ranking_maiores_credores(limite=2)
        assert len(ranking) == 2
        assert ranking[0]["credor_nome"] == "Banco Alfa S.A."
        assert ranking[1]["credor_nome"] == "Fornecedor Beta Ltda"


class TestLoaderDados:
    """Testes de sincronização automática a partir de arquivos JSON."""

    def test_carregar_manifesto_arquivo(self, tmp_path: Path, banco_memoria: BancoDados) -> None:
        # Criar manifesto sintético
        pasta_empresa = tmp_path / "empresa_x"
        pasta_empresa.mkdir()
        manifesto_path = pasta_empresa / "ingestion_manifest.json"

        dados_manifesto = {
            "fonte": "aj_exm",
            "empresa": "empresa_x",
            "arquivos": {
                "doc1.pdf": {
                    "status": "sucesso",
                    "categoria": "PRJ",
                    "caminho": "data/raw/empresa_x/PRJ/doc1.pdf",
                    "sha256": "hash_doc1",
                    "bytes": 54321,
                },
                "doc2.pdf": {
                    "status": "sucesso",
                    "categoria": "EDITAL",
                    "caminho": "data/raw/empresa_x/EDITAL/doc2.pdf",
                    "sha256": "hash_doc2",
                    "bytes": 12345,
                },
            },
        }
        with open(manifesto_path, "w", encoding="utf-8") as f:
            json.dump(dados_manifesto, f)

        loader = LoaderDados(banco_memoria)
        res = loader.carregar_manifesto_arquivo(manifesto_path)

        assert res["documentos"] == 2

        stats = banco_memoria.obter_estatisticas_gerais()
        assert stats["total_empresas"] == 1
        assert stats["total_processos"] == 1
        assert stats["total_documentos"] == 2

    def test_carregar_qgc_arquivo(self, tmp_path: Path, banco_memoria: BancoDados) -> None:
        pasta_qgc = tmp_path / "atlas" / "qgc"
        pasta_qgc.mkdir(parents=True)
        qgc_path = pasta_qgc / "relacao_credores.json"

        dados_qgc = {
            "nome_arquivo": "relacao_credores.pdf",
            "total_credores": 2,
            "valor_total_apurado": 120000.0,
            "credores": [
                {
                    "nome": "Credor 1",
                    "documento": "11.111.111/0001-11",
                    "documento_limpo": "11111111000111",
                    "tipo_documento": "CNPJ",
                    "classe": "I - Trabalhista",
                    "valor": 20000.0,
                    "cidade": "Marília",
                    "uf": "SP",
                    "pagina": 1,
                },
                {
                    "nome": "Credor 2",
                    "documento": "22.222.222/0001-22",
                    "documento_limpo": "22222222000122",
                    "tipo_documento": "CNPJ",
                    "classe": "III - Quirografário",
                    "valor": 100000.0,
                    "cidade": "Bauru",
                    "uf": "SP",
                    "pagina": 2,
                },
            ],
        }
        with open(qgc_path, "w", encoding="utf-8") as f:
            json.dump(dados_qgc, f)

        loader = LoaderDados(banco_memoria)
        total_salvos = loader.carregar_qgc_arquivo(qgc_path, slug_empresa="atlas")

        assert total_salvos == 2

        stats = banco_memoria.obter_estatisticas_gerais()
        assert stats["total_credores"] == 2

        resumo = banco_memoria.obter_resumo_passivo_empresa("atlas")
        assert resumo["total_credores"] == 2
        assert resumo["valor_total_apurado"] == 120000.0
