"""
CLI orquestradora do pipeline de ingestão.

Uso:
  python -m src.ingestao.cli --extrator cvm-dfp --empresa oi --dry-run
  python -m src.ingestao.cli --extrator todos
  python -m src.ingestao.cli --help

Ordem de execução (conforme D4):
  1. CVM DFP/ITR  (mais estável)
  2. CVM IPE
  3. ITD
  4. e-SAJ        (mais frágil)
"""

from __future__ import annotations

import argparse
import logging
import sys
import time

from src.ingestao import cvm_dfp_itr, cvm_ipe, esaj_tjsp, itd_acordaos
from src.ingestao.aj import brizola as aj_brizola, exm as aj_exm, ruiz as aj_ruiz
from src.ingestao.download import RAIZ_PROJETO, carregar_config_empresas
from src.ingestao.tribunais import pipeline as tribunais_pipeline

# Carregar variáveis de ambiente de .env se existir
try:
    from dotenv import load_dotenv

    load_dotenv(RAIZ_PROJETO / ".env")
except ImportError:
    pass

# Mapeamento de nomes CLI → módulos
EXTRATORES = {
    "cvm-dfp": ("CVM DFP/ITR", cvm_dfp_itr),
    "cvm-ipe": ("CVM IPE", cvm_ipe),
    "aj-exm": ("AJ EXM Partners", aj_exm),
    "aj-ruiz": ("AJ Ruiz", aj_ruiz),
    "aj-brizola": ("AJ Brizola e Japur", aj_brizola),
    "tribunais": ("Radar de Tribunais de Justiça", tribunais_pipeline),
    "itd": ("ITD Acórdãos", itd_acordaos),
    "esaj": ("e-SAJ TJSP (Legado)", esaj_tjsp),
}

ORDEM_EXECUCAO = ["cvm-dfp", "cvm-ipe", "aj-exm", "aj-ruiz", "aj-brizola", "tribunais", "itd"]


def obter_slugs_validos() -> list[str]:
    """Retorna dinamicamente os slugs das empresas cadastradas em config/empresas.yaml."""
    try:
        config = carregar_config_empresas()
        slugs = [
            emp["slug"]
            for emp in config.get("empresas", [])
            if isinstance(emp, dict) and "slug" in emp
        ]
        if slugs:
            return slugs
    except Exception as e:
        logging.getLogger("ingestao.cli").warning(
            "Não foi possível carregar empresas.yaml (%s). Usando fallback de slugs.", e
        )
    return ["oi", "americanas", "light"]


def _configurar_logging(verbose: bool = False, salvar_arquivo: bool = True) -> None:
    """Configura logging com formatação padronizada para console e arquivo em logs/."""
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    nivel = logging.DEBUG if verbose else logging.INFO
    formato = "%(asctime)s [%(levelname)-5s] %(name)s: %(message)s"
    data_formato = "%Y-%m-%d %H:%M:%S"

    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]

    if salvar_arquivo:
        dir_logs = RAIZ_PROJETO / "logs"
        dir_logs.mkdir(parents=True, exist_ok=True)
        hoje = time.strftime("%Y-%m-%d")
        caminho_log = dir_logs / f"ingestao_{hoje}.log"
        handlers.append(logging.FileHandler(caminho_log, encoding="utf-8"))

    root_logger = logging.getLogger()
    root_logger.setLevel(nivel)
    for h in list(root_logger.handlers):
        root_logger.removeHandler(h)

    formatter = logging.Formatter(fmt=formato, datefmt=data_formato)
    for h in handlers:
        h.setFormatter(formatter)
        root_logger.addHandler(h)


def _criar_parser() -> argparse.ArgumentParser:
    """Cria o parser de argumentos CLI."""
    parser = argparse.ArgumentParser(
        prog="ingerir",
        description=(
            "Pipeline de ingestão de dados públicos para o Radar de "
            "Oportunidades em Recuperação de Ativos."
        ),
    )
    slugs_validos = obter_slugs_validos()
    parser.add_argument(
        "--extrator",
        choices=list(EXTRATORES.keys()) + ["todos"],
        default="todos",
        help="Extrator a executar (default: todos, na ordem D4).",
    )
    parser.add_argument(
        "--empresa",
        default="todas",
        help=f"Empresa/processo a processar (cadastradas: {slugs_validos}, ou slug específico de AJ, default: todas).",
    )
    parser.add_argument(
        "--ano",
        type=int,
        default=None,
        help="Ano específico a processar (default: todos na janela temporal).",
    )
    parser.add_argument(
        "--limite",
        type=int,
        default=None,
        help="Limite máximo de documentos por empresa (ou processos no caso de AJ).",
    )
    parser.add_argument(
        "--processo",
        type=str,
        default=None,
        help="Número de processo CNJ específico para consulta em tribunais (ex: 1024564-80.2024.8.26.0100).",
    )
    parser.add_argument(
        "--tribunais",
        type=str,
        default="tjsp",
        help="Siglas de tribunais separadas por vírgula para o radar nacional (default: tjsp).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Mostra o que faria sem baixar nada.",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Logging detalhado (DEBUG).",
    )
    parser.add_argument(
        "--no-log-file",
        action="store_true",
        help="Desativa a gravação de logs em arquivo (pasta logs/).",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    """Ponto de entrada principal da CLI."""
    parser = _criar_parser()
    args = parser.parse_args(argv)

    _configurar_logging(verbose=args.verbose, salvar_arquivo=not args.no_log_file)
    logger = logging.getLogger("ingestao.cli")

    # Resolver filtros
    slugs = None if args.empresa == "todas" else [args.empresa]
    extratores = ORDEM_EXECUCAO if args.extrator == "todos" else [args.extrator]
    anos = [args.ano] if args.ano else None
    lista_tribunais = [t.strip().lower() for t in args.tribunais.split(",") if t.strip()]

    logger.info("=" * 70)
    logger.info("PIPELINE DE INGESTÃO — Radar de Oportunidades")
    logger.info("=" * 70)
    logger.info("Extratores: %s", extratores)
    logger.info("Empresas: %s", slugs or "todas")
    if args.processo:
        logger.info("Processo CNJ Alvo: %s", args.processo)
    if "tribunais" in extratores:
        logger.info("Tribunais Rastreamento: %s", lista_tribunais)
    if anos:
        logger.info("Ano: %s", anos)
    if args.limite:
        logger.info("Limite de documentos: %d", args.limite)
    logger.info("Dry-run: %s", args.dry_run)
    logger.info("=" * 70)

    inicio = time.time()
    resultados = {}

    for nome_extrator in extratores:
        nome_display, modulo = EXTRATORES[nome_extrator]

        logger.info("")
        logger.info("-" * 50)
        logger.info("> Extrator: %s", nome_display)
        logger.info("-" * 50)

        try:
            if nome_extrator == "itd":
                # ITD não recebe filtro de empresa (é amostra genérica)
                resultado = modulo.executar(dry_run=args.dry_run)
            elif nome_extrator == "esaj":
                resultado = modulo.executar(
                    slugs_empresa=slugs, dry_run=args.dry_run
                )
            elif nome_extrator == "tribunais":
                resultado = modulo.executar(
                    processo=args.processo,
                    tribunais=lista_tribunais,
                    limite=args.limite,
                    dry_run=args.dry_run,
                )
            elif nome_extrator == "cvm-dfp":
                resultado = modulo.executar(
                    slugs_empresa=slugs, anos=anos, dry_run=args.dry_run
                )
            elif nome_extrator == "cvm-ipe":
                resultado = modulo.executar(
                    slugs_empresa=slugs,
                    anos=anos,
                    max_documentos=args.limite,
                    dry_run=args.dry_run,
                )
            elif nome_extrator in ("aj-exm", "aj-ruiz", "aj-brizola"):
                resultado = modulo.executar(
                    slugs_empresa=slugs,
                    limite=args.limite,
                    limite_docs=args.limite if slugs else None,
                    dry_run=args.dry_run,
                )
            else:
                resultado = modulo.executar(
                    slugs_empresa=slugs, dry_run=args.dry_run
                )

            resultados[nome_extrator] = resultado
            logger.info("[OK] %s concluido: %s", nome_display, resultado)

            # Pausa de cortesia entre extratores se executando múltiplos
            if len(extratores) > 1 and nome_extrator != extratores[-1] and not args.dry_run:
                logger.info("Aguardando 1.5s antes do próximo extrator...")
                time.sleep(1.5)

        except Exception as e:
            logger.error("[FALHA] %s falhou: %s", nome_display, e, exc_info=True)
            resultados[nome_extrator] = f"ERRO: {e}"

    # Resumo final
    duracao = time.time() - inicio
    logger.info("")
    logger.info("=" * 70)
    logger.info("RESUMO FINAL (%.1fs)", duracao)
    logger.info("=" * 70)
    for ext, res in resultados.items():
        logger.info("  %s: %s", ext, res)
    logger.info("=" * 70)


if __name__ == "__main__":
    main()
