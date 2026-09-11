"""
CLI para processamento e extração de texto de documentos PDF.

Uso:
  python -m src.processamento.cli --empresa oi
  python -m src.processamento.cli --arquivo data/raw/oi/cvm/ipe/doc.pdf
  python -m src.processamento.cli --empresa todas
  python -m src.processamento.cli --help
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from src.ingestao.cli import obter_slugs_validos
from src.processamento.extrator_texto import (
    DIR_DATA_PROCESSED,
    DIR_DATA_RAW,
    RAIZ_PROJETO,
    ExtratorTextoPDF,
)

logger = logging.getLogger("processamento.cli")


def _configurar_logging(verbose: bool = False) -> None:
    """Configura logging para o processamento de texto."""
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    nivel = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=nivel,
        format="%(asctime)s [%(levelname)-5s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def _criar_parser() -> argparse.ArgumentParser:
    """Cria parser de argumentos da CLI de processamento."""
    parser = argparse.ArgumentParser(
        prog="processar",
        description="Motor de extração de texto e detecção de OCR para PDFs do Radar de Recuperação de Ativos.",
    )
    slugs = obter_slugs_validos()
    parser.add_argument(
        "--empresa",
        choices=slugs + ["todas"],
        default=None,
        help="Empresa a processar documentos em data/raw/<empresa>/ (default: None).",
    )
    parser.add_argument(
        "--arquivo",
        type=str,
        default=None,
        help="Caminho de um PDF específico para extração direta.",
    )
    parser.add_argument(
        "--dir-saida",
        type=str,
        default=None,
        help="Diretório de saída personalizado para gravação dos textos extraídos.",
    )
    parser.add_argument(
        "--forcar",
        action="store_true",
        help="Reprocessa documentos mesmo se já existirem em data/processed/.",
    )
    parser.add_argument(
        "--limite",
        type=int,
        default=None,
        help="Limite máximo de PDFs a processar por empresa.",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Habilita logs detalhados (DEBUG).",
    )
    return parser


def processar_empresa(
    slug: str, forcar: bool = False, limite: int | None = None
) -> dict:
    """Varre e processa todas as pastas de PDFs de uma empresa."""
    dir_empresa_raw = DIR_DATA_RAW / slug
    dir_empresa_dest = DIR_DATA_PROCESSED / slug / "textos"

    if not dir_empresa_raw.exists():
        logger.warning("Pasta da empresa não encontrada: %s", dir_empresa_raw)
        return {"total_encontrados": 0, "processados": 0}

    # Coletar recursivamente todos os PDFs da empresa (CVM IPE, editais, etc.)
    todos_pdfs = sorted(list(dir_empresa_raw.glob("**/*.pdf")))
    if not todos_pdfs:
        logger.info("Nenhum PDF encontrado em %s", dir_empresa_raw)
        return {"total_encontrados": 0, "processados": 0}

    if limite:
        todos_pdfs = todos_pdfs[:limite]

    extrator = ExtratorTextoPDF()
    total = len(todos_pdfs)
    processados = 0
    pulados = 0
    erros = 0
    requerem_ocr = 0

    logger.info("Encontrados %d PDFs para '%s'...", total, slug)

    for pdf in todos_pdfs:
        caminho_json = dir_empresa_dest / f"{pdf.stem}.json"
        if caminho_json.exists() and not forcar:
            pulados += 1
            continue

        try:
            res = extrator.extrair_arquivo(pdf)
            extrator.salvar_resultado(res, dir_empresa_dest)
            processados += 1
            if res.is_scanned or len(res.paginas_requerem_ocr) > 0:
                requerem_ocr += 1
            logger.info(
                "[OK] %s: %d págs, %d chars (OCR: %s)",
                pdf.name[:45] + "..." if len(pdf.name) > 48 else pdf.name,
                res.total_paginas,
                len(res.texto_completo),
                res.is_scanned or bool(res.paginas_requerem_ocr),
            )
        except Exception as e:
            logger.error("Falha ao processar %s: %s", pdf.name, e)
            erros += 1

    return {
        "empresa": slug,
        "total": total,
        "processados": processados,
        "pulados": pulados,
        "erros": erros,
        "requerem_ocr": requerem_ocr,
    }


def main(argv: list[str] | None = None) -> None:
    """Ponto de entrada principal da CLI de processamento."""
    parser = _criar_parser()
    args = parser.parse_args(argv)

    _configurar_logging(args.verbose)

    if not args.empresa and not args.arquivo:
        parser.print_help()
        sys.exit(1)

    inicio = time.time()
    extrator = ExtratorTextoPDF()

    if args.arquivo:
        caminho = Path(args.arquivo)
        if not caminho.exists():
            logger.error("Arquivo não encontrado: %s", caminho)
            sys.exit(1)

        logger.info("Processando arquivo avulso: %s", caminho)
        res = extrator.extrair_arquivo(caminho)
        destino = Path(args.dir_saida) if args.dir_saida else (DIR_DATA_PROCESSED / "_avulsos" / "textos")
        caminho_salvo = extrator.salvar_resultado(res, destino)

        logger.info("=" * 60)
        logger.info("Processamento concluído com sucesso!")
        logger.info("Arquivo: %s", res.nome_arquivo)
        logger.info("Páginas: %d (Com texto: %d)", res.total_paginas, res.paginas_com_texto)
        logger.info("Tamanho do texto extraído: %d caracteres", len(res.texto_completo))
        logger.info("Documento escaneado: %s", res.is_scanned)
        logger.info("Páginas demandando OCR: %s", res.paginas_requerem_ocr or "Nenhuma")
        logger.info("Salvo em: %s", caminho_salvo)
        logger.info("=" * 60)
        return

    # Processar empresas
    empresas = (
        obter_slugs_validos() if args.empresa == "todas" else [args.empresa]
    )

    logger.info("=" * 70)
    logger.info("MOTOR DE EXTRAÇÃO DE TEXTO & OCR — Fase 2")
    logger.info("=" * 70)
    logger.info("Empresas: %s", empresas)
    logger.info("Forçar reprocessamento: %s", args.forcar)
    if args.limite:
        logger.info("Limite por empresa: %d", args.limite)
    logger.info("=" * 70)

    resultados = []
    for slug in empresas:
        res = processar_empresa(slug, forcar=args.forcar, limite=args.limite)
        resultados.append(res)

    duracao = time.time() - inicio
    logger.info("")
    logger.info("=" * 70)
    logger.info("RESUMO FINAL DO PROCESSAMENTO (%.2fs)", duracao)
    logger.info("=" * 70)
    for r in resultados:
        logger.info(
            "  Empresa '%s': %d encontrados, %d processados, %d pulados, %d erros, %d demandam OCR",
            r.get("empresa"),
            r.get("total", 0),
            r.get("processados", 0),
            r.get("pulados", 0),
            r.get("erros", 0),
            r.get("requerem_ocr", 0),
        )
    logger.info("=" * 70)


if __name__ == "__main__":
    main()
