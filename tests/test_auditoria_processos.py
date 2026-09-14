"""
Testes unitários para o script de auditoria e reconciliação de processos.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from scripts.auditar_e_reconciliar_processos import (
    detectar_status_por_movimentacoes,
    executar_auditoria,
)
from src.banco.repositorio import BancoDados


def test_detectar_status_por_movimentacoes():
    # 1. Encerramento art. 63
    movs_encerramento = [
        {"titulo": "Sentença", "descricao": "Julgo extinta a presente recuperação judicial, com fulcro no art. 63 da Lei 11.101/05"}
    ]
    status, motivo = detectar_status_por_movimentacoes(movs_encerramento)
    assert status == "Encerrada por Sentença (Cumprimento do Plano)"
    assert "art. 63" in motivo

    # 2. Falência art. 73
    movs_falencia = [
        {"titulo": "Decisão", "descricao": "Decreto a falência da recuperanda nos termos do artigo 73 da LRF"}
    ]
    status, motivo = detectar_status_por_movimentacoes(movs_falencia)
    assert status == "Falência Decretada"

    # 3. Homologação
    movs_homolog = [
        {"titulo": "Decisão", "descricao": "Homologo o plano de recuperação judicial aprovado em AGC"}
    ]
    status, motivo = detectar_status_por_movimentacoes(movs_homolog)
    assert status == "Plano Homologado (Em Cumprimento)"

    # 4. Deferimento
    movs_defer = [
        {"titulo": "Despacho", "descricao": "Defiro o processamento da recuperação judicial"}
    ]
    status, motivo = detectar_status_por_movimentacoes(movs_defer)
    assert status == "Em Andamento (Recuperação Deferida)"

    # 5. Sem correspondência
    movs_geral = [
        {"titulo": "Juntada", "descricao": "Juntada de petição de credor"}
    ]
    status, motivo = detectar_status_por_movimentacoes(movs_geral)
    assert status is None


def test_executar_auditoria_em_memoria(tmp_path: Path):
    db_file = tmp_path / "teste_auditoria.db"
    banco = BancoDados(str(db_file))
    banco.inicializar_schema()

    # Inserir empresa e processo de teste
    empresa_id = banco.salvar_empresa(
        nome_razao_social="PDG Realty S.A. Empreendimentos e Participações",
        cnpj="02.950.811/0001-89",
        setor="Construção Civil & Imobiliário",
        slug="pdg-realty",
    )

    # Inserir com dados antigos/divergentes para testar auditoria
    proc_id = banco.salvar_processo(
        empresa_id=empresa_id,
        numero_cnj="1016422-34.2017.8.26.0100",
        tribunal="TJSP",
        vara_comarca="1ª Vara de Falências e Recuperações Judiciais",
        administrador_judicial="KPMG Corporate Finance",
        status_processual="Em Andamento",  # Divergente do real (encerrada)
        valor_causa=7800000000.0,          # Valor do passivo colocado incorretamente na causa
        passivo_declarado=0.0,             # Zerado
        slug="proc-pdg-realty",
    )

    # Executar auditoria em modo offline (usando benchmark e catálogo)
    relatorio = executar_auditoria(
        db_path=str(db_file),
        aplicar_correcoes=True,
        consultar_online=False,
    )

    assert relatorio["estatisticas"]["total_processos_analisados"] == 1
    assert relatorio["estatisticas"]["empresas_cvm_identificadas"] == 1
    assert relatorio["estatisticas"]["discrepancias_valor_causa"] == 1
    assert relatorio["estatisticas"]["discrepancias_status_processual"] == 1

    # Verificar se as correções foram persistidas no banco
    dossie = banco.obter_dossie_processo(proc_id)
    assert dossie["valor_causa"] == 6200000000.0
    assert dossie["passivo_declarado"] == 7800000000.0
    assert "Encerrada" in dossie["status_processual"]
