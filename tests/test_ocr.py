"""
Testes unitários e de integração do Motor de OCR para páginas escaneadas.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pymupdf
import pytest

from src.processamento.cli import main as cli_main
from src.processamento.extrator_texto import ExtratorTextoPDF
from src.processamento.ocr import MotorOCR


class TestMotorOCR:
    """Testes do módulo e motor de OCR."""

    def test_verificar_disponibilidade_boolean(self) -> None:
        motor = MotorOCR()
        assert isinstance(motor.is_disponivel(), bool)

    def test_aviso_quando_indisponivel(self) -> None:
        motor = MotorOCR()
        with patch.object(motor, "is_disponivel", return_value=False):
            texto = motor.extrair_texto_pagina(MagicMock())
            assert texto == ""

    def test_execucao_ocr_com_sucesso(self) -> None:
        motor = MotorOCR()
        mock_pagina = MagicMock()
        mock_textpage = MagicMock()
        mock_textpage.extractText.return_value = "Texto reconhecido via OCR da certidão."
        mock_pagina.get_textpage_ocr.return_value = mock_textpage

        with patch.object(motor, "is_disponivel", return_value=True):
            texto = motor.extrair_texto_pagina(mock_pagina)
            assert texto == "Texto reconhecido via OCR da certidão."


class TestIntegracaoExtratorTextoOCR:
    """Testa a integração do ExtratorTextoPDF com o OCR ativo."""

    @pytest.fixture
    def pdf_escaneado(self, tmp_path: Path) -> Path:
        """Cria um PDF sintético de 1 página simulando página escaneada sem texto vetorial."""
        doc = pymupdf.open()
        p = doc.new_page()
        # Inserir um desenho/retângulo simulando imagem para ter conteúdo
        p.draw_rect(pymupdf.Rect(50, 50, 200, 200), fill=(0.8, 0.8, 0.8))
        caminho = tmp_path / "escaneado.pdf"
        doc.save(caminho)
        doc.close()
        return caminho

    def test_extracao_sem_ocr_marca_requer_ocr(self, pdf_escaneado: Path) -> None:
        extrator = ExtratorTextoPDF(executar_ocr=False)
        res = extrator.extrair_arquivo(pdf_escaneado)

        assert res.total_paginas == 1
        assert len(res.paginas_requerem_ocr) == 1
        assert res.paginas_com_texto == 0

    def test_extracao_com_ocr_ativo_transcreve_pagina(self, pdf_escaneado: Path) -> None:
        extrator = ExtratorTextoPDF(executar_ocr=True)

        # Mock do motor de OCR para simular a transcrição bem sucedida
        texto_transcrito = "Certidão de Registro de Imóveis da Fazenda Primavera com área de 500 hectares."
        with patch.object(
            extrator.motor_ocr, "extrair_texto_pagina", return_value=texto_transcrito
        ):
            res = extrator.extrair_arquivo(pdf_escaneado)

        assert res.total_paginas == 1
        assert "Fazenda Primavera" in res.texto_completo
        assert res.paginas_com_texto == 1
        assert len(res.paginas_requerem_ocr) == 0

    def test_cli_com_flag_ocr(self, tmp_path: Path, pdf_escaneado: Path) -> None:
        dir_saida = tmp_path / "saida_ocr"
        texto_mock = (
            "Certidão de Objeto e Pé transcrita pelo motor OCR com mais de cinquenta caracteres."
        )
        with patch(
            "src.processamento.ocr.MotorOCR.extrair_texto_pagina",
            return_value=texto_mock,
        ):
            cli_main(["--arquivo", str(pdf_escaneado), "--dir-saida", str(dir_saida), "--ocr"])

        json_gerado = dir_saida / f"{pdf_escaneado.stem}.json"
        txt_gerado = dir_saida / f"{pdf_escaneado.stem}.txt"
        assert json_gerado.exists()
        assert txt_gerado.exists()

