"""
CLI para execução do Robô de Monitoramento Contínuo de Tribunais de Justiça.
"""

from __future__ import annotations

import argparse
import logging
import sys

from src.monitor.agendador import MonitorTribunais

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("MonitorCLI")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Radar de Ativos - Robô Contínuo de Monitoramento de Tribunais"
    )
    grupo = parser.add_mutually_exclusive_group(required=True)
    grupo.add_argument(
        "--ciclo-unico",
        action="store_true",
        help="Executa uma única varredura nos tribunais e imprime relatório",
    )
    grupo.add_argument(
        "--daemon",
        action="store_true",
        help="Executa em loop contínuo em segundo plano",
    )

    parser.add_argument(
        "--tribunais",
        type=str,
        default="",
        help="Lista de siglas de tribunais separadas por vírgula (ex: tjsp,tjmg,tjrs)",
    )
    parser.add_argument(
        "--limite",
        type=int,
        default=5,
        help="Quantidade máxima de novos processos a consultar por tribunal (padrão: 5)",
    )
    parser.add_argument(
        "--intervalo",
        type=int,
        default=300,
        help="Intervalo em segundos entre ciclos no modo daemon (padrão: 300s / 5min)",
    )
    parser.add_argument(
        "--max-ciclos",
        type=int,
        default=None,
        help="Número máximo de ciclos a executar antes de parar (opcional)",
    )
    parser.add_argument(
        "--sem-banco",
        action="store_true",
        help="Modo dry-run: não grava no banco de dados radar.db",
    )
    parser.add_argument(
        "--sem-cruzamento",
        action="store_true",
        help="Desativa o cruzamento automático com Administradores Judiciais",
    )

    args = parser.parse_args()

    tribunais = [t.strip().lower() for t in args.tribunais.split(",") if t.strip()] or None
    salvar_banco = not args.sem_banco
    disparar_cruzamento = not args.sem_cruzamento

    monitor = MonitorTribunais()

    if args.ciclo_unico:
        logger.info("[CLI] Executando ciclo único de monitoramento...")
        relatorio = monitor.executar_ciclo(
            tribunais=tribunais,
            limite_por_tribunal=args.limite,
            salvar_banco=salvar_banco,
            disparar_cruzamento=disparar_cruzamento,
        )
        print("\n" + "=" * 60)
        print("          RELATÓRIO DO CICLO DE MONITORAMENTO")
        print("=" * 60)
        print(f"Tribunais varridos:        {', '.join(relatorio.tribunais).upper()}")
        print(f"Processos encontrados:     {relatorio.total_encontrados}")
        print(f"Novos processos detectados:{relatorio.total_novos}")
        print(f"Processos enriquecidos:    {relatorio.total_enriquecidos}")
        print(f"Cruzamentos com AJs:       {relatorio.cruzamentos_realizados}")
        print(f"Erros encontrados:         {relatorio.total_erros}")
        if relatorio.processos_processados:
            print("\nProcessos novos processados:")
            for cnj in relatorio.processos_processados:
                print(f"  • {cnj}")
        print("=" * 60 + "\n")

    elif args.daemon:
        logger.info(
            "[CLI] Iniciando monitor em modo daemon (Intervalo: %ds, Max Ciclos: %s)...",
            args.intervalo,
            args.max_ciclos,
        )
        monitor.executar_daemon(
            intervalo_segundos=args.intervalo,
            max_ciclos=args.max_ciclos,
            tribunais=tribunais,
            limite_por_tribunal=args.limite,
            salvar_banco=salvar_banco,
            disparar_cruzamento=disparar_cruzamento,
        )


if __name__ == "__main__":
    main()
