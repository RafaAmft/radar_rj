"""
Extrator 3: ITD — Iudicium Textum Dataset (UFPR/C3SL).

Amostra estrutural de acórdãos do STF para treino do classificador.
Não possui vínculo com empresa específica.

Fluxo:
  1. Carrega config da fonte itd.
  2. Faz download com streaming do JSON de relatórios (153 MB).
  3. Parseia incrementalmente com ijson os primeiros N registros.
  4. Salva cada acórdão como arquivo .txt individual.
  5. Registra no manifesto da amostra estrutural.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import requests

from src.ingestao.download import (
    DIR_DATA_RAW,
    HEADERS_PADRAO,
    calcular_sha256,
    carregar_config_fonte,
)
from src.ingestao.manifesto import ManifestoManager

logger = logging.getLogger(__name__)


def _parse_json_streaming(url: str, max_registros: int) -> list[dict]:
    """
    Faz download com streaming e parseia incrementalmente o JSON do ITD.

    O JSON do ITD é um array de objetos. Usamos ijson para parse
    incremental sem carregar tudo em memória.

    Falls back para download completo + json.loads se ijson não estiver
    disponível ou se o formato não for o esperado.
    """
    registros = []

    try:
        import ijson

        logger.info(
            "Iniciando parse streaming de %s (máx %d registros)...",
            url,
            max_registros,
        )
        resp = requests.get(url, headers=HEADERS_PADRAO, stream=True, timeout=120)
        resp.raise_for_status()

        # ijson parseia o stream incrementalmente
        # O JSON é um array de objetos: [{"campo": "valor"}, ...]
        parser = ijson.items(resp.raw, "item")

        for i, item in enumerate(parser):
            if i >= max_registros:
                break
            registros.append(item)
            if (i + 1) % 50 == 0:
                logger.info("Parseados %d/%d registros...", i + 1, max_registros)

        resp.close()
        logger.info("Parse streaming concluído: %d registros", len(registros))

    except ImportError:
        logger.warning(
            "ijson não disponível. Fazendo download completo (pode demorar)..."
        )
        resp = requests.get(url, headers=HEADERS_PADRAO, timeout=300)
        resp.raise_for_status()
        todos = json.loads(resp.content)
        registros = todos[:max_registros]
        logger.info("Download completo: %d registros extraídos", len(registros))

    except Exception as e:
        logger.error("Erro no parse streaming: %s", e)
        raise

    return registros


def _formatar_acordao(registro: dict) -> str:
    """
    Formata um registro de acórdão como texto plano estruturado.

    Tenta extrair campos conhecidos do ITD:
    - id, nome/titulo, ementa, relatorio, voto(s), decisao
    """
    partes = []

    # Header
    titulo = registro.get("titulo") or registro.get("nome") or registro.get("id", "")
    if titulo:
        partes.append(f"# {titulo}")
        partes.append("")

    # Metadados
    for campo in ["id", "numero", "data_julgamento", "relator", "orgao_julgador"]:
        valor = registro.get(campo)
        if valor:
            partes.append(f"**{campo.replace('_', ' ').title()}**: {valor}")

    if partes and partes[-1] != "":
        partes.append("")

    # Seções de conteúdo
    for secao, label in [
        ("ementa", "EMENTA"),
        ("relatorio", "RELATÓRIO"),
        ("relator_relatorio", "RELATÓRIO"),
        ("voto", "VOTO"),
        ("voto_relator", "VOTO DO RELATOR"),
        ("decisao", "DECISÃO"),
        ("acordao", "ACÓRDÃO"),
        ("texto", "TEXTO INTEGRAL"),
    ]:
        conteudo = registro.get(secao)
        if conteudo and isinstance(conteudo, str) and conteudo.strip():
            partes.append(f"## {label}")
            partes.append("")
            partes.append(conteudo.strip())
            partes.append("")

    # Se nenhum campo estruturado, dump JSON formatado
    if len(partes) <= 2:
        partes.append("## DADOS BRUTOS")
        partes.append("")
        partes.append(json.dumps(registro, ensure_ascii=False, indent=2))

    return "\n".join(partes)


def executar(dry_run: bool = False) -> int:
    """
    Executa a ingestão da amostra estrutural do ITD.

    Args:
        dry_run: Se True, apenas mostra o que faria.

    Returns:
        Número de acórdãos salvos.
    """
    config = carregar_config_fonte("itd")
    url_relatorios = config["urls"]["relatorios"]
    tamanho_amostra = config["tamanho_amostra"]
    saida_dir_rel = config["saida_dir"]
    dir_saida = DIR_DATA_RAW / saida_dir_rel

    if dry_run:
        logger.info("[DRY-RUN] Baixaria %d acórdãos de: %s", tamanho_amostra, url_relatorios)
        logger.info("[DRY-RUN] Salvaria em: %s", dir_saida)
        return 0

    # Inicializar diretório e manifesto da amostra estrutural
    dir_saida.mkdir(parents=True, exist_ok=True)
    manifesto = ManifestoManager(dir_saida, empresa="itd_acordaos")

    # Verificar idempotência: conferir acórdãos registrados com sucesso que existem em disco
    acordaos_validos = [
        e
        for e in manifesto.entradas
        if e.get("status") == "ok"
        and (dir_saida / Path(e.get("arquivo_local", "")).name).exists()
    ]
    if len(acordaos_validos) >= tamanho_amostra:
        logger.info(
            "Amostra ITD já contém %d acórdãos válidos no manifesto (meta: %d). Pulando.",
            len(acordaos_validos),
            tamanho_amostra,
        )
        return 0

    # Download e parse incremental
    logger.info("Iniciando ingestão ITD: %d acórdãos de %s", tamanho_amostra, url_relatorios)
    registros = _parse_json_streaming(url_relatorios, tamanho_amostra)

    # Salvar cada acórdão
    salvos = 0
    for i, registro in enumerate(registros):
        id_acordao = registro.get("id") or registro.get("numero") or f"acordao_{i+1:04d}"
        # Limpar ID para nome de arquivo
        id_limpo = str(id_acordao).replace("/", "_").replace("\\", "_").replace(" ", "_")
        nome_arquivo = f"{id_limpo}.txt"
        caminho = dir_saida / nome_arquivo
        arquivo_rel = nome_arquivo

        if manifesto.ja_ingerido_arquivo(arquivo_rel) and caminho.exists():
            continue

        # Formatar e salvar
        texto = _formatar_acordao(registro)
        caminho.write_text(texto, encoding="utf-8")

        hash_arq = calcular_sha256(caminho)
        manifesto.registrar(
            url_origem=url_relatorios,
            arquivo_local=arquivo_rel,
            hash_sha256=hash_arq,
            tipo_fonte="itd",
            metadados_extra={"indice": i, "id_original": str(id_acordao)},
        )
        salvos += 1

    logger.info("Ingestão ITD concluída: %d acórdãos salvos em %s", salvos, dir_saida)
    return salvos
