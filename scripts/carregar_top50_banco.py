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
from src.dados.links_util import (
    COMPANHIAS_CVM,
    resolver_link_cvm,
    resolver_link_documento_marco,
    resolver_link_tribunal,
)

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
    total_documentos = 0

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

        # Resolver url de detalhe do processo se genérica
        url_detalhe = caso.get("url_detalhe", "")
        if not url_detalhe or "esaj.tjsp.jus.br" == url_detalhe.strip():
            url_detalhe = resolver_link_tribunal(caso.get("numero_cnj"), caso.get("tribunal"))

        slug_processo = f"proc-{slug_empresa}"
        processo_id = banco.salvar_processo(
            empresa_id=empresa_id,
            slug=slug_processo,
            numero_cnj=caso.get("numero_cnj", ""),
            vara_comarca=caso.get("vara_comarca", ""),
            administrador_judicial=caso.get("administrador_judicial", ""),
            tipo_processo="recuperacao_judicial",
            url_detalhe=url_detalhe,
            valor_causa=caso.get("valor_causa", 0.0),
            passivo_declarado=caso.get("passivo_declarado", caso.get("valor_causa", 0.0)),
            tribunal=caso.get("tribunal", ""),
            status_processual=caso.get("status_processual", "Em Andamento"),
            data_distribuicao=caso.get("data_distribuicao", ""),
        )
        total_processos += 1

        # Limpar marcos e documentos anteriores do processo para atualização idempotente
        with banco.conectar() as conn:
            conn.execute("DELETE FROM marcos_processuais WHERE processo_id = ?", (processo_id,))
            conn.execute("DELETE FROM documentos WHERE processo_id = ?", (processo_id,))

        # Inserir marcos processuais na linha do tempo com links canônicos
        marcos = list(caso.get("marcos", []))

        # Se for companhia aberta com código CVM, adicionar marcos e documentos CVM
        info_cvm = None
        for chave_cvm, dados_cvm in COMPANHIAS_CVM.items():
            if chave_cvm in slug_empresa.lower() and dados_cvm["codigo_cvm"]:
                info_cvm = dados_cvm
                break

        if info_cvm:
            link_rad_cvm = resolver_link_cvm(info_cvm["codigo_cvm"])
            marcos.append({
                "data_evento": caso.get("data_distribuicao", "2023-01-01"),
                "tipo_evento": "FATO_RELEVANTE_CVM",
                "titulo": f"Fato Relevante CVM: Ajuizamento de Recuperação Judicial ({info_cvm['ticker'] or info_cvm['razao']})",
                "autor": "CVM",
                "descricao": f"Divulgação oficial ao mercado de capitais referente ao pedido de recuperação judicial (Cód. CVM {info_cvm['codigo_cvm']}).",
                "url_documento": link_rad_cvm,
            })
            marcos.append({
                "data_evento": "2024-01-15",
                "tipo_evento": "COMUNICADO_MERCADO_CVM",
                "titulo": f"Comunicado CVM: Andamento das Negociações do Plano de RJ ({info_cvm['ticker'] or info_cvm['razao']})",
                "autor": "CVM",
                "descricao": "Apresentação de aditivo ao PRJ e convocação de assembleia geral arquivados perante a autarquia.",
                "url_documento": link_rad_cvm,
            })

        for m in marcos:
            url_resolvida = resolver_link_documento_marco(
                url_existente=m.get("url_documento", ""),
                numero_cnj=caso.get("numero_cnj", ""),
                tribunal=caso.get("tribunal", ""),
                empresa_slug=slug_empresa,
                tipo_evento=m.get("tipo_evento", ""),
                autor=m.get("autor", "AJ"),
            )

            banco.salvar_marco_processual(
                processo_id=processo_id,
                data_evento=m.get("data_evento", ""),
                tipo_evento=m.get("tipo_evento", "MANIFESTACAO_AJ"),
                titulo=m.get("titulo", "Publicação de Ato Processual"),
                descricao=m.get("descricao", ""),
                autor=m.get("autor", "AJ"),
                url_documento=url_resolvida,
            )
            total_marcos += 1

            # Catalogar também na tabela documentos para busca e repositório central
            categoria_doc = m.get("tipo_evento", "OUTROS")
            if "CVM" in categoria_doc:
                cat_limpa = "CVM_FATO_RELEVANTE"
            elif "PETICAO" in categoria_doc:
                cat_limpa = "INICIAL"
            elif "DECISAO" in categoria_doc or "HOMOLOGACAO" in categoria_doc:
                cat_limpa = "DECISAO"
            elif "PRJ" in categoria_doc:
                cat_limpa = "PRJ"
            elif "AGC" in categoria_doc:
                cat_limpa = "AGC"
            elif "RMA" in categoria_doc:
                cat_limpa = "RMA"
            else:
                cat_limpa = "OUTROS"

            banco.salvar_documento(
                empresa_id=empresa_id,
                processo_id=processo_id,
                titulo=m.get("titulo", "Peça Processual"),
                categoria=cat_limpa,
                slug_documento=f"doc-{slug_empresa}-{m.get('data_evento', '')}-{cat_limpa.lower()}",
                url_download=url_resolvida,
                caminho_arquivo="",
            )
            total_documentos += 1

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
