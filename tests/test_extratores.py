"""Testes unitários para os 4 extratores com simulação de requisições (mocks)."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.ingestao import cvm_dfp_itr, cvm_ipe, esaj_tjsp, itd_acordaos


def _criar_zip_em_memoria(arquivos: dict[str, str | bytes]) -> bytes:
    """Helper: cria bytes de um arquivo ZIP contendo os arquivos especificados."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for nome, conteudo in arquivos.items():
            if isinstance(conteudo, str):
                zf.writestr(nome, conteudo.encode("utf-8"))
            else:
                zf.writestr(nome, conteudo)
    return buf.getvalue()


class TestExtratorCvmDfpItr:
    """Testes do extrator de demonstrações financeiras da CVM."""

    def test_executar_filtra_e_salva_csv(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verifica se o extrator DFP/ITR filtra pelo CNPJ e registra no manifesto."""
        monkeypatch.setattr(cvm_dfp_itr, "DIR_DATA_RAW", tmp_path)

        csv_mock = (
            "CNPJ_CIA;DENOM_CIA;CD_CVM;DT_REFER;VERSAO;GRUPO_DFP;MOEDA;ESCALA_MOEDA;"
            "ORDEM_EXERC;DT_FIM_EXERC;CD_CONTA;DS_CONTA;VL_CONTA;ST_CONTA_FIXA\n"
            "76535764000143;OI S.A.;11312;2024-12-31;1;DFP;BRL;MIL;ÚLTIMO;2024-12-31;1;Ativo Total;1000000;S\n"
            "99999999000199;OUTRA CIA;99999;2024-12-31;1;DFP;BRL;MIL;ÚLTIMO;2024-12-31;1;Ativo Total;500000;S\n"
        )
        zip_bytes = _criar_zip_em_memoria({"dfp_cia_aberta_BPA_con_2024.csv": csv_mock})

        with patch("src.ingestao.cvm_dfp_itr.download_com_retry", return_value=zip_bytes):
            resultado = cvm_dfp_itr.executar(slugs_empresa=["oi"], anos=[2024])

        assert resultado.get("oi", 0) >= 1
        arquivo_salvo = tmp_path / "oi" / "cvm" / "dfp_itr" / "dfp_BPA_con_2024.csv"
        assert arquivo_salvo.exists()
        conteudo_salvo = arquivo_salvo.read_text(encoding="utf-8")
        assert "76535764000143" in conteudo_salvo
        assert "99999999000199" not in conteudo_salvo

        manifesto_path = tmp_path / "oi" / "ingestion_manifest.json"
        assert manifesto_path.exists()
        assert "dfp_BPA_con_2024.csv" in manifesto_path.read_text(encoding="utf-8")


class TestExtratorCvmIpe:
    """Testes do extrator de informações periódicas e eventuais (IPE) da CVM."""

    def test_executar_baixa_pdf_e_registra(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verifica se o IPE processa índice CSV e salva o PDF do fato relevante."""
        monkeypatch.setattr(cvm_ipe, "DIR_DATA_RAW", tmp_path)

        csv_indice = (
            "Codigo_CVM;Nome_Companhia;CNPJ_Companhia;Categoria;Tipo;Especie;Data_Referencia;"
            "Data_Entrega;Status;Versao;Protocolo_Envio;Numero_Sequencia;Link_Download\n"
            "11312;OI S.A. - EM RECUPERAÇÃO JUDICIAL;76.535.764/0001-43;Fato Relevante;"
            "Comunicado;Outros;2024-05-15;2024-05-15;Ativo;1;12345;1;https://cvm.gov.br/doc.pdf\n"
        )
        zip_indice = _criar_zip_em_memoria({"ipe_cia_aberta_2024.csv": csv_indice})
        pdf_falso = b"%PDF-1.4 Fake PDF Content for Unit Test"

        def _mock_download(url: str, **kwargs):
            if "zip" in url.lower():
                return zip_indice
            return pdf_falso

        with patch("src.ingestao.cvm_ipe.download_com_retry", side_effect=_mock_download):
            resultado = cvm_ipe.executar(slugs_empresa=["oi"], anos=[2024], max_documentos=1)

        assert resultado.get("oi", 0) == 1
        arquivos = list((tmp_path / "oi" / "cvm" / "ipe").glob("*.pdf"))
        assert len(arquivos) == 1
        assert arquivos[0].read_bytes().startswith(b"%PDF")

        manifesto_path = tmp_path / "oi" / "ingestion_manifest.json"
        assert manifesto_path.exists()
        assert "cvm_ipe" in manifesto_path.read_text(encoding="utf-8")


class TestExtratorItd:
    """Testes do extrator da amostra de acórdãos do STF (ITD)."""

    def test_executar_salva_acordao_e_idempotencia(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verifica se o ITD formata o acórdão, salva em _amostra_estrutural e respeita idempotência."""
        monkeypatch.setattr(itd_acordaos, "DIR_DATA_RAW", tmp_path)

        registros_mock = [
            {
                "id": "RE_999999",
                "numero": "RE 999999",
                "classe": "RE",
                "relator": "Min. Teste",
                "data_julgamento": "2024-01-01",
                "ementa": "Ementa de teste sobre recuperação judicial.",
                "relatorio": "Relatório descritivo do caso.",
                "voto": "Voto do relator provendo o recurso.",
            }
        ]

        with patch("src.ingestao.itd_acordaos._parse_json_streaming", return_value=registros_mock):
            salvos = itd_acordaos.executar()

        assert salvos == 1
        dir_itd = tmp_path / "_amostra_estrutural" / "itd_acordaos"
        arquivo_txt = dir_itd / "RE_999999.txt"
        assert arquivo_txt.exists()
        conteudo = arquivo_txt.read_text(encoding="utf-8")
        assert "Ementa de teste" in conteudo
        assert "Min. Teste" in conteudo

        manifesto_path = dir_itd / "ingestion_manifest.json"
        assert manifesto_path.exists()
        assert "RE_999999.txt" in manifesto_path.read_text(encoding="utf-8")

        # Teste de reexecução (idempotência dentro do loop)
        with patch("src.ingestao.itd_acordaos._parse_json_streaming", return_value=registros_mock):
            salvos_segunda_vez = itd_acordaos.executar()
        assert salvos_segunda_vez == 0


class TestExtratorEsajDataJud:
    """Testes da consulta e fallback DataJud/CNJ no extrator e-SAJ."""

    def test_fallback_datajud_com_sucesso(self, tmp_path: Path) -> None:
        """Verifica o parsing da resposta da API pública do DataJud."""
        resposta_api = {
            "hits": {
                "hits": [
                    {
                        "_source": {
                            "dadosBasicos": {
                                "numero": "1001234-56.2024.8.26.0100",
                                "classeProcessual": "128",
                                "dataAjuizamento": "2024-02-10T14:30:00.000Z",
                                "valorCausa": 15000000.0,
                                "orgaoJulgador": {"nome": "2ª Vara de Falências e Recuperações Judiciais"},
                            },
                            "movimento": [
                                {
                                    "dataHora": "2024-02-11T10:00:00",
                                    "nome": "Distribuição",
                                    "complementosTabelados": [{"descricao": "Por Sorteio"}],
                                }
                            ],
                        }
                    }
                ]
            }
        }

        mock_resp = MagicMock()
        mock_resp.json.return_value = resposta_api
        mock_resp.raise_for_status.return_value = None

        config_mock = {
            "urls": {"datajud_api": "https://api-publica.datajud.cnj.jus.br/api_publica_tjsp/_search"},
            "classe_processual": "128",
        }

        with patch("requests.post", return_value=mock_resp):
            resultados = esaj_tjsp._fallback_datajud("Empresa Teste S.A.", tmp_path, config_mock)

        assert len(resultados) == 1
        item = resultados[0]
        assert item["numero_processo"] == "1001234-56.2024.8.26.0100"
        assert item["classe_processual"] == "128"
        assert item["valor_causa"] == 15000000.0
        assert item["orgao_julgador"]["nome"] == "2ª Vara de Falências e Recuperações Judiciais"
        assert item["fonte"] == "datajud_fallback"
        assert len(item["movimentacoes"]) == 1
