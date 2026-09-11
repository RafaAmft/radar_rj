"""Testes unitários do motor de extração de texto e detecção de OCR."""

from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest

from src.processamento.extrator_texto import (
    ExtratorTextoPDF,
    ResultadoExtracao,
    normalizar_texto,
)


class TestNormalizacaoTexto:
    """Testes da função de higienização e normalização textual."""

    def test_uniao_hifenizacao_quebra_linha(self) -> None:
        """Une palavras partidas por hífen no fim da linha."""
        texto = "Processo de re-\ncuperação judicial em an-\n  damento."
        esperado = "Processo de recuperação judicial em andamento."
        assert normalizar_texto(texto) == esperado

    def test_remocao_nulos_e_espacos_excessivos(self) -> None:
        """Remove bytes nulos e múltiplos espaços e tabs."""
        texto = "Crédito\x00 no valor   de   R$ 1.500.000,00.\t\tData da AGC."
        normalizado = normalizar_texto(texto)
        assert "\x00" not in normalizado
        assert "R$ 1.500.000,00." in normalizado
        assert "   " not in normalizado

    def test_preservacao_quebra_paragrafo(self) -> None:
        """Preserva quebras duplas de parágrafo reduzindo quebras triplas ou maiores."""
        texto = "Parágrafo 1.\n\n\n\nParágrafo 2."
        esperado = "Parágrafo 1.\n\nParágrafo 2."
        assert normalizar_texto(texto) == esperado


class TestExtratorTextoPDF:
    """Testes funcionais do extrator de PDFs."""

    @pytest.fixture
    def pdf_com_texto(self, tmp_path: Path) -> Path:
        """Cria um PDF sintético de 2 páginas com texto vetorial."""
        doc = pymupdf.open()
        p1 = doc.new_page()
        p1.insert_text((50, 72), "Plano de Recuperacao Judicial da Empresa Alvo S.A.")
        p1.insert_text((50, 100), "Edital de Convocacao para a Assembleia Geral de Credores.")

        p2 = doc.new_page()
        p2.insert_text((50, 72), "Quadro Geral de Credores: Classe I Trabalhista totaliza R$ 5.000.000,00.")

        caminho = tmp_path / "documento_teste.pdf"
        doc.save(caminho)
        doc.close()
        return caminho

    @pytest.fixture
    def pdf_escaneado_simulado(self, tmp_path: Path) -> Path:
        """Cria um PDF de 1 página sem texto (simulando imagem/escaneado)."""
        doc = pymupdf.open()
        doc.new_page()  # página vazia (0 caracteres)
        caminho = tmp_path / "documento_escaneado.pdf"
        doc.save(caminho)
        doc.close()
        return caminho

    def test_extracao_pymupdf(self, pdf_com_texto: Path) -> None:
        """Extrai texto vetorial corretamente via PyMuPDF."""
        extrator = ExtratorTextoPDF()
        resultado = extrator.extrair_arquivo(pdf_com_texto)

        assert isinstance(resultado, ResultadoExtracao)
        assert resultado.total_paginas == 2
        assert resultado.paginas_com_texto == 2
        assert not resultado.is_scanned
        assert len(resultado.paginas_requerem_ocr) == 0
        assert "Plano de Recuperacao Judicial" in resultado.texto_completo
        assert "Quadro Geral de Credores" in resultado.texto_completo
        assert resultado.metadados["motor"] == "pymupdf"
        assert len(resultado.paginas) == 2

    def test_deteccao_pagina_escaneada_ocr(self, pdf_escaneado_simulado: Path) -> None:
        """Detecta página sem texto e sinaliza que requer OCR."""
        extrator = ExtratorTextoPDF(limiar_chars_ocr=50)
        resultado = extrator.extrair_arquivo(pdf_escaneado_simulado)

        assert resultado.total_paginas == 1
        assert resultado.paginas_com_texto == 0
        assert resultado.is_scanned
        assert 1 in resultado.paginas_requerem_ocr

    def test_fallback_pypdf(self, pdf_com_texto: Path) -> None:
        """Garante que a extração via pypdf funciona como fallback."""
        extrator = ExtratorTextoPDF()
        resultado = extrator._extrair_com_pypdf(
            pdf_com_texto, hash_arq="mockhash", tamanho=1000
        )

        assert resultado.total_paginas == 2
        assert "Plano de Recuperacao" in resultado.texto_completo
        assert resultado.metadados["motor"] == "pypdf"

    def test_salvar_resultado(self, pdf_com_texto: Path, tmp_path: Path) -> None:
        """Valida que o JSON estruturado e TXT são salvos corretamente."""
        extrator = ExtratorTextoPDF(salvar_txt_junto=True)
        resultado = extrator.extrair_arquivo(pdf_com_texto)

        dir_saida = tmp_path / "processed"
        json_path = extrator.salvar_resultado(resultado, dir_saida)

        assert json_path.exists()
        assert json_path.suffix == ".json"

        txt_path = dir_saida / f"{pdf_com_texto.stem}.txt"
        assert txt_path.exists()
        assert "Plano de Recuperacao Judicial" in txt_path.read_text(encoding="utf-8")

    def test_processar_diretorio_com_idempotencia(self, pdf_com_texto: Path, tmp_path: Path) -> None:
        """Testa o processamento em lote com respeito a idempotência."""
        dir_origem = tmp_path / "origem"
        dir_origem.mkdir()
        # Mover PDF para dir_origem
        pdf_origem = dir_origem / pdf_com_texto.name
        pdf_origem.write_bytes(pdf_com_texto.read_bytes())

        dir_destino = tmp_path / "destino"

        extrator = ExtratorTextoPDF()
        # Primeira execução: deve processar
        stats1 = extrator.processar_diretorio(dir_origem, dir_destino)
        assert stats1["processados"] == 1
        assert stats1["pulados"] == 0

        # Segunda execução: deve pular por idempotência
        stats2 = extrator.processar_diretorio(dir_origem, dir_destino)
        assert stats2["processados"] == 0
        assert stats2["pulados"] == 1

        # Forçar reprocessamento
        stats3 = extrator.processar_diretorio(dir_origem, dir_destino, forcar=True)
        assert stats3["processados"] == 1
        assert stats3["pulados"] == 0
