"""Testes unitários e de integração do motor de extração do Quadro Geral de Credores (QGC)."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pymupdf
import pytest

from src.processamento.cli import main as cli_main
from src.processamento.extrator_qgc import (
    CredorRecord,
    ExtratorQGC,
    ResultadoQGC,
)


class TestNormalizacaoValores:
    """Testes de conversão e higienização de valores monetários."""

    def test_valor_brl_formatado(self) -> None:
        assert ExtratorQGC.normalizar_valor("R$ 1.500.000,50") == 1500000.50

    def test_valor_sem_moeda(self) -> None:
        assert ExtratorQGC.normalizar_valor("12.674,00") == 12674.00

    def test_valor_com_tracos_e_espacos(self) -> None:
        assert ExtratorQGC.normalizar_valor("- 6.789,62-") == 6789.62

    def test_valor_zero_ou_vazio(self) -> None:
        assert ExtratorQGC.normalizar_valor("") == 0.0
        assert ExtratorQGC.normalizar_valor(None) == 0.0
        assert ExtratorQGC.normalizar_valor(" 0,00 ") == 0.0

    def test_valor_float_ou_int_direto(self) -> None:
        assert ExtratorQGC.normalizar_valor(1234.56) == 1234.56
        assert ExtratorQGC.normalizar_valor(500) == 500.0


class TestNormalizacaoDocumentos:
    """Testes de validação e formatação de CNPJs e CPFs."""

    def test_cnpj_formatado(self) -> None:
        fmt, dig, tipo = ExtratorQGC.normalizar_documento("55.788.528/0001-69")
        assert fmt == "55.788.528/0001-69"
        assert dig == "55788528000169"
        assert tipo == "CNPJ"

    def test_cnpj_apenas_digitos(self) -> None:
        fmt, dig, tipo = ExtratorQGC.normalizar_documento("55788528000169")
        assert fmt == "55.788.528/0001-69"
        assert dig == "55788528000169"
        assert tipo == "CNPJ"

    def test_cpf_formatado(self) -> None:
        fmt, dig, tipo = ExtratorQGC.normalizar_documento("123.456.789-00")
        assert fmt == "123.456.789-00"
        assert dig == "12345678900"
        assert tipo == "CPF"

    def test_cpf_apenas_digitos(self) -> None:
        fmt, dig, tipo = ExtratorQGC.normalizar_documento("12345678900")
        assert fmt == "123.456.789-00"
        assert dig == "12345678900"
        assert tipo == "CPF"

    def test_documento_desconhecido_ou_vazio(self) -> None:
        fmt, dig, tipo = ExtratorQGC.normalizar_documento("")
        assert tipo == "DESCONHECIDO"
        assert fmt == ""

        fmt, dig, tipo = ExtratorQGC.normalizar_documento("N/A")
        assert tipo == "DESCONHECIDO"


class TestNormalizacaoClasses:
    """Testes de enquadramento das classes da Lei 11.101/2005."""

    def test_classe_trabalhista(self) -> None:
        assert ExtratorQGC.normalizar_classe("Classe I") == "I - Trabalhista"
        assert ExtratorQGC.normalizar_classe("Credito Trabalhista") == "I - Trabalhista"
        assert ExtratorQGC.normalizar_classe("Acidente de trabalho") == "I - Trabalhista"

    def test_classe_garantia_real(self) -> None:
        assert ExtratorQGC.normalizar_classe("Classe II - Garantia Real") == "II - Garantia Real"
        assert ExtratorQGC.normalizar_classe("Credor Hipotecario") == "II - Garantia Real"

    def test_classe_quirografario(self) -> None:
        assert ExtratorQGC.normalizar_classe("Classe III") == "III - Quirografário"
        assert ExtratorQGC.normalizar_classe("Quirografario Geral") == "III - Quirografário"
        assert ExtratorQGC.normalizar_classe("") == "III - Quirografário"

    def test_classe_me_epp(self) -> None:
        assert ExtratorQGC.normalizar_classe("Classe IV") == "IV - ME/EPP"
        assert ExtratorQGC.normalizar_classe("Microempresa e EPP") == "IV - ME/EPP"

    def test_classe_extraconcursal(self) -> None:
        assert ExtratorQGC.normalizar_classe("Credito Extraconcursal") == "Extraconcursal"
        assert ExtratorQGC.normalizar_classe("Alienação Fiduciária (Art. 49)") == "Extraconcursal"


class TestExtratorQGCFluxo:
    """Testes de ponta a ponta do extrator de credores."""

    @pytest.fixture
    def pdf_qgc_sintetico(self, tmp_path: Path) -> Path:
        """Gera um PDF simulando texto de lista de credores."""
        doc = pymupdf.open()
        p1 = doc.new_page()
        linhas_texto = [
            "RELAÇÃO DE CREDORES - RECUPERAÇÃO JUDICIAL",
            "Classe I - Trabalhista",
            "João da Silva",
            "123.456.789-00",
            "R$ 50.000,00",
            "Classe III - Quirografário",
            "Banco Credor S.A.",
            "55.788.528/0001-69",
            "R$ 1.250.000,00",
            "Fornecedora de Insumos Ltda",
            "11.222.333/0001-44",
            "R$ 750.000,00",
        ]
        y = 50
        for linha in linhas_texto:
            p1.insert_text((50, y), linha)
            y += 25

        caminho = tmp_path / "qgc_teste.pdf"
        doc.save(caminho)
        doc.close()
        return caminho

    def test_extracao_camada_blocos(self, pdf_qgc_sintetico: Path) -> None:
        """Valida fallback de extração heurística de blocos de texto."""
        extrator = ExtratorQGC()
        resultado = extrator.extrair_pdf(pdf_qgc_sintetico)

        assert isinstance(resultado, ResultadoQGC)
        assert resultado.total_credores >= 3
        assert resultado.valor_total_apurado >= 2000000.0
        assert "I - Trabalhista" in resultado.totais_por_classe
        assert "III - Quirografário" in resultado.totais_por_classe

        nomes = [c.nome for c in resultado.credores]
        assert any("João da Silva" in n for n in nomes)
        assert any("Banco Credor" in n for n in nomes)

    def test_extracao_camada_tabela_nativa(self, tmp_path: Path) -> None:
        """Valida extração quando o TableFinder do PyMuPDF retorna linhas tabulares."""
        caminho = tmp_path / "tabela_simulada.pdf"
        doc = pymupdf.open()
        doc.new_page()
        doc.save(caminho)
        doc.close()

        extrator = ExtratorQGC()

        # Mock do resultado de find_tables()
        mock_tabela = MagicMock()
        mock_tabela.extract.return_value = [
            ["Classe", "Razão Social", "CNPJ ou CPF", "Crédito Líquido", "Cidade", "UF"],
            ["Classe I - Trabalhista", "Maria Souza", "222.333.444-55", "R$ 35.000,00", "São Paulo", "SP"],
            ["Classe III - Quirografário", "Distribuidora Beta Ltda", "33.444.555/0001-66", "R$ 480.000,00", "Campinas", "SP"],
            ["Classe IV - ME/EPP", "Gráfica Rápida ME", "44.555.666/0001-77", "R$ 15.500,00", "Santos", "SP"],
        ]

        with patch("pymupdf.open") as mock_open:
            mock_doc = MagicMock()
            mock_page = MagicMock()
            mock_page.find_tables.return_value = [mock_tabela]
            mock_doc.__iter__.return_value = [mock_page]
            mock_doc.__len__.return_value = 1
            mock_open.return_value = mock_doc

            resultado = extrator.extrair_pdf(caminho)

        assert resultado.total_credores == 3
        assert resultado.valor_total_apurado == 530500.0
        assert resultado.quantidade_por_classe["I - Trabalhista"] == 1
        assert resultado.quantidade_por_classe["III - Quirografário"] == 1
        assert resultado.quantidade_por_classe["IV - ME/EPP"] == 1

        credores = {c.nome: c for c in resultado.credores}
        assert "Maria Souza" in credores
        assert credores["Maria Souza"].documento == "222.333.444-55"
        assert credores["Maria Souza"].tipo_documento == "CPF"
        assert credores["Maria Souza"].cidade == "São Paulo"
        assert credores["Maria Souza"].uf == "SP"

    def test_salvar_resultado_json_e_csv(self, tmp_path: Path) -> None:
        """Verifica se a exportação em JSON e CSV funciona com encoding correto."""
        extrator = ExtratorQGC()
        resultado = ResultadoQGC(
            nome_arquivo="edital_credores.pdf",
            total_credores=2,
            valor_total_apurado=150000.0,
            totais_por_classe={"I - Trabalhista": 50000.0, "III - Quirografário": 100000.0},
            quantidade_por_classe={"I - Trabalhista": 1, "III - Quirografário": 1},
            credores=[
                CredorRecord(
                    nome="Credor 1",
                    documento="11.111.111/0001-11",
                    documento_limpo="11111111000111",
                    tipo_documento="CNPJ",
                    classe="I - Trabalhista",
                    valor=50000.0,
                    moeda="BRL",
                    cidade="Curitiba",
                    uf="PR",
                    pagina=1,
                ),
                CredorRecord(
                    nome="Credor 2",
                    documento="22.222.222/0001-22",
                    documento_limpo="22222222000122",
                    tipo_documento="CNPJ",
                    classe="III - Quirografário",
                    valor=100000.0,
                    moeda="BRL",
                    cidade="Londrina",
                    uf="PR",
                    pagina=2,
                ),
            ],
        )

        dir_saida = tmp_path / "saida_qgc"
        caminho_json, caminho_csv = extrator.salvar_resultado(resultado, dir_saida)

        assert caminho_json.exists()
        assert caminho_csv.exists()

        # Validar conteúdo JSON
        with open(caminho_json, "r", encoding="utf-8") as f:
            dados_json = json.load(f)
            assert dados_json["total_credores"] == 2
            assert dados_json["valor_total_apurado"] == 150000.0
            assert len(dados_json["credores"]) == 2

        # Validar conteúdo CSV
        with open(caminho_csv, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f, delimiter=";")
            linhas = list(reader)
            assert len(linhas) == 2
            assert linhas[0]["nome"] == "Credor 1"
            assert linhas[0]["classe"] == "I - Trabalhista"
            assert float(linhas[0]["valor"]) == 50000.0
            assert linhas[1]["nome"] == "Credor 2"
            assert linhas[1]["uf"] == "PR"

    def test_arquivo_inexistente_levanta_erro(self) -> None:
        extrator = ExtratorQGC()
        with pytest.raises(FileNotFoundError):
            extrator.extrair_pdf(Path("caminho/fantasma/inexistente.pdf"))


class TestCLIIntegracaoQGC:
    """Testa a execução via linha de comando com flag --qgc."""

    def test_cli_qgc_arquivo(self, tmp_path: Path) -> None:
        # Criar PDF sintético
        caminho_pdf = tmp_path / "relacao_credores.pdf"
        doc = pymupdf.open()
        p = doc.new_page()
        p.insert_text((50, 50), "Classe I - Trabalhista")
        p.insert_text((50, 80), "Carlos Eduardo")
        p.insert_text((50, 110), "999.888.777-66")
        p.insert_text((50, 140), "R$ 80.000,00")
        doc.save(caminho_pdf)
        doc.close()

        dir_saida = tmp_path / "saida_cli"
        cli_main(["--qgc", "--arquivo", str(caminho_pdf), "--dir-saida", str(dir_saida)])

        csv_gerado = dir_saida / "relacao_credores_credores.csv"
        json_gerado = dir_saida / "relacao_credores_credores.json"

        assert csv_gerado.exists()
        assert json_gerado.exists()
