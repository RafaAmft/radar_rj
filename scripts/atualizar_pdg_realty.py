"""
Script para sincronizar e corrigir os dados oficiais da PDG Realty no banco radar.db.
"""

import sqlite3
from src.banco.repositorio import BancoDados
from src.dados.catalogo_top50 import CATALOGO_TOP_50_RJS
from src.dados.links_util import resolver_link_documento_marco

def atualizar_pdg(db_path: str = "data/radar.db"):
    banco = BancoDados(db_path)
    conn = banco.conectar()

    # Localizar caso PDG no catálogo
    caso_pdg = next((c for c in CATALOGO_TOP_50_RJS if c["slug"] == "pdg-realty"), None)
    if not caso_pdg:
        print("Erro: Caso PDG não encontrado no catálogo.")
        return

    with conn:
        # Atualizar tabela de processos
        conn.execute(
            """
            UPDATE processos
            SET valor_causa = ?,
                status_processual = ?,
                administrador_judicial = ?,
                url_detalhe = ?
            WHERE slug = 'proc-pdg-realty' OR numero_cnj LIKE '%1016422-34.2017.8.26.0100%';
            """,
            (
                caso_pdg["valor_causa"],
                caso_pdg["status_processual"],
                caso_pdg["administrador_judicial"],
                caso_pdg["url_detalhe"],
            ),
        )

        # Buscar ID do processo
        cur = conn.execute("SELECT id, empresa_id FROM processos WHERE slug = 'proc-pdg-realty' OR numero_cnj LIKE '%1016422-34.2017.8.26.0100%'")
        row = cur.fetchone()
        if not row:
            print("Processo da PDG não localizado no banco.")
            return

        processo_id = int(row["id"])
        empresa_id = int(row["empresa_id"])

        # Remover marcos e documentos antigos/incompletos deste processo
        conn.execute("DELETE FROM marcos_processuais WHERE processo_id = ?", (processo_id,))
        conn.execute("DELETE FROM documentos WHERE processo_id = ?", (processo_id,))

        # Inserir os novos marcos históricos reais e oficiais
        for idx, m in enumerate(caso_pdg["marcos"], 1):
            url_resolvida = resolver_link_documento_marco(
                url_existente=m.get("url_documento", ""),
                numero_cnj=caso_pdg["numero_cnj"],
                tribunal=caso_pdg["tribunal"],
                empresa_slug="pdg-realty",
                tipo_evento=m.get("tipo_evento", ""),
                autor=m.get("autor", "AJ"),
            )

            conn.execute(
                """
                INSERT INTO marcos_processuais (
                    processo_id, data_evento, tipo_evento, titulo, descricao, autor, url_documento
                ) VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    processo_id,
                    m["data_evento"],
                    m["tipo_evento"],
                    m["titulo"],
                    m["descricao"],
                    m["autor"],
                    url_resolvida,
                ),
            )

            # Inserir também em documentos
            cat = "CVM_FATO_RELEVANTE" if "CVM" in m["tipo_evento"] else ("DECISAO" if "DECISAO" in m["tipo_evento"] or "HOMOLOGACAO" in m["tipo_evento"] else "INICIAL")
            conn.execute(
                """
                INSERT INTO documentos (
                    processo_id, empresa_id, slug_documento, titulo, categoria,
                    url_download, caminho_arquivo, sha256, total_paginas, is_scanned, tamanho_bytes
                ) VALUES (?, ?, ?, ?, ?, ?, '', '', 0, 0, 0);
                """,
                (
                    processo_id,
                    empresa_id,
                    f"doc-pdg-{m['data_evento']}-{idx}",
                    m["titulo"],
                    cat,
                    url_resolvida,
                ),
            )

    print(f"Sucesso! PDG atualizada com {len(caso_pdg['marcos'])} marcos e documentos no radar.db.")

if __name__ == "__main__":
    atualizar_pdg()
