"""
CLI para Reconciliação e Cruzamento Inteligente de Processos e Fontes de AJ/CVM.
"""

from __future__ import annotations

import argparse
import logging
import sys

from src.cruzamento.reconciliador import ReconciliadorFontes

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("CruzamentoCLI")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Radar de Ativos - Cruzamento e Reconciliação Inteligente de Fontes"
    )
    parser.add_argument(
        "--reconciliar",
        action="store_true",
        help="Executa a reconciliação em lote para todos os processos judiciais do banco",
    )
    parser.add_argument(
        "--processo",
        type=str,
        default="",
        help="Número CNJ de um processo específico para reconciliar",
    )
    parser.add_argument(
        "--limiar",
        type=float,
        default=0.85,
        help="Limiar de similaridade para matching fuzzy de razão social (0.0 a 1.0, padrão: 0.85)",
    )
    parser.add_argument(
        "--sem-extracao",
        action="store_true",
        help="Não dispara extração automática de QGC para peças vinculadas",
    )

    args = parser.parse_args()

    if not args.reconciliar and not args.processo:
        parser.print_help()
        sys.exit(1)

    processos_alvo = [args.processo.strip()] if args.processo else None
    disparar_extracao = not args.sem_extracao

    logger.info("[CLI] Iniciando reconciliação de fontes (Limiar: %.2f)...", args.limiar)
    reconciliador = ReconciliadorFontes()
    resultado = reconciliador.executar_reconciliacao(
        processos_cnj=processos_alvo,
        limiar_similaridade=args.limiar,
        disparar_extracao=disparar_extracao,
    )

    print("\n" + "=" * 70)
    print("         RELATÓRIO DE CRUZAMENTO E RECONCILIAÇÃO DE FONTES")
    print("=" * 70)
    print(f"Total de processos analisados: {resultado.total_processos_analisados}")
    print(f"Total de vínculos (matches):   {resultado.total_matches_encontrados}")

    if resultado.matches:
        print("\nDetalhes dos Vínculos Encontrados:")
        for idx, m in enumerate(resultado.matches, 1):
            print(f"  [{idx}] CNJ: {m.processo_cnj}")
            print(f"      Empresa Casada:   {m.empresa_nome} (ID: {m.empresa_id})")
            print(f"      Fonte AJ/CVM:     {m.fonte_aj.upper()}")
            print(f"      Critério:         {m.tipo_match.upper()} (Confiança: {int(m.confianca*100)}%)")
            print(f"      Detalhes:         {m.detalhes}")
            if m.documentos_vinculados > 0:
                print(f"      Peças Vinculadas: {m.documentos_vinculados} documento(s)")
            print()

    if resultado.acoes_disparadas:
        print("Ações Automáticas Disparadas:")
        for acao in resultado.acoes_disparadas:
            print(f"  [OK] {acao}")

    print("=" * 70 + "\n")


if __name__ == "__main__":
    main()
