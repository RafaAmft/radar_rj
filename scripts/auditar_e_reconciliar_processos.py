"""
Script de Auditoria e Reconciliação Cadastral de Processos Judiciais do Radar RJ.

Executa:
1. Varredura dos processos no banco radar.db contra sistemas de tribunais (e-SAJ TJSP, etc.).
2. Auditoria e segregação de 'valor_causa' (petição inicial oficial) vs 'passivo_declarado' (QGC).
3. Detecção de status processuais definitivos (sentença de encerramento art. 63, falência art. 73, homologação).
4. Verificação de registro de companhia aberta na CVM (código CVM e Ticker B3).
5. Geração de relatório consolidado em 'data/relatorio_auditoria_processos.json'.
6. Reconciliação opcional dos dados com flag --aplicar.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from src.banco.repositorio import BancoDados
from src.dados.catalogo_top50 import CATALOGO_TOP_50_RJS
from src.dados.cvm_resolver import obter_info_cvm
from src.ingestao.tribunais.esaj import ConsultorEsaj

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("AuditoriaProcessos")

# Padrões textuais para detecção de status processual a partir de movimentações
PADROES_STATUS = [
    (
        r"\b(julgo\s+extint\w*|julgo\s+encerrad\w*|encerramento\s+da\s+recupera[çc][ãa]o|artigo\s+63|art\.?\s*63)\b",
        "Encerrada por Sentença (Cumprimento do Plano)",
        "Encerramento da RJ por cumprimento do plano / sentença art. 63 LRF",
    ),
    (
        r"\b(decreto\s+a\s+fal[êe]ncia|convolo\s+em\s+fal[êe]ncia|convolada\s+em\s+fal[êe]ncia|decretada\s+a\s+fal[êe]ncia|artigo\s+73|art\.?\s*73)\b",
        "Falência Decretada",
        "Convolação em falência / decreto judicial art. 73 LRF",
    ),
    (
        r"\b(homologo\s+o\s+plano|homologado\s+o\s+plano|homologa[çc][ãa]o\s+do\s+plano|concedo\s+a\s+recupera[çc][ãa]o)\b",
        "Plano Homologado (Em Cumprimento)",
        "Homologação judicial do Plano de Recuperação Judicial",
    ),
    (
        r"\b(defiro\s+o\s+processamento|deferido\s+o\s+processamento|processamento\s+deferido)\b",
        "Em Andamento (Recuperação Deferida)",
        "Deferimento do processamento da Recuperação Judicial",
    ),
]


def detectar_status_por_movimentacoes(movimentacoes: list[Any]) -> tuple[str | None, str | None]:
    """
    Analisa a lista de movimentações processuais para identificar o status jurídico mais atual.
    Retorna (status_detectado, motivo_detectado) ou (None, None).
    """
    for m in movimentacoes:
        texto = ""
        if hasattr(m, "nome") and hasattr(m, "complemento"):
            texto = f"{m.nome} {m.complemento or ''}".lower()
        elif isinstance(m, dict):
            texto = f"{m.get('titulo', '')} {m.get('descricao', '')}".lower()

        for padrao, status_res, motivo in PADROES_STATUS:
            if re.search(padrao, texto, flags=re.IGNORECASE):
                return status_res, motivo

    return None, None


def executar_auditoria(
    db_path: str = "data/radar.db",
    aplicar_correcoes: bool = False,
    consultar_online: bool = True,
) -> dict[str, Any]:
    """
    Realiza a auditoria de integridade e reconciliação dos processos.
    """
    banco = BancoDados(db_path)
    banco.inicializar_schema()
    conn = banco.conectar()

    logger.info("Iniciando varredura analítica de processos em %s...", db_path)

    cur = conn.execute(
        """
        SELECT
            p.id as processo_id,
            p.slug as processo_slug,
            p.numero_cnj,
            p.tribunal,
            p.vara_comarca,
            p.administrador_judicial,
            p.status_processual,
            p.valor_causa,
            p.passivo_declarado,
            p.url_detalhe,
            e.id as empresa_id,
            e.nome_razao_social,
            e.cnpj,
            e.setor
        FROM processos p
        JOIN empresas e ON p.empresa_id = e.id
        ORDER BY p.id ASC;
        """
    )
    processos = [dict(r) for r in cur.fetchall()]

    consultor_esaj = ConsultorEsaj() if consultar_online else None

    # Mapeamento do catálogo em memória para cruzamento rápido
    catalogo_map = {c["slug"]: c for c in CATALOGO_TOP_50_RJS}
    catalogo_cnj_map = {c["numero_cnj"]: c for c in CATALOGO_TOP_50_RJS}

    detalhes_auditoria: list[dict[str, Any]] = []
    discrepancias_valor: list[dict[str, Any]] = []
    discrepancias_status: list[dict[str, Any]] = []
    atualizacoes_feitas = 0

    for proc in processos:
        p_id = proc["processo_id"]
        cnj = proc["numero_cnj"]
        tribunal = (proc["tribunal"] or "").upper()
        empresa_nome = proc["nome_razao_social"]
        cnpj = proc["cnpj"] or ""
        db_valor_causa = float(proc["valor_causa"] or 0.0)
        db_passivo_declarado = float(proc["passivo_declarado"] or 0.0)
        db_status = proc["status_processual"] or "Em Andamento"

        # 1. Resolução CVM (Companhia Aberta)
        cvm_info = obter_info_cvm(cnpj=cnpj, razao_social=empresa_nome)

        # 2. Benchmark com catálogo top 50
        cat_match = catalogo_cnj_map.get(cnj) or catalogo_map.get(proc["processo_slug"].replace("proc-", ""))
        ref_passivo_declarado = cat_match.get("passivo_declarado", 0.0) if cat_match else 0.0
        ref_valor_causa = cat_match.get("valor_causa", 0.0) if cat_match else 0.0
        ref_status = cat_match.get("status_processual") if cat_match else None

        # 3. Consulta Online se suportado (e-SAJ TJSP)
        tribunal_valor_causa = None
        tribunal_status = None
        tribunal_motivo = None
        fonte_audit = "CATALOGO_BENCHMARK"

        if consultor_esaj and tribunal in ["TJSP", "TJSC", "TJMS"]:
            try:
                info_esaj = consultor_esaj.consultar_processo(cnj)
                if info_esaj:
                    fonte_audit = "ESAJ_ONLINE"
                    if info_esaj.valor_causa is not None:
                        tribunal_valor_causa = info_esaj.valor_causa

                    # Verificar status nas movimentações retornadas pelo e-SAJ
                    if info_esaj.movimentacoes:
                        st_det, mot_det = detectar_status_por_movimentacoes(info_esaj.movimentacoes)
                        if st_det:
                            tribunal_status = st_det
                            tribunal_motivo = mot_det
            except Exception as e:
                logger.warning("Falha na consulta online e-SAJ para %s: %s", cnj, e)

        # Se a consulta online não retornou valor mas o catálogo tem valor verificado
        if tribunal_valor_causa is None and ref_valor_causa > 0:
            tribunal_valor_causa = ref_valor_causa

        if tribunal_status is None and ref_status:
            tribunal_status = ref_status
            tribunal_motivo = "Status auditado no acervo histórico documental"

        # Se ainda não detectou status no tribunal, consultar marcos salvos no banco local
        if tribunal_status is None:
            marcos_locais = banco.obter_linha_do_tempo(p_id)
            st_det, mot_det = detectar_status_por_movimentacoes(marcos_locais)
            if st_det:
                tribunal_status = st_det
                tribunal_motivo = f"Marco cronológico local: {mot_det}"

        # 4. Avaliação de Discrepâncias
        houve_discrepancia_valor = False
        if tribunal_valor_causa is not None and abs(db_valor_causa - tribunal_valor_causa) > 1.0:
            houve_discrepancia_valor = True
            disc_v = {
                "processo_id": p_id,
                "empresa": empresa_nome,
                "numero_cnj": cnj,
                "db_valor_causa": db_valor_causa,
                "tribunal_valor_causa": tribunal_valor_causa,
                "diferenca": round(tribunal_valor_causa - db_valor_causa, 2),
                "fonte": fonte_audit,
            }
            discrepancias_valor.append(disc_v)

        houve_discrepancia_status = False
        if tribunal_status and tribunal_status.lower() != db_status.lower():
            houve_discrepancia_status = True
            disc_s = {
                "processo_id": p_id,
                "empresa": empresa_nome,
                "numero_cnj": cnj,
                "db_status": db_status,
                "tribunal_status": tribunal_status,
                "motivo": tribunal_motivo,
                "fonte": fonte_audit,
            }
            discrepancias_status.append(disc_s)

        # Reconciliação do passivo declarado (QGC) se estiver zerado no banco
        passivo_reconciliado = db_passivo_declarado
        if passivo_reconciliado <= 0.0:
            passivo_reconciliado = ref_passivo_declarado or db_valor_causa

        # 5. Aplicação das Correções no Banco se solicitado
        if aplicar_correcoes:
            novo_valor_causa = tribunal_valor_causa if tribunal_valor_causa is not None else db_valor_causa
            novo_status = tribunal_status if tribunal_status else db_status

            with conn:
                conn.execute(
                    """
                    UPDATE processos
                    SET valor_causa = ?,
                        passivo_declarado = ?,
                        status_processual = ?
                    WHERE id = ?;
                    """,
                    (novo_valor_causa, passivo_reconciliado, novo_status, p_id),
                )
            atualizacoes_feitas += 1

        detalhes_auditoria.append({
            "processo_id": p_id,
            "empresa": empresa_nome,
            "cnpj": cnpj,
            "numero_cnj": cnj,
            "tribunal": tribunal,
            "db_valor_causa": db_valor_causa,
            "tribunal_valor_causa": tribunal_valor_causa or db_valor_causa,
            "db_passivo_declarado": db_passivo_declarado,
            "passivo_declarado_sugerido": passivo_reconciliado,
            "db_status": db_status,
            "status_detectado": tribunal_status or db_status,
            "motivo_status": tribunal_motivo,
            "fonte_auditoria": fonte_audit,
            "cvm_info": cvm_info,
            "discrepancia_valor": houve_discrepancia_valor,
            "discrepancia_status": houve_discrepancia_status,
        })

    # Compilar Relatório Final
    relatorio = {
        "timestamp_auditoria": datetime.now().isoformat(),
        "parametros": {
            "db_path": db_path,
            "aplicar_correcoes": aplicar_correcoes,
            "consultar_online": consultar_online,
        },
        "estatisticas": {
            "total_processos_analisados": len(processos),
            "discrepancias_valor_causa": len(discrepancias_valor),
            "discrepancias_status_processual": len(discrepancias_status),
            "empresas_cvm_identificadas": sum(1 for d in detalhes_auditoria if d["cvm_info"] is not None),
            "registros_reconciliados_banco": atualizacoes_feitas if aplicar_correcoes else 0,
        },
        "discrepancias_valor_causa": discrepancias_valor,
        "discrepancias_status_processual": discrepancias_status,
        "detalhes": detalhes_auditoria,
    }

    # Salvar em data/relatorio_auditoria_processos.json
    out_path = Path("data/relatorio_auditoria_processos.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(relatorio, f, indent=2, ensure_ascii=False)

    logger.info("Relatório de auditoria salvo com sucesso em %s", out_path)
    logger.info(
        "Resumo: %d processos analisados, %d discrepâncias de valor, %d discrepâncias de status, %d CVM.",
        len(processos),
        len(discrepancias_valor),
        len(discrepancias_status),
        relatorio["estatisticas"]["empresas_cvm_identificadas"],
    )

    return relatorio


def main() -> None:
    parser = argparse.ArgumentParser(description="Auditoria e Reconciliação dos Processos do Radar RJ")
    parser.add_argument("--db", default="data/radar.db", help="Caminho do banco SQLite")
    parser.add_argument("--aplicar", action="store_true", help="Aplica as correções de valor e status no banco")
    parser.add_argument("--offline", action="store_true", help="Não faz requisições aos portais dos tribunais")
    args = parser.parse_args()

    relatorio = executar_auditoria(
        db_path=args.db,
        aplicar_correcoes=args.aplicar,
        consultar_online=not args.offline,
    )

    print("\n" + "=" * 80)
    print("RELATÓRIO DE AUDITORIA E RECONCILIAÇÃO PROCESSUAL - RADAR RJ")
    print("=" * 80)
    stats = relatorio["estatisticas"]
    print(f"Total de processos analisados:        {stats['total_processos_analisados']}")
    print(f"Discrepâncias de valor da causa:      {stats['discrepancias_valor_causa']}")
    print(f"Discrepâncias de status processual:   {stats['discrepancias_status_processual']}")
    print(f"Companhias com registro CVM ativo:   {stats['empresas_cvm_identificadas']}")
    if args.aplicar:
        print(f"Processos atualizados no radar.db:    {stats['registros_reconciliados_banco']}")
    else:
        print("Modo simulação: Nenhuma alteração gravada. Use --aplicar para reconciliar.")
    print("=" * 80)


if __name__ == "__main__":
    main()
