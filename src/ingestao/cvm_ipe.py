"""
Extrator 2: CVM IPE — Informações Periódicas e Eventuais.

Fluxo:
  1. Carrega config de empresas e da fonte cvm_ipe.
  2. Para cada ano na janela temporal:
     a. Baixa o ZIP anual do índice IPE.
     b. Extrai o CSV de índice em memória.
     c. Filtra por CD_CVM de cada empresa e categorias de interesse.
     d. Para cada documento filtrado, baixa o PDF via LINK_DOC.
  3. Registra cada PDF no manifesto da empresa.
"""

from __future__ import annotations

import io
import logging
import re
import time
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


def _sanitizar_nome(texto: str) -> str:
    """Remove caracteres inválidos para nomes de arquivo."""
    # Substituir espaços e caracteres especiais por underscore
    texto = re.sub(r"[^\w\d\-.]", "_", texto)
    # Colapsar underscores múltiplos
    texto = re.sub(r"_+", "_", texto)
    # Limitar tamanho
    return texto[:100].strip("_")


def _resolver_coluna(df: pd.DataFrame, preferida: str, alternativas: list[str]) -> str | None:
    """Retorna o nome da coluna presente no DataFrame, testando alternativas."""
    if preferida in df.columns:
        return preferida
    for alt in alternativas:
        if alt in df.columns:
            return alt
    return None


def executar(
    slugs_empresa: list[str] | None = None,
    anos: list[int] | None = None,
    max_documentos: int | None = None,
    dry_run: bool = False,
) -> dict[str, int]:
    """
    Executa a ingestão de IPE da CVM.

    Args:
        slugs_empresa: Lista de slugs das empresas a processar (None = todas).
        anos: Lista de anos específicos (None = usa janela de empresas.yaml).
        dry_run: Se True, apenas lista URLs sem baixar.

    Returns:
        Dict com contagem de PDFs baixados por empresa.
    """
    config_empresas = carregar_config_empresas()
    config_fonte = carregar_config_fonte("cvm_ipe")

    if anos is None:
        inicio = config_empresas["janela_temporal"]["inicio"]
        fim = config_empresas["janela_temporal"]["fim"]
        anos = list(range(inicio, fim + 1))

    campo_filtro = config_fonte["campo_filtro"]
    campo_link = config_fonte["campo_link"]
    campo_data = config_fonte["campo_data"]
    campo_categoria = config_fonte["campo_categoria"]
    categorias = config_fonte["categorias"]
    delay = config_fonte["delay_entre_downloads"]
    saida_dir_rel = config_fonte["saida_dir"]
    url_base = config_fonte["urls"]["base"]
    pattern = config_fonte["urls"]["pattern"]

    empresas = config_empresas["empresas"]
    if slugs_empresa:
        empresas = [e for e in empresas if e["slug"] in slugs_empresa]

    contagem: dict[str, int] = {}

    for ano in anos:
        nome_zip = pattern.format(ano=ano)
        url_zip = url_base + nome_zip

        if dry_run:
            logger.info("[DRY-RUN] Baixaria índice: %s", url_zip)
            continue

        # Download do ZIP do índice
        logger.info("Baixando índice IPE %d...", ano)
        try:
            conteudo_zip = download_com_retry(url_zip, desc=nome_zip)
        except ConnectionError as e:
            logger.error("Falha ao baixar %s: %s", nome_zip, e)
            continue

        # Extrair CSV de índice
        arquivos_zip = extrair_zip_em_memoria(conteudo_zip)
        csvs = [n for n in arquivos_zip if n.lower().endswith(".csv")]
        if not csvs:
            logger.warning("Nenhum CSV encontrado em %s", nome_zip)
            continue

        # Normalmente há um único CSV dentro do ZIP
        nome_csv_indice = csvs[0]
        conteudo_csv = arquivos_zip[nome_csv_indice]

        try:
            df_indice = pd.read_csv(
                io.BytesIO(conteudo_csv),
                sep=";",
                encoding="latin-1",
                dtype=str,
                low_memory=False,
            )
        except Exception as e:
            logger.error("Erro ao ler CSV do índice IPE %d: %s", ano, e)
            continue

        logger.info("Índice IPE %d: %d registros", ano, len(df_indice))

        # Resolver colunas dinamicamente
        col_filtro = _resolver_coluna(
            df_indice, campo_filtro, ["Codigo_CVM", "CD_CVM", "CNPJ_Companhia", "CNPJ_CIA"]
        )
        col_link = _resolver_coluna(
            df_indice, campo_link, ["Link_Download", "LINK_DOC", "LINK_DOCUMENTO"]
        )
        col_data = _resolver_coluna(
            df_indice, campo_data, ["Data_Referencia", "DT_REFER", "Data_Entrega"]
        )
        col_categoria = _resolver_coluna(
            df_indice, campo_categoria, ["Categoria", "CATEG_DOC", "Tipo"]
        )

        if not col_filtro or not col_link:
            logger.warning(
                "Colunas essenciais não encontradas no índice IPE %d. Disponíveis: %s",
                ano,
                list(df_indice.columns),
            )
            continue

        # Processar cada empresa
        for empresa in empresas:
            slug = empresa["slug"]
            codigo_cvm = str(empresa["codigo_cvm"]).strip()
            cnpj = str(empresa.get("cnpj", "")).strip()
            cnpj_fmt = str(empresa.get("cnpj_formatado", "")).strip()
            dir_empresa_ipe = DIR_DATA_RAW / slug / saida_dir_rel
            dir_empresa_ipe.mkdir(parents=True, exist_ok=True)

            manifesto = ManifestoManager(DIR_DATA_RAW / slug, empresa=slug)

            # Filtrar por código CVM ou CNPJ
            serie_filtro = df_indice[col_filtro].astype(str).str.strip()
            mascara = (
                (serie_filtro == codigo_cvm)
                | (serie_filtro.str.lstrip("0") == codigo_cvm.lstrip("0"))
                | (serie_filtro == cnpj)
                | (serie_filtro == cnpj_fmt)
            )
            df_empresa = df_indice[mascara]

            # Filtrar por categorias de interesse
            if col_categoria and col_categoria in df_empresa.columns:
                df_empresa = df_empresa[
                    df_empresa[col_categoria].isin(categorias)
                ]

            if df_empresa.empty:
                logger.debug("Nenhum IPE para %s em %d", slug, ano)
                continue

            logger.info(
                "IPE %d/%s: %d documentos encontrados nas categorias selecionadas",
                ano,
                slug,
                len(df_empresa),
            )

            # Baixar cada PDF
            docs_processados = 0
            for _, row in df_empresa.iterrows():
                link_doc = row.get(col_link, "")
                if not link_doc or not isinstance(link_doc, str):
                    continue

                # Montar nome do arquivo
                data_ref = str(row.get(col_data, "sem_data")).replace("/", "-")
                categoria = _sanitizar_nome(str(row.get(col_categoria, "doc")))

                # Identificador único do documento
                protocolo = str(row.get("Protocolo_Entrega", "")).strip()
                if not protocolo:
                    m_prot = re.search(r"numProtocolo=(\d+)", link_doc)
                    protocolo = m_prot.group(1) if m_prot else ""

                m_seq = re.search(r"numSequencia=(\d+)", link_doc)
                seq = m_seq.group(1) if m_seq else ""

                if protocolo:
                    id_doc = f"prot_{protocolo}" + (f"_seq_{seq}" if seq else "")
                else:
                    partes_url = link_doc.rstrip("/").split("/")
                    id_doc = _sanitizar_nome(partes_url[-1]) if partes_url else "doc"

                nome_base = f"{data_ref}_{categoria}_{id_doc}"
                arquivo_rel_pdf = f"{saida_dir_rel}/{nome_base}.pdf"
                arquivo_rel_html = f"{saida_dir_rel}/{nome_base}.html"

                # Idempotência
                if manifesto.ja_ingerido_arquivo(arquivo_rel_pdf) or manifesto.ja_ingerido_arquivo(arquivo_rel_html):
                    logger.debug("Já ingerido, pulando: %s", nome_base)
                    continue

                if dry_run:
                    logger.info("[DRY-RUN]   → %s ← %s", dir_empresa_ipe / f"{nome_base}.pdf", link_doc)
                    continue

                # Download do conteúdo
                try:
                    conteudo = download_com_retry(link_doc, desc=nome_base)
                except ConnectionError as e:
                    logger.warning(
                        "Falha ao baixar documento %s: %s. Continuando...",
                        link_doc,
                        e,
                    )
                    continue

                if not isinstance(conteudo, bytes) or len(conteudo) == 0:
                    continue

                # Validação de formato: PDF real vs formulário HTML
                if conteudo.startswith(b"%PDF"):
                    ext = ".pdf"
                    tipo_mime = "application/pdf"
                else:
                    # Casca ASP.NET vazia da CVM (formulário sem anexo)
                    if len(conteudo) < 8000 and (b"__VIEWSTATE" in conteudo or b"<html" in conteudo.lower()):
                        corpo = re.search(rb"<body[^>]*>(.*?)</body>", conteudo, re.DOTALL | re.IGNORECASE)
                        texto_limpo = re.sub(rb"<[^>]+>", b"", corpo.group(1)).strip() if corpo else b""
                        if len(texto_limpo) == 0:
                            logger.debug("Documento sem anexo binário (casca web vazia): %s", link_doc)
                            continue
                    ext = ".html"
                    tipo_mime = "text/html"

                nome_arquivo = f"{nome_base}{ext}"
                caminho_arquivo = dir_empresa_ipe / nome_arquivo
                arquivo_rel = f"{saida_dir_rel}/{nome_arquivo}"

                caminho_arquivo.write_bytes(conteudo)
                logger.info("Salvo documento %s (%d bytes)", nome_arquivo, len(conteudo))

                # Registrar no manifesto
                hash_arq = calcular_sha256(caminho_arquivo)
                manifesto.registrar(
                    url_origem=link_doc,
                    arquivo_local=arquivo_rel,
                    hash_sha256=hash_arq,
                    tipo_fonte="cvm_ipe",
                    metadados_extra={
                        "ano": ano,
                        "categoria": str(row.get(col_categoria, "")),
                        "data_referencia": data_ref,
                        "protocolo": protocolo,
                        "formato": tipo_mime,
                    },
                )
                contagem[slug] = contagem.get(slug, 0) + 1
                docs_processados += 1

                # Respeitar delay entre downloads para não sobrecarregar portal CVM
                if delay > 0:
                    time.sleep(delay)

                if max_documentos and docs_processados >= max_documentos:
                    logger.info(
                        "Limite de %d documentos atingido para %s.",
                        max_documentos,
                        slug,
                    )
                    break

    # Resumo
    total = sum(contagem.values())
    logger.info(
        "Ingestão CVM IPE concluída: %d PDFs baixados. %s",
        total,
        contagem,
    )
    return contagem
