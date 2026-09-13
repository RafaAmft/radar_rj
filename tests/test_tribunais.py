"""
Testes automatizados para o subsistema de Tribunais de Justiça.
Cobre: Roteador CNJ, Cliente DataJud, Consultor e-SAJ e Pipeline Integrado com Banco.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from src.banco.repositorio import BancoDados
from src.ingestao.tribunais.base import (
    formatar_numero_cnj,
    identificar_tribunal_por_cnj,
    limpar_numero_cnj,
)
from src.ingestao.tribunais.datajud import ClienteDataJud
from src.ingestao.tribunais.esaj import ConsultorEsaj
from src.ingestao.tribunais.modelos import (
    MovimentacaoProcessual,
    ParteProcessual,
    ProcessoTribunalInfo,
)
from src.ingestao.tribunais.pipeline import PipelineTribunais, executar, gerar_slug


# ==============================================================================
# 1. TESTES DO ROTEADOR CNJ
# ==============================================================================
class TestRoteadorCNJ:
    """Testes de identificação e normalização de números CNJ."""

    def test_identificar_tribunal_tjsp(self) -> None:
        sigla, uf, sistema = identificar_tribunal_por_cnj("1024564-80.2024.8.26.0100")
        assert sigla == "tjsp"
        assert uf == "SP"
        assert sistema == "esaj"

    def test_identificar_tribunal_tjmt(self) -> None:
        sigla, uf, sistema = identificar_tribunal_por_cnj("1022365-90.2021.8.11.0041")
        assert sigla == "tjmt"
        assert uf == "MT"
        assert sistema == "pje"

    def test_identificar_tribunal_tjrs(self) -> None:
        sigla, uf, sistema = identificar_tribunal_por_cnj("5001234-56.2023.8.21.0001")
        assert sigla == "tjrs"
        assert uf == "RS"
        assert sistema == "eproc"

    def test_identificar_tribunal_tjsc(self) -> None:
        sigla, uf, sistema = identificar_tribunal_por_cnj("0300123-45.2022.8.24.0023")
        assert sigla == "tjsc"
        assert uf == "SC"
        assert sistema == "esaj"

    def test_identificar_cnj_invalido_ou_curto(self) -> None:
        sigla, uf, sistema = identificar_tribunal_por_cnj("123456")
        assert sigla == "desconhecido"
        assert uf == ""
        assert sistema == ""

    def test_formatar_e_limpar_numero_cnj(self) -> None:
        num_limpo = "10245648020248260100"
        formatado = formatar_numero_cnj(num_limpo)
        assert formatado == "1024564-80.2024.8.26.0100"
        assert limpar_numero_cnj(formatado) == num_limpo


# ==============================================================================
# 2. TESTES DO CLIENTE DATAJUD (CNJ)
# ==============================================================================
class TestClienteDataJud:
    """Testes com mocks HTTP para a API do DataJud."""

    @pytest.fixture
    def mock_payload_datajud(self) -> dict:
        return {
            "hits": {
                "total": {"value": 1},
                "hits": [
                    {
                        "_source": {
                            "numeroProcesso": "10245648020248260100",
                            "tribunal": "TJSP",
                            "grau": "G1",
                            "dataAjuizamento": "20240221225722",
                            "classe": {"codigo": 12134, "nome": "Tutela Cautelar Antecedente"},
                            "orgaoJulgador": {"nome": "2ª Vara de Falências e Recuperações Judiciais"},
                            "assuntos": [{"nome": "Recuperação judicial"}],
                            "movimentos": [
                                {
                                    "codigo": 26,
                                    "nome": "Distribuição",
                                    "dataHora": "2024-02-21T23:01:01.000Z",
                                    "complementosTabelados": [{"nome": "dependência"}],
                                }
                            ],
                        }
                    }
                ],
            }
        }

    def test_buscar_por_numero_com_sucesso(self, mock_payload_datajud: dict) -> None:
        cliente = ClienteDataJud()
        with patch("requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = mock_payload_datajud
            mock_post.return_value = mock_resp

            resultado = cliente.buscar_por_numero("1024564-80.2024.8.26.0100")

            assert resultado is not None
            assert resultado.numero_cnj == "1024564-80.2024.8.26.0100"
            assert resultado.tribunal == "TJSP"
            assert resultado.classe_codigo == 12134
            assert resultado.classe_nome == "Tutela Cautelar Antecedente"
            assert len(resultado.movimentacoes) == 1
            assert resultado.movimentacoes[0].nome == "Distribuição"
            assert resultado.movimentacoes[0].complemento == "dependência"

    def test_buscar_por_numero_nao_encontrado(self) -> None:
        cliente = ClienteDataJud()
        with patch("requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"hits": {"hits": []}}
            mock_post.return_value = mock_resp

            resultado = cliente.buscar_por_numero("1024564-80.2024.8.26.0100")
            assert resultado is None

    def test_listar_novos_processos(self, mock_payload_datajud: dict) -> None:
        cliente = ClienteDataJud()
        with patch("requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = mock_payload_datajud
            mock_post.return_value = mock_resp

            lista = cliente.listar_novos_processos(tribunal="tjsp", limite=5)
            assert len(lista) == 1
            assert lista[0].numero_limpo == "10245648020248260100"


# ==============================================================================
# 3. TESTES DO CONSULTOR E-SAJ
# ==============================================================================
class TestConsultorEsaj:
    """Testes do consultor e-SAJ e seu parser de HTML."""

    @pytest.fixture
    def html_amostra_esaj(self) -> str:
        return """
        <html>
            <body>
                <span id="classeProcesso">Recuperação Judicial</span>
                <span id="assuntoProcesso">Concurso de Credores</span>
                <span id="foroProcesso">Foro Central Cível</span>
                <span id="varaProcesso">2ª Vara de Falências</span>
                <span id="juizProcesso">Dr. Juiz de Direito</span>
                <span id="valorAcaoProcesso">R$ 90.419.751,76</span>
                <table id="tableTodasPartes">
                    <tr>
                        <td>Reqdo:</td>
                        <td>Athol Participações Ltda Advogada: Dra. Ana Silva</td>
                    </tr>
                    <tr>
                        <td>Falido:</td>
                        <td>Lsk Engenharia e Serviços Ltda.</td>
                    </tr>
                    <tr>
                        <td>Credor:</td>
                        <td>Itaú Unibanco S.A Advogado: Dr. Carlos Mendes</td>
                    </tr>
                    <tr>
                        <td>Administrador:</td>
                        <td>AJ Ruiz Consultoria Judicial</td>
                    </tr>
                </table>
            </body>
        </html>
        """

    def test_suporta_tribunais_esaj(self) -> None:
        consultor = ConsultorEsaj()
        assert consultor.suporta_tribunal("tjsp") is True
        assert consultor.suporta_tribunal("tjsc") is True
        assert consultor.suporta_tribunal("tjrj") is False
        assert consultor.suporta_tribunal("tjmg") is False

    def test_parsear_html_processo(self, html_amostra_esaj: str) -> None:
        consultor = ConsultorEsaj()
        info = consultor.parsear_html_processo(
            html=html_amostra_esaj,
            numero_cnj="1024564-80.2024.8.26.0100",
            tribunal="TJSP",
            url_consulta="https://esaj.tjsp.jus.br/show.do?mock",
        )

        assert info.numero_cnj == "1024564-80.2024.8.26.0100"
        assert info.classe_nome == "Recuperação Judicial"
        assert info.vara == "2ª Vara de Falências"
        assert info.comarca == "Foro Central Cível"
        assert info.juiz == "Dr. Juiz de Direito"
        assert info.valor_causa == 90419751.76

        # Partes e Devedores
        assert "Athol Participações Ltda" in info.devedores
        assert "Lsk Engenharia e Serviços Ltda." in info.devedores
        assert "Itaú Unibanco S.A" in info.credores
        assert info.administrador_judicial == "AJ Ruiz Consultoria Judicial"
        assert len(info.partes) == 4


# ==============================================================================
# 4. TESTES DO PIPELINE INTEGRADO E BANCO DE DADOS
# ==============================================================================
class TestPipelineIntegrado:
    """Testes da orquestração unificada e persistência no banco de dados."""

    @pytest.fixture
    def banco_memoria(self) -> BancoDados:
        banco = BancoDados(":memory:")
        banco.inicializar_schema()
        return banco

    def test_processar_processo_especifico_e_persistir(self, banco_memoria: BancoDados) -> None:
        mock_datajud = MagicMock()
        mock_datajud.buscar_por_numero.return_value = ProcessoTribunalInfo(
            numero_cnj="1024564-80.2024.8.26.0100",
            numero_limpo="10245648020248260100",
            tribunal="TJSP",
            data_distribuicao="20240221225722",
            movimentacoes=[MovimentacaoProcessual(data_hora="2024-02-21", nome="Distribuição")],
        )

        mock_esaj = MagicMock()
        mock_esaj.suporta_tribunal.return_value = True
        mock_esaj.consultar_processo.return_value = ProcessoTribunalInfo(
            numero_cnj="1024564-80.2024.8.26.0100",
            numero_limpo="10245648020248260100",
            tribunal="TJSP",
            classe_nome="Tutela Cautelar",
            orgao_julgador="2ª Vara de Falências - Foro Central",
            valor_causa=90419751.76,
            devedores=["Athol Participações Ltda"],
            credores=["Itaú Unibanco S.A"],
            administrador_judicial="AJ Ruiz",
            url_consulta="https://esaj.tjsp.jus.br/mock",
        )

        pipeline = PipelineTribunais(
            cliente_datajud=mock_datajud,
            consultor_esaj=mock_esaj,
            banco=banco_memoria,
        )

        res = pipeline.processar_processo_especifico(
            numero_cnj="1024564-80.2024.8.26.0100",
            salvar_banco=True,
            salvar_raw=False,
        )

        assert res is not None
        assert res.numero_cnj == "1024564-80.2024.8.26.0100"
        assert res.valor_causa == 90419751.76
        assert "Athol Participações Ltda" in res.devedores
        assert len(res.movimentacoes) == 1

        # Validar persistência no banco em memória
        with banco_memoria as repo:
            conn = repo.conectar()
            empresa = conn.execute("SELECT * FROM empresas WHERE slug = 'athol-participacoes-ltda';").fetchone()
            assert empresa is not None
            assert empresa["nome_razao_social"] == "Athol Participações Ltda"

            processo = conn.execute("SELECT * FROM processos WHERE numero_cnj = '1024564-80.2024.8.26.0100';").fetchone()
            assert processo is not None
            assert processo["administrador_judicial"] == "AJ Ruiz"

    def test_funcao_executar_dry_run(self) -> None:
        resultado = executar(
            processo="1024564-80.2024.8.26.0100",
            dry_run=True,
        )
        assert resultado["status"] == "dry_run"
        assert resultado["processo"] == "1024564-80.2024.8.26.0100"
