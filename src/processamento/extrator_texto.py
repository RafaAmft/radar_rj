"""
Motor de extração de texto, normalização e detecção de OCR para PDFs.

Estratégia híbrida:
1. PyMuPDF (fitz) para extração nativa de alta velocidade (<50ms).
2. pypdf como fallback sem dependências nativas.
3. Detecção automática de páginas escaneadas que exigem OCR.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from tqdm import tqdm

logger = logging.getLogger(__name__)

# Raiz do projeto
RAIZ_PROJETO = Path(__file__).resolve().parent.parent.parent
DIR_DATA_RAW = RAIZ_PROJETO / "data" / "raw"
DIR_DATA_PROCESSED = RAIZ_PROJETO / "data" / "processed"


@dataclass
class PaginaInfo:
    """Informações e texto extraído de uma página individual."""

    numero: int
    chars: int
    imagens: int
    requer_ocr: bool
    texto: str


@dataclass
class ResultadoExtracao:
    """Resultado completo e estruturado da extração de um documento PDF."""

    arquivo_origem: str
    nome_arquivo: str
    hash_sha256: str
    tamanho_bytes: int
    total_paginas: int
    paginas_com_texto: int
    is_scanned: bool
    paginas_requerem_ocr: list[int]
    metadados: dict[str, Any]
    texto_completo: str
    paginas: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Converte o resultado em dicionário serializável."""
        return asdict(self)


def normalizar_texto(texto: str) -> str:
    """
    Normaliza o texto extraído para análise e mineração.

    Aplica:
    - Junção de palavras separadas por hifenização e quebra de linha (ex: "re-\\ncuperação" -> "recuperação").
    - Remoção de caracteres de controle e nulos.
    - Uniformização de quebras de linha e remoção de espaços duplicados.
    - Preservação da formatação monetária e numérica brasileira (ex: "R$ 1.250.000,00").
    """
    if not texto:
        return ""

    # Remover caracteres nulos
    texto = texto.replace("\x00", "")

    # Unir palavras quebradas por hifenização no fim da linha
    # Ex: "recupera- \nção" -> "recuperação"
    texto = re.sub(r"(\w+)-\s*[\r\n]+\s*(\w+)", r"\1\2", texto)

    # Normalizar quebras de linha Windows para Unix
    texto = texto.replace("\r\n", "\n").replace("\r", "\n")

    # Limpar linhas individuais removendo espaços à direita e tabs
    linhas = [re.sub(r"[ \t]+", " ", l).strip() for l in texto.split("\n")]

    # Agrupar linhas mantendo quebras de parágrafo duplas
    texto_limpo = "\n".join(linhas)
    # Reduzir mais de 2 quebras consecutivas a no máximo 2
    texto_limpo = re.sub(r"\n{3,}", "\n\n", texto_limpo)

    return texto_limpo.strip()


def _calcular_sha256(caminho: Path) -> str:
    """Calcula hash SHA-256 de um arquivo."""
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()


class ExtratorTextoPDF:
    """Motor de extração de texto e detecção de documentos escaneados."""

    def __init__(self, limiar_chars_ocr: int = 50, salvar_txt_junto: bool = True):
        """
        Args:
            limiar_chars_ocr: Número mínimo de caracteres por página para considerar
                              que possui texto vetorial útil (abaixo disso, marca OCR).
            salvar_txt_junto: Se True, além do .json estruturado salva também um .txt com
                              o texto completo limpo para buscas diretas.
        """
        self.limiar_chars_ocr = limiar_chars_ocr
        self.salvar_txt_junto = salvar_txt_junto

    def extrair_arquivo(self, caminho_pdf: str | Path) -> ResultadoExtracao:
        """
        Extrai o texto completo e metadados de um arquivo PDF.

        Usa prioritariamente PyMuPDF (fitz) e faz fallback para pypdf se necessário.
        """
        caminho = Path(caminho_pdf)
        if not caminho.exists():
            raise FileNotFoundError(f"Arquivo PDF não encontrado: {caminho}")

        hash_arq = _calcular_sha256(caminho)
        tamanho = caminho.stat().st_size

        try:
            return self._extrair_com_pymupdf(caminho, hash_arq, tamanho)
        except Exception as e:
            logger.warning(
                "Falha ao extrair com PyMuPDF (%s): %s. Tentando fallback pypdf...",
                caminho.name,
                e,
            )
            return self._extrair_com_pypdf(caminho, hash_arq, tamanho)

    def _extrair_com_pymupdf(
        self, caminho: Path, hash_arq: str, tamanho: int
    ) -> ResultadoExtracao:
        """Extrai texto e imagens usando PyMuPDF."""
        import pymupdf

        doc = pymupdf.open(caminho)
        total_paginas = len(doc)
        paginas_info: list[PaginaInfo] = []
        paginas_requerem_ocr: list[int] = []
        textos_paginas: list[str] = []

        metadados = {
            "titulo": doc.metadata.get("title", ""),
            "autor": doc.metadata.get("author", ""),
            "criador": doc.metadata.get("creator", ""),
            "produtor": doc.metadata.get("producer", ""),
            "data_criacao": doc.metadata.get("creationDate", ""),
            "motor": "pymupdf",
        }

        for num_pag in range(total_paginas):
            pagina = doc[num_pag]
            texto_bruto = pagina.get_text() or ""
            texto_normalizado = normalizar_texto(texto_bruto)
            num_chars = len(texto_normalizado)

            # Contar imagens na página
            imagens = len(pagina.get_images())

            # Critério para OCR: texto muito curto ou vazio com imagens presentes
            requer_ocr = (num_chars < self.limiar_chars_ocr) and (imagens > 0 or num_chars == 0)

            if requer_ocr:
                paginas_requerem_ocr.append(num_pag + 1)

            paginas_info.append(
                PaginaInfo(
                    numero=num_pag + 1,
                    chars=num_chars,
                    imagens=imagens,
                    requer_ocr=requer_ocr,
                    texto=texto_normalizado,
                )
            )
            textos_paginas.append(texto_normalizado)

        doc.close()

        paginas_com_texto = sum(1 for p in paginas_info if p.chars >= self.limiar_chars_ocr)
        is_scanned = (total_paginas > 0) and (
            len(paginas_requerem_ocr) / total_paginas > 0.6
        )

        texto_completo = "\n\n--- PÁGINA ---\n\n".join(
            t for t in textos_paginas if t.strip()
        )

        return ResultadoExtracao(
            arquivo_origem=str(caminho.resolve()),
            nome_arquivo=caminho.name,
            hash_sha256=hash_arq,
            tamanho_bytes=tamanho,
            total_paginas=total_paginas,
            paginas_com_texto=paginas_com_texto,
            is_scanned=is_scanned,
            paginas_requerem_ocr=paginas_requerem_ocr,
            metadados=metadados,
            texto_completo=texto_completo,
            paginas=[asdict(p) for p in paginas_info],
        )

    def _extrair_com_pypdf(
        self, caminho: Path, hash_arq: str, tamanho: int
    ) -> ResultadoExtracao:
        """Fallback de extração usando a biblioteca pura pypdf."""
        from pypdf import PdfReader

        reader = PdfReader(caminho)
        total_paginas = len(reader.pages)
        paginas_info: list[PaginaInfo] = []
        paginas_requerem_ocr: list[int] = []
        textos_paginas: list[str] = []

        doc_info = reader.metadata or {}
        metadados = {
            "titulo": str(doc_info.get("/Title", "")),
            "autor": str(doc_info.get("/Author", "")),
            "criador": str(doc_info.get("/Creator", "")),
            "produtor": str(doc_info.get("/Producer", "")),
            "motor": "pypdf",
        }

        for num_pag, page in enumerate(reader.pages):
            try:
                texto_bruto = page.extract_text() or ""
            except Exception as e:
                logger.debug("Erro ao extrair página %d com pypdf: %s", num_pag + 1, e)
                texto_bruto = ""

            texto_normalizado = normalizar_texto(texto_bruto)
            num_chars = len(texto_normalizado)
            num_imagens = len(getattr(page, "images", []))

            requer_ocr = (num_chars < self.limiar_chars_ocr) and (num_imagens > 0 or num_chars == 0)
            if requer_ocr:
                paginas_requerem_ocr.append(num_pag + 1)

            paginas_info.append(
                PaginaInfo(
                    numero=num_pag + 1,
                    chars=num_chars,
                    imagens=num_imagens,
                    requer_ocr=requer_ocr,
                    texto=texto_normalizado,
                )
            )
            textos_paginas.append(texto_normalizado)

        paginas_com_texto = sum(1 for p in paginas_info if p.chars >= self.limiar_chars_ocr)
        is_scanned = (total_paginas > 0) and (
            len(paginas_requerem_ocr) / total_paginas > 0.6
        )

        texto_completo = "\n\n--- PÁGINA ---\n\n".join(
            t for t in textos_paginas if t.strip()
        )

        return ResultadoExtracao(
            arquivo_origem=str(caminho.resolve()),
            nome_arquivo=caminho.name,
            hash_sha256=hash_arq,
            tamanho_bytes=tamanho,
            total_paginas=total_paginas,
            paginas_com_texto=paginas_com_texto,
            is_scanned=is_scanned,
            paginas_requerem_ocr=paginas_requerem_ocr,
            metadados=metadados,
            texto_completo=texto_completo,
            paginas=[asdict(p) for p in paginas_info],
        )

    def salvar_resultado(
        self, resultado: ResultadoExtracao, dir_destino: str | Path
    ) -> Path:
        """
        Persiste o resultado estruturado em disco.

        Gera:
        - `<nome_arquivo>.json`: resultado estruturado completo.
        - `<nome_arquivo>.txt`: texto corrido (se salvar_txt_junto=True).
        """
        dir_dest = Path(dir_destino)
        dir_dest.mkdir(parents=True, exist_ok=True)

        nome_base = Path(resultado.nome_arquivo).stem
        caminho_json = dir_dest / f"{nome_base}.json"

        with open(caminho_json, "w", encoding="utf-8") as f:
            json.dump(resultado.to_dict(), f, ensure_ascii=False, indent=2)

        if self.salvar_txt_junto and resultado.texto_completo:
            caminho_txt = dir_dest / f"{nome_base}.txt"
            caminho_txt.write_text(resultado.texto_completo, encoding="utf-8")

        return caminho_json

    def processar_diretorio(
        self,
        dir_origem: str | Path,
        dir_destino: str | Path,
        forcar: bool = False,
        limite: int | None = None,
    ) -> dict[str, Any]:
        """
        Processa todos os PDFs encontrados em dir_origem e salva os resultados em dir_destino.

        Args:
            dir_origem: Diretório contendo os PDFs brutos.
            dir_destino: Diretório onde serão gravados os JSONs e TXTs.
            forcar: Se True, reprocessa mesmo se o JSON já existir.
            limite: Máximo de documentos a processar.

        Returns:
            Dicionário com estatísticas consolidadas do lote.
        """
        origem = Path(dir_origem)
        destino = Path(dir_destino)
        destino.mkdir(parents=True, exist_ok=True)

        if not origem.exists():
            logger.warning("Diretório de origem não existe: %s", origem)
            return {"encontrados": 0, "processados": 0}

        arquivos_pdf = sorted(list(origem.glob("*.pdf")))
        if limite:
            arquivos_pdf = arquivos_pdf[:limite]

        estatisticas = {
            "total_encontrados": len(arquivos_pdf),
            "processados": 0,
            "pulados": 0,
            "erros": 0,
            "requerem_ocr": 0,
            "arquivos": [],
        }

        logger.info(
            "Iniciando extração de texto para %d PDFs em %s...",
            len(arquivos_pdf),
            origem,
        )

        for pdf_path in tqdm(arquivos_pdf, desc="Extraindo texto", unit="doc"):
            nome_base = pdf_path.stem
            caminho_json = destino / f"{nome_base}.json"

            # Idempotência: pular se já existe
            if caminho_json.exists() and not forcar:
                logger.debug("Documento já processado, pulando: %s", pdf_path.name)
                estatisticas["pulados"] += 1
                continue

            try:
                res = self.extrair_arquivo(pdf_path)
                self.salvar_resultado(res, destino)

                estatisticas["processados"] += 1
                if res.is_scanned or len(res.paginas_requerem_ocr) > 0:
                    estatisticas["requerem_ocr"] += 1

                estatisticas["arquivos"].append(
                    {
                        "arquivo": pdf_path.name,
                        "paginas": res.total_paginas,
                        "chars": len(res.texto_completo),
                        "is_scanned": res.is_scanned,
                        "paginas_ocr": res.paginas_requerem_ocr,
                    }
                )
            except Exception as e:
                logger.error("Erro ao processar %s: %s", pdf_path.name, e)
                estatisticas["erros"] += 1

        logger.info(
            "Extração concluída: %d processados, %d pulados, %d erros, %d demandam OCR",
            estatisticas["processados"],
            estatisticas["pulados"],
            estatisticas["erros"],
            estatisticas["requerem_ocr"],
        )
        return estatisticas
