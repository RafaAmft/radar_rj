"""
Módulo de OCR (Optical Character Recognition) do Radar de Ativos.

Gerencia a transcrição automática de páginas escaneadas, laudos periciais e certidões
embutidas em PDFs sem camada de texto vetorial.
"""

from __future__ import annotations

import logging
import shutil
from typing import Any

logger = logging.getLogger(__name__)


class MotorOCR:
    """Motor de OCR para transcrição de páginas escaneadas em PDFs."""

    def __init__(self, idioma: str = "por") -> None:
        self.idioma = idioma
        self._disponivel = self._verificar_disponibilidade()

    def _verificar_disponibilidade(self) -> bool:
        """Verifica se há algum motor de OCR disponível no sistema."""
        # 1. Checar se executável tesseract está no PATH
        if shutil.which("tesseract") is not None:
            return True

        # 2. Testar se o PyMuPDF consegue executar OCR nativamente
        try:
            import pymupdf

            doc = pymupdf.open()
            p = doc.new_page()
            p.get_textpage_ocr(language=self.idioma)
            doc.close()
            return True
        except Exception:
            pass

        return False

    def is_disponivel(self) -> bool:
        """Indica se o OCR pode ser executado no ambiente operacional corrente."""
        return self._disponivel

    def extrair_texto_pagina(self, pagina: Any) -> str:
        """
        Executa OCR em uma página do PyMuPDF (fitz.Page).

        Returns:
            Texto reconhecido e transcrito da imagem da página.
        """
        if not self.is_disponivel():
            logger.warning(
                "OCR solicitado, mas o Tesseract OCR / tessdata não foi detectado no sistema operacional. "
                "Para ativar OCR nativo, instale o Tesseract (ex: 'winget install tesseract-ocr' no Windows "
                "ou 'apt-get install tesseract-ocr tesseract-ocr-por' no Linux)."
            )
            return ""

        # Tentativa 1: PyMuPDF nativo get_textpage_ocr
        try:
            tp = pagina.get_textpage_ocr(language=self.idioma, dpi=150, full=True)
            texto = tp.extractText() or ""
            if texto.strip():
                return texto.strip()
        except Exception as e:
            logger.debug("Falha na tentativa PyMuPDF OCR: %s", e)

        # Tentativa 2: pytesseract se disponível
        try:
            import pytesseract
            from PIL import Image
            import io

            pix = pagina.get_pixmap(dpi=150)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            texto = pytesseract.image_to_string(img, lang=self.idioma)
            if texto.strip():
                return texto.strip()
        except Exception as e:
            logger.debug("Falha na tentativa pytesseract: %s", e)

        return ""
