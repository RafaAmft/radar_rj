"""
Extrator 1: CVM DFP/ITR — Demonstrações Financeiras Padronizadas e
Informações Trimestrais.

Fluxo:
  1. Carrega config de empresas e da fonte cvm_dfp_itr.
  2. Para cada ano na janela temporal:
     a. Baixa o ZIP anual (DFP e ITR separadamente).
     b. Extrai CSVs em memória.
     c. Filtra linhas pelo CNPJ de cada empresa-alvo.
     d. Salva CSV filtrado em data/raw/<empresa>/cvm/dfp_itr/.
  3. Registra cada arquivo gerado no manifesto da empresa.
"""

from __future__ import annotations

import io
import logging
from pathlib import Path

import pandas as pd

from src.ingestao.download import (
    DIR_DATA_RAW,
    calcular_sha256,
    carregar_config_empresas,
    carregar_config_fonte,
    download_com_retry,
    extrair_zip_em_memoria,
)
from src.ingestao.manifesto import ManifestoManager

logger = logging.getLogger(__name__)


def _filtrar_csv_por_cnpj(
    conteudo_csv: bytes,
    cnpj: str,
    campo_filtro: str,
    cnpj_formatado: str | None = None,
    encoding: str = "latin-1",
    separador: str = ";",
) -> pd.DataFrame | None:
    """
    Lê um CSV da CVM e filtra as linhas pelo CNPJ da empresa.

    Os CSVs da CVM usam encoding latin-1 e separador ';'.
    Suporta tanto formato com pontuação (XX.XXX.XXX/XXXX-XX) quanto sem pontuação.

    Returns:
        DataFrame filtrado, ou None se não houver linhas para o CNPJ.
    """
    try:
        df = pd.read_csv(
            io.BytesIO(conteudo_csv),
            sep=separador,
            encoding=encoding,
            dtype=str,  # tudo como string para preservar zeros à esquerda
            low_memory=False,
        )
    except Exception as e:
        logger.warning("Erro ao ler CSV: %s", e)
        return None

    if campo_filtro not in df.columns:
        logger.debug(
            "Campo '%s' não encontrado. Colunas disponíveis: %s",
            campo_filtro,
            list(df.columns),
        )
        return None

    col_filtro = df[campo_filtro].astype(str).str.strip()
    mascara = col_filtro == cnpj
    if cnpj_formatado:
        mascara = mascara | (col_filtro == cnpj_formatado)

    # Fallback: normaliza removendo pontuações
    if not mascara.any():
        col_normalizada = col_filtro.str.replace(r"\D", "", regex=True)
        cnpj_limpo = cnpj.replace(".", "").replace("/", "").replace("-", "")
        mascara = col_normalizada == cnpj_limpo

    filtrado = df[mascara]
    if filtrado.empty:
        return None

    return filtrado


def executar(
    slugs_empresa: list[str] | None = None,
    anos: list[int] | None = None,
    dry_run: bool = False,
) -> dict[str, int]:
    """
    Executa a ingestão de DFP e ITR da CVM.

    Args:
        slugs_empresa: Lista de slugs das empresas a processar (None = todas).
        anos: Lista de anos específicos (None = usa janela de empresas.yaml).
        dry_run: Se True, apenas lista URLs sem baixar.

    Returns:
        Dict com contagem de arquivos gerados por empresa.
    """
    config_empresas = carregar_config_empresas()
    config_fonte = carregar_config_fonte("cvm_dfp_itr")

    if anos is None:
        inicio = config_empresas["janela_temporal"]["inicio"]
        fim = config_empresas["janela_temporal"]["fim"]
        anos = list(range(inicio, fim + 1))

    campo_filtro = config_fonte["campo_filtro"]
    tipos_demo = config_fonte["tipos_demonstracao"]
    saida_dir_rel = config_fonte["saida_dir"]

    empresas = config_empresas["empresas"]
    if slugs_empresa:
        empresas = [e for e in empresas if e["slug"] in slugs_empresa]

    contagem: dict[str, int] = {}

    for prefixo, url_base, pattern in [
        ("dfp", config_fonte["urls"]["dfp_base"], config_fonte["urls"]["dfp_pattern"]),
        ("itr", config_fonte["urls"]["itr_base"], config_fonte["urls"]["itr_pattern"]),
    ]:
        for ano in anos:
            nome_zip = pattern.format(ano=ano)
            url_zip = url_base + nome_zip

            if dry_run:
                logger.info("[DRY-RUN] Baixaria: %s", url_zip)
                for emp in empresas:
                    for tipo in tipos_demo:
                        destino = (
                            DIR_DATA_RAW
                            / emp["slug"]
                            / saida_dir_rel
                            / f"{prefixo}_{tipo}_{ano}.csv"
                        )
                        logger.info("[DRY-RUN]   → %s", destino)
                continue

            # Download do ZIP
            logger.info("Baixando %s...", nome_zip)
            delay_download = config_fonte.get("delay_entre_downloads", 1.0)
            try:
                conteudo_zip = download_com_retry(
                    url_zip, desc=nome_zip, delay_rate_limit=delay_download
                )
            except ConnectionError as e:
                logger.error("Falha ao baixar %s: %s", nome_zip, e)
                continue

            # Extrair CSVs do ZIP em memória
            arquivos_zip = extrair_zip_em_memoria(conteudo_zip)
            logger.info(
                "ZIP %s contém %d arquivos: %s",
                nome_zip,
                len(arquivos_zip),
                list(arquivos_zip.keys())[:5],
            )

            # Processar cada empresa
            for empresa in empresas:
                slug = empresa["slug"]
                cnpj = empresa["cnpj"]
                cnpj_formatado = empresa.get("cnpj_formatado")
                dir_empresa = DIR_DATA_RAW / slug / saida_dir_rel
                dir_empresa.mkdir(parents=True, exist_ok=True)

                manifesto = ManifestoManager(DIR_DATA_RAW / slug, empresa=slug)

                # Filtrar cada CSV interno relevante
                for nome_csv, conteudo_csv in arquivos_zip.items():
                    if not nome_csv.lower().endswith(".csv"):
                        continue

                    # Identificar o tipo de demonstração pelo nome do arquivo
                    # Ex: dfp_cia_aberta_BPA_con_2024.csv → tipo = BPA
                    tipo_encontrado = None
                    nome_upper = nome_csv.upper()
                    for tipo in tipos_demo:
                        if f"_{tipo}_" in nome_upper or f"_{tipo}." in nome_upper:
                            tipo_encontrado = tipo
                            break

                    if tipo_encontrado is None:
                        continue

                    # Identificar se é consolidado (con) ou individual (ind)
                    grupo = ""
                    if "_CON_" in nome_upper or nome_upper.endswith("_CON.CSV"):
                        grupo = "con"
                    elif "_IND_" in nome_upper or nome_upper.endswith("_IND.CSV"):
                        grupo = "ind"

                    # Nome de saída mantendo distinção de consolidação
                    nome_saida = (
                        f"{prefixo}_{tipo_encontrado}_{grupo}_{ano}.csv"
                        if grupo
                        else f"{prefixo}_{tipo_encontrado}_{ano}.csv"
                    )
                    caminho_saida = dir_empresa / nome_saida
                    arquivo_rel = f"{saida_dir_rel}/{nome_saida}"

                    if manifesto.ja_ingerido_arquivo(arquivo_rel):
                        logger.debug("Já ingerido, pulando: %s", arquivo_rel)
                        continue

                    # Filtrar pelo CNPJ
                    df = _filtrar_csv_por_cnpj(
                        conteudo_csv,
                        cnpj,
                        campo_filtro,
                        cnpj_formatado=cnpj_formatado,
                    )
                    if df is None:
                        logger.debug(
                            "Nenhum dado para %s em %s/%s/%d",
                            slug,
                            prefixo,
                            tipo_encontrado,
                            ano,
                        )
                        continue

                    # Salvar CSV filtrado
                    df.to_csv(caminho_saida, index=False, sep=";", encoding="utf-8")
                    logger.info(
                        "Salvo %d linhas em %s", len(df), caminho_saida
                    )

                    # Registrar no manifesto
                    hash_arq = calcular_sha256(caminho_saida)
                    manifesto.registrar(
                        url_origem=url_zip,
                        arquivo_local=arquivo_rel,
                        hash_sha256=hash_arq,
                        tipo_fonte=f"cvm_{prefixo}",
                        metadados_extra={
                            "tipo_demonstracao": tipo_encontrado,
                            "consolidacao": grupo,
                            "ano": ano,
                            "linhas": len(df),
                            "csv_origem": nome_csv,
                        },
                    )
                    contagem[slug] = contagem.get(slug, 0) + 1

    # Resumo
    total = sum(contagem.values())
    logger.info(
        "Ingestão CVM DFP/ITR concluída: %d arquivos gerados. %s",
        total,
        contagem,
    )
    return contagem
