"""Pacote de processamento de dados e extração de texto do Radar de Oportunidades."""

from src.processamento.extrator_qgc import CredorRecord, ExtratorQGC, ResultadoQGC
from src.processamento.extrator_texto import ExtratorTextoPDF, ResultadoExtracao
from src.processamento.ocr import MotorOCR

__all__ = [
    "CredorRecord",
    "ExtratorQGC",
    "ExtratorTextoPDF",
    "MotorOCR",
    "ResultadoExtracao",
    "ResultadoQGC",
]


