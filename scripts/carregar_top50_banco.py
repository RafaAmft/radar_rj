"""
Script de Carga e Enriquecimento das Maiores Recuperações Judiciais no radar.db.

Popula as tabelas empresas, processos, marcos_processuais e credores
a partir do catálogo curado CATALOGO_TOP_50_RJS.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# Garantir importação do módulo src
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.banco.repositorio import BancoDados
from src.dados.catalogo_top50 import CATALOGO_TOP_50_RJS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("CargaTop50")


def carregar_catalogo_para_banco(db_path: str = "data/radar.db") -> dict[str, int]:
    """Insere ou atualiza o catálogo das 50 maiores RJs no banco relacional."""
    banco = BancoDados(db_path)
    banco.inicializar_schema()

    total_empresas = 0
    total_processos = 0
    total_marcos = 0
    total_credores = 0

    logger.info("Iniciando carga de %d casos do catálogo no banco %s...", len(CATALOGO_TOP_50_RJS), db_path)

    for caso in CATALOGO_TOP_50_RJS:
        slug_empresa = caso["slug"]
        empresa_id = banco.salvar_empresa(
            slug=slug_empresa,
            nome_razao_social=caso["nome_razao_social"],
            cnpj=caso.get("cnpj", ""),
            setor=caso.get("setor", "Outros"),
            origem_fonte="catalogo_nacional_top50",
        )
        total_empresas += 1

        slug_processo = f"proc-{slug_empresa}"
        processo_id = banco.salvar_processo(
            empresa_id=empresa_id,
            slug=slug_processo,
            numero_cnj=caso.get("numero_cnj", ""),
            vara_comarca=caso.get("vara_comarca", ""),
            administrador_judicial=caso.get("administrador_judicial", ""),
            tipo_processo="recuperacao_judicial",
            url_detalhe=caso.get("url_detalhe", ""),
            valor_causa=caso.get("valor_causa", 0.0),
            tribunal=caso.get("tribunal", ""),
            status_processual=caso.get("status_processual", "Em Andamento"),
            data_distribuicao=caso.get("data_distribuicao", ""),
        )
        total_processos += 1

        # Inserir marcos processuais na linha do tempo
        marcos = caso.get("marcos", [])
        for m in marcos:
            banco.salvar_marco_processual(
                processo_id=processo_id,
                data_evento=m.get("data_evento", ""),
                tipo_evento=m.get("tipo_evento", "MANIFESTACAO_AJ"),
                titulo=m.get("titulo", "Publicação de Ato Processual"),
                descricao=m.get("descricao", ""),
                autor=m.get("autor", "AJ"),
                url_documento=m.get("url_documento", ""),
            )
            total_marcos += 1

        # Se houver classes_passivo e não existirem credores desse processo, insere registros agregados
        classes = caso.get("classes_passivo", {})
        if classes:
            resumo_atual = banco.obter_resumo_credores_processo(processo_id)
            if resumo_atual["total_credores"] == 0:
                lote_credores = []
                for nome_classe, valor in classes.items():
                    if valor > 0:
                        lote_credores.append({
                            "nome": f"Total {nome_classe} ({caso['nome_razao_social'][:30]})",
                            "documento": caso.get("cnpj", ""),
                            "documento_limpo": "".join(filter(str.isdigit, caso.get("cnpj", ""))),
                            "tipo_documento": "CNPJ",
                            "classe": nome_classe,
                            "natureza": "Crédito Concursal",
                            "valor": valor,
                            "moeda": "BRL",
                        })
                if lote_credores:
                    banco.salvar_credores_lote(lote_credores, processo_id=processo_id)
                    total_credores += len(lote_credores)

    stats = banco.obter_estatisticas_gerais()
    logger.info("Carga concluída com sucesso!")
    logger.info(
        "Status final do radar.db: %d empresas, %d processos, %d documentos, %d credores, %d marcos.",
        stats.get("total_empresas", 0),
        stats.get("total_processos", 0),
        stats.get("total_documentos", 0),
        stats.get("total_credores", 0),
        stats.get("total_marcos", 0),
    )

    return {
        "empresas_inseridas": total_empresas,
        "processos_inseridos": total_processos,
        "marcos_inseridos": total_marcos,
        "credores_inseridos": total_credores,
    }


if __name__ == "__main__":
    carregar_catalogo_para_banco("data/radar.db")
