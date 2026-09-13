"""
Repositório de acesso e manipulação do banco de dados relacional do Radar.

Oferece transações seguras, suporte a SQLite local e in-memory para testes,
além de consultas analíticas para fundos de crédito e investidores.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

from src.banco.schema import DDL_SCHEMA

logger = logging.getLogger(__name__)

DIR_PADRAO_BANCO = Path("data")
CAMINHO_PADRAO_DB = DIR_PADRAO_BANCO / "radar.db"


class BancoDados:
    """Gerenciador de conexão e repositório de dados do Radar."""

    def __init__(self, db_path: str | Path = CAMINHO_PADRAO_DB) -> None:
        if str(db_path) == ":memory:":
            self.caminho = ":memory:"
        else:
            self.caminho = Path(db_path)
            self.caminho.parent.mkdir(parents=True, exist_ok=True)

        self._conn: sqlite3.Connection | None = None

    def conectar(self) -> sqlite3.Connection:
        """Abre ou reutiliza conexão com SQLite habilitando foreign keys e dict rows."""
        if self._conn is None:
            self._conn = sqlite3.connect(
                str(self.caminho),
                timeout=30.0,
                check_same_thread=False,
            )
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA foreign_keys = ON;")
            self._conn.execute("PRAGMA journal_mode = WAL;")
        return self._conn

    def fechar(self) -> None:
        """Fecha a conexão com o banco de dados."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> BancoDados:
        self.conectar()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.fechar()

    def inicializar_schema(self) -> None:
        """Executa o DDL de criação de tabelas e índices."""
        conn = self.conectar()
        with conn:
            conn.executescript(DDL_SCHEMA)
        logger.info("Schema do banco de dados inicializado em: %s", self.caminho)

    # --------------------------------------------------------------------------
    # EMPRESAS
    # --------------------------------------------------------------------------
    def salvar_empresa(
        self,
        slug: str,
        nome_razao_social: str,
        cnpj: str = "",
        setor: str = "",
        origem_fonte: str = "manual",
    ) -> int:
        """Insere ou atualiza uma empresa pelo slug único e retorna seu ID."""
        conn = self.conectar()
        with conn:
            cur = conn.execute(
                """
                INSERT INTO empresas (slug, nome_razao_social, cnpj, setor, origem_fonte, atualizado_em)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(slug) DO UPDATE SET
                    nome_razao_social = excluded.nome_razao_social,
                    cnpj = COALESCE(NULLIF(excluded.cnpj, ''), empresas.cnpj),
                    setor = COALESCE(NULLIF(excluded.setor, ''), empresas.setor),
                    atualizado_em = CURRENT_TIMESTAMP
                RETURNING id;
                """,
                (slug, nome_razao_social, cnpj, setor, origem_fonte),
            )
            row = cur.fetchone()
            return int(row["id"])

    def obter_empresa_por_slug(self, slug: str) -> dict[str, Any] | None:
        """Recupera metadados da empresa pelo slug."""
        conn = self.conectar()
        cur = conn.execute("SELECT * FROM empresas WHERE slug = ?;", (slug,))
        row = cur.fetchone()
        return dict(row) if row else None

    # --------------------------------------------------------------------------
    # PROCESSOS
    # --------------------------------------------------------------------------
    def salvar_processo(
        self,
        empresa_id: int,
        slug: str,
        numero_cnj: str = "",
        vara_comarca: str = "",
        administrador_judicial: str = "",
        tipo_processo: str = "recuperacao_judicial",
        url_detalhe: str = "",
    ) -> int:
        """Insere ou atualiza um processo judicial pelo slug único."""
        conn = self.conectar()
        with conn:
            cur = conn.execute(
                """
                INSERT INTO processos (
                    empresa_id, slug, numero_cnj, vara_comarca, administrador_judicial,
                    tipo_processo, url_detalhe
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(slug) DO UPDATE SET
                    numero_cnj = COALESCE(NULLIF(excluded.numero_cnj, ''), processos.numero_cnj),
                    vara_comarca = COALESCE(NULLIF(excluded.vara_comarca, ''), processos.vara_comarca),
                    administrador_judicial = COALESCE(NULLIF(excluded.administrador_judicial, ''), processos.administrador_judicial),
                    url_detalhe = COALESCE(NULLIF(excluded.url_detalhe, ''), processos.url_detalhe)
                RETURNING id;
                """,
                (
                    empresa_id,
                    slug,
                    numero_cnj,
                    vara_comarca,
                    administrador_judicial,
                    tipo_processo,
                    url_detalhe,
                ),
            )
            row = cur.fetchone()
            return int(row["id"])

    def obter_processo_por_slug(self, slug: str) -> dict[str, Any] | None:
        conn = self.conectar()
        cur = conn.execute("SELECT * FROM processos WHERE slug = ?;", (slug,))
        row = cur.fetchone()
        return dict(row) if row else None

    # --------------------------------------------------------------------------
    # DOCUMENTOS
    # --------------------------------------------------------------------------
    def salvar_documento(
        self,
        empresa_id: int,
        titulo: str,
        categoria: str,
        processo_id: int | None = None,
        slug_documento: str = "",
        url_download: str = "",
        caminho_arquivo: str = "",
        sha256: str = "",
        total_paginas: int = 0,
        is_scanned: bool = False,
        tamanho_bytes: int = 0,
    ) -> int:
        """Registra um documento em PDF coletado ou processado."""
        conn = self.conectar()
        with conn:
            cur = conn.execute(
                """
                INSERT INTO documentos (
                    processo_id, empresa_id, slug_documento, titulo, categoria,
                    url_download, caminho_arquivo, sha256, total_paginas,
                    is_scanned, tamanho_bytes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                RETURNING id;
                """,
                (
                    processo_id,
                    empresa_id,
                    slug_documento,
                    titulo,
                    categoria,
                    url_download,
                    caminho_arquivo,
                    sha256,
                    total_paginas,
                    1 if is_scanned else 0,
                    tamanho_bytes,
                ),
            )
            row = cur.fetchone()
            return int(row["id"])

    # --------------------------------------------------------------------------
    # CREDORES (QGC)
    # --------------------------------------------------------------------------
    def salvar_credores_lote(
        self,
        credores: list[dict[str, Any]],
        processo_id: int | None = None,
        documento_id: int | None = None,
    ) -> int:
        """
        Insere uma lista de credores em lote com transação atômica.
        Retorna o total de credores inseridos.
        """
        if not credores:
            return 0

        conn = self.conectar()
        registros = [
            (
                processo_id,
                documento_id,
                str(c.get("nome", "")).strip(),
                c.get("documento", ""),
                c.get("documento_limpo", ""),
                c.get("tipo_documento", "DESCONHECIDO"),
                c.get("classe", "III - Quirografário"),
                c.get("natureza", ""),
                float(c.get("valor", 0.0)),
                c.get("moeda", "BRL"),
                c.get("cidade", ""),
                c.get("uf", ""),
                int(c.get("pagina", 1)),
            )
            for c in credores
        ]

        with conn:
            conn.executemany(
                """
                INSERT INTO credores (
                    processo_id, documento_id, nome, documento_formatado,
                    documento_limpo, tipo_documento, classe, natureza,
                    valor_original, moeda, cidade, uf, pagina_origem
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                registros,
            )

        logger.info(
            "Lote de %d credores inserido no banco (Processo ID: %s, Doc ID: %s)",
            len(registros),
            processo_id,
            documento_id,
        )
        return len(registros)

    # --------------------------------------------------------------------------
    # CONSULTAS ANALÍTICAS
    # --------------------------------------------------------------------------
    def obter_resumo_passivo_empresa(self, empresa_slug: str) -> dict[str, Any]:
        """
        Retorna consolidação financeira da dívida de uma empresa:
        valor total apurado, quantidade de credores e soma por classe jurídica.
        """
        conn = self.conectar()
        query = """
        SELECT
            c.classe,
            COUNT(c.id) as total_credores,
            SUM(c.valor_original) as valor_total
        FROM credores c
        JOIN processos p ON c.processo_id = p.id
        JOIN empresas e ON p.empresa_id = e.id
        WHERE e.slug = ?
        GROUP BY c.classe
        ORDER BY valor_total DESC;
        """
        cur = conn.execute(query, (empresa_slug,))
        linhas = cur.fetchall()

        totais_por_classe: dict[str, float] = {}
        qtd_por_classe: dict[str, int] = {}
        valor_total_geral = 0.0
        total_credores_geral = 0

        for r in linhas:
            classe = str(r["classe"])
            v = float(r["valor_total"] or 0.0)
            q = int(r["total_credores"] or 0)
            totais_por_classe[classe] = round(v, 2)
            qtd_por_classe[classe] = q
            valor_total_geral += v
            total_credores_geral += q

        return {
            "empresa_slug": empresa_slug,
            "total_credores": total_credores_geral,
            "valor_total_apurado": round(valor_total_geral, 2),
            "totais_por_classe": totais_por_classe,
            "quantidade_por_classe": qtd_por_classe,
        }

    def buscar_credores(
        self,
        nome: str = "",
        documento: str = "",
        classe: str = "",
        valor_minimo: float = 0.0,
        limite: int = 50,
    ) -> list[dict[str, Any]]:
        """
        Busca credores por filtros combinados (Nome, CPF/CNPJ, Classe, Faixa de Valor).
        """
        conn = self.conectar()
        condicoes = ["1=1"]
        params: list[Any] = []

        if nome:
            condicoes.append("c.nome LIKE ?")
            params.append(f"%{nome}%")

        if documento:
            doc_limpo = "".join(filter(str.isdigit, documento))
            if doc_limpo:
                condicoes.append("(c.documento_limpo = ? OR c.documento_formatado LIKE ?)")
                params.extend([doc_limpo, f"%{documento}%"])
            else:
                condicoes.append("c.documento_formatado LIKE ?")
                params.append(f"%{documento}%")

        if classe:
            condicoes.append("c.classe LIKE ?")
            params.append(f"%{classe}%")

        if valor_minimo > 0:
            condicoes.append("c.valor_original >= ?")
            params.append(valor_minimo)

        clausula_where = " AND ".join(condicoes)
        params.append(limite)

        sql = f"""
        SELECT
            c.id,
            e.nome_razao_social as empresa_recuperanda,
            p.numero_cnj,
            c.nome as credor_nome,
            c.documento_formatado,
            c.tipo_documento,
            c.classe,
            c.valor_original,
            c.natureza,
            c.cidade,
            c.uf,
            c.pagina_origem
        FROM credores c
        LEFT JOIN processos p ON c.processo_id = p.id
        LEFT JOIN empresas e ON p.empresa_id = e.id
        WHERE {clausula_where}
        ORDER BY c.valor_original DESC
        LIMIT ?;
        """

        cur = conn.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]

    def ranking_maiores_credores(self, limite: int = 10) -> list[dict[str, Any]]:
        """Retorna os maiores créditos individuais cadastrados no banco."""
        return self.buscar_credores(limite=limite)

    def obter_estatisticas_gerais(self) -> dict[str, int]:
        """Retorna contagem total de registros no banco."""
        conn = self.conectar()
        cur = conn.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM empresas) as total_empresas,
                (SELECT COUNT(*) FROM processos) as total_processos,
                (SELECT COUNT(*) FROM documentos) as total_documentos,
                (SELECT COUNT(*) FROM credores) as total_credores;
            """
        )
        row = cur.fetchone()
        return dict(row) if row else {}
