"""
Script para sincronizar movimentações estratégicas do e-SAJ diretamente para o radar.db.
"""

from __future__ import annotations

import logging
from src.banco.repositorio import BancoDados
from src.dados.links_util import resolver_link_tribunal
from src.ingestao.tribunais.esaj import ConsultorEsaj

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("SyncEsaj")


def sincronizar_processo_esaj(
    processo_id: int,
    db_path: str = "data/radar.db",
    url_custom: str | None = None,
    max_paginas: int = 5,
) -> int:
    """Extrai e persiste movimentações relevantes do e-SAJ para um processo específico."""
    banco = BancoDados(db_path)
    consultor = ConsultorEsaj()

    conn = banco.conectar()
    cur = conn.execute(
        "SELECT id, empresa_id, numero_cnj, tribunal, url_detalhe FROM processos WHERE id = ?",
        (processo_id,),
    )
    proc = cur.fetchone()
    if not proc:
        logger.warning("Processo ID %d não encontrado no banco.", processo_id)
        return 0

    numero_cnj = proc["numero_cnj"]
    tribunal = proc["tribunal"] or "TJSP"
    empresa_id = proc["empresa_id"]

    url_alvo = url_custom or proc["url_detalhe"]
    logger.info("Iniciando sincronização e-SAJ para %s (Tribunal: %s)...", numero_cnj, tribunal)

    movs = []
    if url_alvo and "processo.codigo" in url_alvo:
        movs = consultor.obter_movimentacoes_por_url(url_alvo, max_paginas=max_paginas, apenas_relevantes=True)
    else:
        info = consultor.consultar_processo(numero_cnj)
        if info:
            movs = info.movimentacoes

    logger.info("Extraídas %d movimentações estratégicas com filtro de relevância.", len(movs))

    url_tribunal = resolver_link_tribunal(numero_cnj, tribunal)
    inseridos = 0

    for m in movs:
        # Formatar data de DD/MM/YYYY para YYYY-MM-DD
        dt = m.data_hora
        if "/" in dt:
            partes = dt.split("/")
            if len(partes) == 3:
                dt = f"{partes[2]}-{partes[1]}-{partes[0]}"

        # Evitar duplicações
        existe = conn.execute(
            "SELECT id FROM marcos_processuais WHERE processo_id = ? AND data_evento = ? AND titulo = ?",
            (processo_id, dt, m.nome),
        ).fetchone()

        if not existe:
            banco.salvar_marco_processual(
                processo_id=processo_id,
                data_evento=dt,
                tipo_evento=m.tipo_evento or "MANIFESTACAO",
                titulo=m.nome,
                descricao=m.complemento,
                autor=m.autor or "JUIZO",
                url_documento=url_tribunal,
            )

            banco.salvar_documento(
                empresa_id=empresa_id,
                processo_id=processo_id,
                titulo=f"{m.nome} - {m.tipo_evento}",
                categoria=m.tipo_evento or "OUTROS",
                slug_documento=f"esaj-mov-{processo_id}-{dt}",
                url_download=url_tribunal,
            )
            inseridos += 1

    logger.info("Sincronização concluída! %d novos marcos inseridos no radar.db.", inseridos)
    return inseridos


if __name__ == "__main__":
    banco = BancoDados("data/radar.db")
    conn = banco.conectar()
    # Pega o processo da Novonor
    p = conn.execute("SELECT id FROM processos WHERE slug LIKE '%novonor%'").fetchone()
    if p:
        url_novonor = "https://esaj.tjsp.jus.br/cpopg/show.do?processo.codigo=2S0012IW70000&processo.foro=100&processo.numero=1057756-77.2019.8.26.0100"
        sincronizar_processo_esaj(processo_id=p["id"], url_custom=url_novonor, max_paginas=4)
