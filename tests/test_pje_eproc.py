"""
Testes unitários para os consultores de tribunais PJe e Eproc, e integração com PipelineTribunais.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from src.banco.repositorio import BancoDados
from src.ingestao.tribunais.eproc import ConsultorEproc
from src.ingestao.tribunais.modelos import (
    ParteProcessual,
    ProcessoTribunalInfo,
)
from src.ingestao.tribunais.pipeline import PipelineTribunais
from src.ingestao.tribunais.pje import ConsultorPje


HTML_PJE_EXEMPLO = """
<html>
<body>
    <div id="dadosProcesso">
        <span>Classe Judicial: Recuperação Judicial</span>
        <span>Órgão Julgador: 2ª Vara Empresarial de Belo Horizonte</span>
        <span>Valor da causa: R$ 45.230.150,00</span>
    </div>
    <table class="rich-table partes">
        <tr>
            <th>Polo Ativo (Autor)</th>
            <td>Mineração Minas Gerais S.A.</td>
        </tr>
        <tr>
            <th>Polo Passivo (Réu)</th>
            <td>Banco do Brasil S.A.</td>
        </tr>
        <tr>
            <th>Polo Passivo (Credor)</th>
            <td>Fornecedores Gerais Ltda</td>
        </tr>
        <tr>
            <th>Administrador Judicial</th>
            <td>Gomes & Associados Administração Judicial</td>
        </tr>
    </table>
</body>
</html>
"""

HTML_EPROC_EXEMPLO = """
<html>
<body>
    <div id="capaProcesso">
        <span id="lblClasseProcessual">Classe: Recuperação Judicial</span>
        <span id="lblOrgaoJulgador">Órgão Julgador: Vara Regional de Falências e RJs de Porto Alegre</span>
        <span id="lblValorCausa">Valor da Causa: R$ 12.800.000,50</span>
    </div>
    <table class="infraTable" id="tbPartes">
        <tr>
            <td>Autor / Recuperanda:</td>
            <td>Calçados Gaúchos Indústria e Comércio S.A.</td>
        </tr>
        <tr>
            <td>Interessado / Credor:</td>
            <td>Couros do Sul Ltda</td>
        </tr>
        <tr>
            <td>Interessado / Credor:</td>
            <td>Banrisul S.A.</td>
        </tr>
        <tr>
            <td>Administrador Judicial:</td>
            <td>Brizola e Japur Administração Judicial</td>
        </tr>
    </table>
</body>
</html>
"""


class TestConsultorPje:
    """Testes para o consultor PJe."""

    def test_suporta_tribunais_pje(self) -> None:
        consultor = ConsultorPje()
        assert consultor.suporta_tribunal("tjmg") is True
        assert consultor.suporta_tribunal("tjmt") is True
        assert consultor.suporta_tribunal("tjdf") is True
        assert consultor.suporta_tribunal("tjrj") is True
        assert consultor.suporta_tribunal("tjsp") is False
        assert consultor.suporta_tribunal("tjrs") is False

    def test_parsear_html_processo_pje(self) -> None:
        consultor = ConsultorPje()
        info = consultor.parsear_html_processo(
            html=HTML_PJE_EXEMPLO,
            numero_cnj="5012345-67.2024.8.13.0024",
            tribunal="tjmg",
        )

        assert info.tribunal == "TJMG"
        assert info.numero_cnj == "5012345-67.2024.8.13.0024"
        assert info.classe_nome == "Recuperação Judicial"
        assert "2ª Vara Empresarial" in info.orgao_julgador
        assert info.valor_causa == 45230150.00
        assert "Mineração Minas Gerais S.A." in info.devedores
        assert "Banco do Brasil S.A." in info.credores
        assert "Fornecedores Gerais Ltda" in info.credores
        assert len(info.partes) == 4

    def test_fallback_datajud_quando_pje_sem_html(self) -> None:
        mock_datajud = MagicMock()
        mock_datajud.buscar_por_numero.return_value = ProcessoTribunalInfo(
            numero_cnj="5012345-67.2024.8.13.0024",
            numero_limpo="50123456720248130024",
            tribunal="TJMG",
            grau="1G",
            classe_codigo=129,
            classe_nome="Recuperação Judicial",
            orgao_julgador="Vara Empresarial de BH",
            vara="Vara Empresarial de BH",
            valor_causa=0.0,
        )

        consultor = ConsultorPje(cliente_datajud=mock_datajud)
        # Mockando requisitar_pje para falhar/bloquear
        with patch.object(consultor, "_requisitar_pje", return_value=None):
            info = consultor.consultar_processo("5012345-67.2024.8.13.0024")

        assert info is not None
        assert info.tribunal == "TJMG"
        assert info.classe_nome == "Recuperação Judicial"
        assert "pje.tjmg.jus.br" in info.url_consulta
        mock_datajud.buscar_por_numero.assert_called_once()


class TestConsultorEproc:
    """Testes para o consultor Eproc."""

    def test_suporta_tribunais_eproc(self) -> None:
        consultor = ConsultorEproc()
        assert consultor.suporta_tribunal("tjrs") is True
        assert consultor.suporta_tribunal("tjsc") is True
        assert consultor.suporta_tribunal("tjto") is True
        assert consultor.suporta_tribunal("trf4") is True
        assert consultor.suporta_tribunal("tjsp") is False
        assert consultor.suporta_tribunal("tjmg") is False

    def test_parsear_html_processo_eproc(self) -> None:
        consultor = ConsultorEproc()
        info = consultor.parsear_html_processo(
            html=HTML_EPROC_EXEMPLO,
            numero_cnj="5009876-54.2024.8.21.0001",
            tribunal="tjrs",
        )

        assert info.tribunal == "TJRS"
        assert info.numero_cnj == "5009876-54.2024.8.21.0001"
        assert info.classe_nome == "Recuperação Judicial"
        assert "Porto Alegre" in info.orgao_julgador
        assert info.valor_causa == 12800000.50
        assert "Calçados Gaúchos Indústria e Comércio S.A." in info.devedores
        assert "Couros do Sul Ltda" in info.credores
        assert "Banrisul S.A." in info.credores
        assert len(info.partes) == 4

    def test_fallback_datajud_quando_eproc_bloqueia(self) -> None:
        mock_datajud = MagicMock()
        mock_datajud.buscar_por_numero.return_value = ProcessoTribunalInfo(
            numero_cnj="5009876-54.2024.8.21.0001",
            numero_limpo="50098765420248210001",
            tribunal="TJRS",
            grau="1G",
            classe_codigo=129,
            classe_nome="Recuperação Judicial",
            orgao_julgador="Vara de Falências de POA",
            vara="Vara de Falências de POA",
            valor_causa=0.0,
        )

        consultor = ConsultorEproc(cliente_datajud=mock_datajud)
        with patch.object(consultor, "_requisitar_eproc", return_value=None):
            info = consultor.consultar_processo("5009876-54.2024.8.21.0001")

        assert info is not None
        assert info.tribunal == "TJRS"
        assert "eproc1g.tjrs.jus.br" in info.url_consulta
        mock_datajud.buscar_por_numero.assert_called_once()


class TestPipelineComPjeEEproc:
    """Testes de despacho de roteamento no PipelineTribunais."""

    def test_pipeline_roteia_para_pje(self) -> None:
        mock_datajud = MagicMock()
        mock_datajud.buscar_por_numero.return_value = None

        mock_pje = MagicMock()
        mock_pje.suporta_tribunal.return_value = True
        mock_pje.consultar_processo.return_value = ProcessoTribunalInfo(
            numero_cnj="5012345-67.2024.8.13.0024",
            numero_limpo="50123456720248130024",
            tribunal="TJMG",
            grau="1G",
            classe_codigo=129,
            classe_nome="Recuperação Judicial",
            orgao_julgador="Vara de BH",
            vara="Vara de BH",
            valor_causa=1000000.0,
            devedores=["Empresa Mineira Ltda"],
        )

        banco = BancoDados(db_path=":memory:")
        banco.inicializar_schema()
        pipeline = PipelineTribunais(
            cliente_datajud=mock_datajud,
            consultor_pje=mock_pje,
            banco=banco,
        )

        resultado = pipeline.processar_processo_especifico(
            "5012345-67.2024.8.13.0024", salvar_banco=True, salvar_raw=False
        )

        assert resultado is not None
        assert resultado.tribunal == "TJMG"
        mock_pje.consultar_processo.assert_called_once_with("5012345-67.2024.8.13.0024")

        # Verificar se gravou no banco
        empresa = banco.obter_empresa_por_slug("empresa-mineira-ltda")
        assert empresa is not None

    def test_pipeline_roteia_para_eproc(self) -> None:
        mock_datajud = MagicMock()
        mock_datajud.buscar_por_numero.return_value = None

        mock_eproc = MagicMock()
        mock_eproc.suporta_tribunal.return_value = True
        mock_eproc.consultar_processo.return_value = ProcessoTribunalInfo(
            numero_cnj="5009876-54.2024.8.21.0001",
            numero_limpo="50098765420248210001",
            tribunal="TJRS",
            grau="1G",
            classe_codigo=129,
            classe_nome="Recuperação Judicial",
            orgao_julgador="Vara de POA",
            vara="Vara de POA",
            valor_causa=2000000.0,
            devedores=["Empresa Gaucha S.A."],
        )

        banco = BancoDados(db_path=":memory:")
        banco.inicializar_schema()
        pipeline = PipelineTribunais(
            cliente_datajud=mock_datajud,
            consultor_eproc=mock_eproc,
            banco=banco,
        )

        resultado = pipeline.processar_processo_especifico(
            "5009876-54.2024.8.21.0001", salvar_banco=True, salvar_raw=False
        )

        assert resultado is not None
        assert resultado.tribunal == "TJRS"
        mock_eproc.consultar_processo.assert_called_once_with("5009876-54.2024.8.21.0001")

        empresa = banco.obter_empresa_por_slug("empresa-gaucha-sa")
        assert empresa is not None
