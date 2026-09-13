"""
Módulo de carga e sincronização de dados (Loader) para o banco de dados do Radar.

Lê os manifestos de ingestão (data/raw/) e os dossiês analíticos de QGC (data/processed/),
populando e atualizando as tabelas relacionais de forma idempotente.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

from src.banco.repositorio import BancoDados

logger = logging.getLogger(__name__)

DIR_DATA_RAW = Path("data/raw")
DIR_DATA_PROCESSED = Path("data/processed")


class LoaderDados:
    """Carrega dados persistidos em disco para o banco relacional."""

    def __init__(self, banco: BancoDados | None = None) -> None:
        self.banco = banco or BancoDados()
        self.banco.inicializar_schema()

    def carregar_manifesto_arquivo(self, caminho_manifesto: Path) -> dict[str, int]:
        """Lê um ingestion_manifest.json e registra empresa, processo e documentos."""
        if not caminho_manifesto.exists():
            return {"documentos": 0}

        try:
            with open(caminho_manifesto, "r", encoding="utf-8") as f:
                dados = json.load(f)
        except Exception as e:
            logger.error("Erro ao ler manifesto %s: %s", caminho_manifesto, e)
            return {"documentos": 0}

        fonte = dados.get("fonte", "desconhecida")
        slug_empresa = dados.get("empresa", caminho_manifesto.parent.name)

        # Mapeamento e criação da empresa
        nome_empresa = slug_empresa.replace("-", " ").title()
        empresa_id = self.banco.salvar_empresa(
            slug=slug_empresa,
            nome_razao_social=nome_empresa,
            origem_fonte=fonte,
        )

        # Mapeamento do processo correspondente
        slug_proc = f"proc-{slug_empresa}"
        proc_id = self.banco.salvar_processo(
            empresa_id=empresa_id,
            slug=slug_proc,
            administrador_judicial=fonte if "aj" in fonte else "",
        )

        # Inserção dos documentos listados no manifesto
        total_docs = 0
        arquivos = dados.get("arquivos", {})
        for nome_arq, meta in arquivos.items():
            if not isinstance(meta, dict):
                continue

            status = meta.get("status", "")
            if status not in ("sucesso", "baixado"):
                continue

            caminho_salvo = meta.get("caminho", "")
            sha256 = meta.get("sha256", "")
            url = meta.get("url", "")
            tamanho = meta.get("bytes", 0)
            categoria = meta.get("categoria") or meta.get("tipo") or "OUTROS"

            self.banco.salvar_documento(
                empresa_id=empresa_id,
                processo_id=proc_id,
                titulo=nome_arq,
                categoria=categoria,
                url_download=url,
                caminho_arquivo=caminho_salvo,
                sha256=sha256,
                tamanho_bytes=tamanho,
            )
            total_docs += 1

        return {"empresa_id": empresa_id, "processo_id": proc_id, "documentos": total_docs}

    def carregar_qgc_arquivo(
        self, caminho_qgc_json: Path, slug_empresa: str | None = None
    ) -> int:
        """
        Lê um arquivo de resultado estruturado de credores (*_credores.json)
        e persiste todos os registros de credores na tabela 'credores'.
        """
        if not caminho_qgc_json.exists():
            return 0

        try:
            with open(caminho_qgc_json, "r", encoding="utf-8") as f:
                dados = json.load(f)
        except Exception as e:
            logger.error("Erro ao carregar QGC JSON %s: %s", caminho_qgc_json, e)
            return 0

        nome_arquivo = dados.get("nome_arquivo", caminho_qgc_json.name)
        credores = dados.get("credores", [])
        if not credores:
            return 0

        # Inferir slug da empresa a partir do caminho se não fornecido
        if not slug_empresa:
            partes = list(caminho_qgc_json.parts)
            if "qgc" in partes:
                idx = partes.index("qgc")
                slug_empresa = partes[idx - 1] if idx > 0 else "recuperanda-desconhecida"
            else:
                slug_empresa = "recuperanda-desconhecida"

        # Garantir empresa e processo existentes
        empresa_id = self.banco.salvar_empresa(
            slug=slug_empresa,
            nome_razao_social=slug_empresa.replace("-", " ").title(),
        )
        proc_id = self.banco.salvar_processo(
            empresa_id=empresa_id,
            slug=f"proc-{slug_empresa}",
        )

        # Registrar documento do QGC
        doc_id = self.banco.salvar_documento(
            empresa_id=empresa_id,
            processo_id=proc_id,
            titulo=nome_arquivo,
            categoria="QGC",
            caminho_arquivo=str(caminho_qgc_json),
            total_paginas=dados.get("metadados", {}).get("paginas_pdf", 0),
        )

        # Salvar credores em lote
        total_salvos = self.banco.salvar_credores_lote(
            credores=credores,
            processo_id=proc_id,
            documento_id=doc_id,
        )

        logger.info(
            "[%s] Carregados %d credores para empresa '%s' a partir de %s",
            slug_empresa,
            total_salvos,
            slug_empresa,
            caminho_qgc_json.name,
        )
        return total_salvos

    def sincronizar_tudo(
        self,
        dir_raw: Path = DIR_DATA_RAW,
        dir_processed: Path = DIR_DATA_PROCESSED,
    ) -> dict[str, int]:
        """Varre recursivamente todo o repositório local e popula o banco de dados."""
        logger.info("Iniciando sincronização completa de dados para o banco...")

        # 1. Carregar manifestos
        manifestos = list(dir_raw.glob("**/ingestion_manifest.json"))
        logger.info("Encontrados %d manifestos de ingestão em %s", len(manifestos), dir_raw)
        total_docs_carregados = 0
        for m in manifestos:
            res = self.carregar_manifesto_arquivo(m)
            total_docs_carregados += res.get("documentos", 0)

        # 2. Carregar arquivos de credores QGC
        qgcs = list(dir_processed.glob("**/*_credores.json"))
        logger.info("Encontrados %d arquivos de QGC estruturado em %s", len(qgcs), dir_processed)
        total_credores_carregados = 0
        for q in qgcs:
            total_credores_carregados += self.carregar_qgc_arquivo(q)

        stats = self.banco.obter_estatisticas_gerais()
        logger.info("Sincronização concluída com sucesso!")
        logger.info("Estatísticas atuais do Banco de Dados:")
        for k, v in stats.items():
            logger.info("  • %-20s: %d", k, v)

        return stats


def main(argv: list[str] | None = None) -> None:
    """CLI para sincronização de dados no banco."""
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)-5s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    parser = argparse.ArgumentParser(
        prog="loader",
        description="Sincronizador de dados do Radar para banco relacional SQLite/PostgreSQL.",
    )
    parser.add_argument(
        "--db",
        type=str,
        default=None,
        help="Caminho personalizado do banco SQLite (padrão: data/radar.db).",
    )
    parser.add_argument(
        "--tudo",
        action="store_true",
        help="Sincroniza todos os manifestos e arquivos de QGC do repositório.",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Exibe as estatísticas atuais do banco de dados.",
    )
    args = parser.parse_args(argv)

    banco = BancoDados(args.db) if args.db else BancoDados()
    loader = LoaderDados(banco)

    if args.stats:
        stats = banco.obter_estatisticas_gerais()
        print("\n--- ESTATÍSTICAS DO RADAR ---")
        for k, v in stats.items():
            print(f"  {k}: {v}")
        return

    loader.sincronizar_tudo()


if __name__ == "__main__":
    main()
