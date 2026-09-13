"""
Testes unitários para o motor de Cruzamento e Reconciliação Inteligente de Fontes.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.banco.repositorio import BancoDados
from src.cruzamento.reconciliador import (
    ReconciliadorFontes,
    calcular_similaridade,
    normalizar_nome_empresa,
)


class TestNormalizacaoESimilaridade:
    """Testes para as funções utilitárias de normalização e similaridade léxica."""

    def test_normalizar_nome_empresa_remove_societarios(self) -> None:
        assert normalizar_nome_empresa("Atlas Agroindustrial Ltda.") == "atlas agroindustrial"
        assert normalizar_nome_empresa("Oi S.A. - Em Recuperação Judicial") == "oi"
        assert normalizar_nome_empresa("Calçados Gaúchos S/A") == "calcados gauchos"
        assert normalizar_nome_empresa("Grupo Lock Engenharia e Participações S.A.") == "lock engenharia"

    def test_calcular_similaridade_exata_ou_subconjunto(self) -> None:
        score1 = calcular_similaridade("Atlas Agroindustrial Ltda.", "Atlas Agroindustrial")
        assert score1 >= 0.95

        score2 = calcular_similaridade("Mineração Minas Gerais S.A.", "Mineracao Minas Gerais")
        assert score2 >= 0.95

    def test_calcular_similaridade_alta_fuzzy(self) -> None:
        score = calcular_similaridade("Lock Engenharia e Serviços Ltda", "Lock Engenharia S/A")
        assert score >= 0.80

    def test_calcular_similaridade_baixa_distintos(self) -> None:
        score = calcular_similaridade("Banco Bradesco S.A.", "Atlas Agroindustrial Ltda.")
        assert score < 0.40


class TestReconciliadorFontes:
    """Testes integrados para o motor ReconciliadorFontes."""

    @pytest.fixture
    def banco_com_dados(self) -> BancoDados:
        banco = BancoDados(":memory:")
        banco.inicializar_schema()

        # Inserir empresas
        emp_id1 = banco.salvar_empresa(
            slug="atlas-agroindustrial",
            nome_razao_social="Atlas Agroindustrial Ltda.",
            origem_fonte="aj_ruiz",
        )
        emp_id2 = banco.salvar_empresa(
            slug="empresa-desconhecida",
            nome_razao_social="Empresa Temporaria Desconhecida",
            origem_fonte="tribunal_tjsp",
        )

        # Inserir processos
        # Processo 1: Sem vínculo com Atlas, mas com Razão Social similar
        banco.salvar_processo(
            empresa_id=emp_id2,
            slug="processo-atlas-tjsp",
            numero_cnj="1002345-88.2024.8.26.0100",
            administrador_judicial="AJ Ruiz Consultoria",
        )

        return banco

    def test_reconciliacao_por_aj_e_razao_social(self, banco_com_dados: BancoDados) -> None:
        reconciliador = ReconciliadorFontes(banco=banco_com_dados)

        # Atualizar a razão social da empresa temporária para testar match fuzzy com Atlas
        conn = banco_com_dados.conectar()
        with conn:
            conn.execute(
                "UPDATE empresas SET nome_razao_social = 'Atlas Agroindustrial' WHERE slug = 'empresa-desconhecida'"
            )

        resultado = reconciliador.executar_reconciliacao(
            processos_cnj=["1002345-88.2024.8.26.0100"],
            limiar_similaridade=0.85,
            disparar_extracao=False,
        )

        assert resultado.total_matches_encontrados == 1
        m = resultado.matches[0]
        assert m.processo_cnj == "1002345-88.2024.8.26.0100"
        assert m.tipo_match == "razao_social"
        assert m.confianca >= 0.85

    def test_reconciliacao_por_cnj_com_catalogo_aj(self, banco_com_dados: BancoDados) -> None:
        reconciliador = ReconciliadorFontes(banco=banco_com_dados)

        # Mock do catálogo de AJs com CNJ coincidente
        catalogo_aj_mock = [
            {
                "fonte": "brizola",
                "empresa": "Calçados Sul",
                "cnj_limpo": "10023458820248260100",
                "total_docs": 3,
                "arquivos": ["doc1.pdf", "doc2.pdf"],
            }
        ]

        with patch.object(reconciliador, "_carregar_catalogo_manifesto_ajs", return_value=catalogo_aj_mock):
            resultado = reconciliador.executar_reconciliacao(
                processos_cnj=["1002345-88.2024.8.26.0100"],
                disparar_extracao=False,
            )

        assert resultado.total_matches_encontrados == 1
        m = resultado.matches[0]
        assert m.tipo_match == "cnj"
        assert m.confianca == 1.0
        assert m.fonte_aj == "brizola"
        assert m.documentos_vinculados == 3

    def test_reconciliacao_por_aj_quando_sem_match_nome(self, banco_com_dados: BancoDados) -> None:
        reconciliador = ReconciliadorFontes(banco=banco_com_dados)

        # Garantir que a empresa deste processo tenha nome totalmente diferente das demais
        conn = banco_com_dados.conectar()
        with conn:
            conn.execute(
                "UPDATE empresas SET nome_razao_social = 'Comercial Alpha Beta ZZZ' WHERE slug = 'empresa-desconhecida'"
            )

        with patch.object(reconciliador, "_carregar_catalogo_manifesto_ajs", return_value=[]):
            resultado = reconciliador.executar_reconciliacao(
                processos_cnj=["1002345-88.2024.8.26.0100"],
                limiar_similaridade=0.85,
                disparar_extracao=False,
            )

        assert resultado.total_matches_encontrados == 1
        m = resultado.matches[0]
        assert m.tipo_match == "administrador_judicial"
        assert m.fonte_aj == "aj_ruiz"
        assert m.confianca == 0.90
