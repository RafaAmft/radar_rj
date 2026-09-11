"""
Extrator 4: e-SAJ TJSP — Scraping Best-Effort de processos de Recuperação Judicial.

Implementação com Selenium headless para consulta pública nominal no e-SAJ.
Se o scraping falhar (captcha, bloqueio, timeout), cai automaticamente para
fallback DataJud/CNJ (metadados apenas, sem texto integral).

⚠️  Este extrator é o mais frágil do pipeline (D4). O pipeline não depende
    dele para funcionar — os extratores 1-3 já fornecem material suficiente.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

import requests

from src.ingestao.download import (
    DIR_DATA_RAW,
    HEADERS_PADRAO,
    calcular_sha256,
    calcular_sha256_bytes,
    carregar_config_empresas,
    carregar_config_fonte,
)
from src.ingestao.manifesto import ManifestoManager

logger = logging.getLogger(__name__)


def _tentar_scraping_esaj(
    razao_social: str,
    dir_saida: Path,
    config: dict,
) -> list[dict]:
    """
    Tenta o scraping do e-SAJ via Selenium.

    Returns:
        Lista de dicts com metadados dos processos encontrados/baixados.
        Lista vazia se falhar.
    """
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait
    except ImportError:
        logger.warning(
            "Selenium não instalado. Instale com: pip install selenium"
        )
        return []

    timeout = config.get("selenium_timeout", 30)
    delay = config.get("delay_entre_acoes", 2.0)
    max_tentativas = config.get("max_tentativas_scraping", 2)
    url_busca = config["urls"]["esaj_busca"]

    for tentativa in range(1, max_tentativas + 1):
        driver = None
        try:
            logger.info(
                "[e-SAJ] Tentativa %d/%d para '%s'",
                tentativa,
                max_tentativas,
                razao_social,
            )

            # Configurar Chrome headless
            options = Options()
            options.add_argument("--headless=new")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-gpu")
            options.add_argument(
                f"--user-agent={HEADERS_PADRAO['User-Agent']}"
            )

            driver = webdriver.Chrome(options=options)
            driver.set_page_load_timeout(timeout)
            wait = WebDriverWait(driver, timeout)

            # Navegar para a busca
            driver.get(url_busca)
            time.sleep(delay)

            # Tentar localizar campo de busca por nome da parte
            # O e-SAJ tem diferentes layouts; tentamos seletores conhecidos
            seletor_combinado = (
                "#campo_pesquisa, "
                "#numProcesso, "
                "input[name='dadosConsulta.valorConsultaNuUnificado'], "
                "input[name='dadosConsulta.valorConsulta']"
            )
            try:
                campo_busca = wait.until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, seletor_combinado))
                )
            except Exception:
                campo_busca = None

            if not campo_busca:
                logger.warning(
                    "[e-SAJ] Campo de busca não encontrado. "
                    "Layout pode ter mudado."
                )
                continue

            # Preencher e submeter
            campo_busca.clear()
            campo_busca.send_keys(razao_social)
            time.sleep(delay)

            # Tentar submeter formulário
            for seletor_btn in [
                "#botaoConsultarProcessos",
                "input[type='submit']",
                "button[type='submit']",
            ]:
                try:
                    btn = driver.find_element(By.CSS_SELECTOR, seletor_btn)
                    btn.click()
                    break
                except Exception:
                    continue

            time.sleep(delay * 2)

            # Verificar se há captcha
            page_source = driver.page_source.lower()
            if "captcha" in page_source or "recaptcha" in page_source:
                logger.warning("[e-SAJ] Captcha detectado. Abortando scraping.")
                continue

            # Extrair resultados (metadados mínimos dos processos listados)
            resultados = []
            try:
                linhas = driver.find_elements(
                    By.CSS_SELECTOR, ".resultadoProcesso, .processoTr, tr.fundocinza1, tr.fundocinza2"
                )
                for linha in linhas[:10]:  # limitar a 10 processos
                    texto = linha.text
                    if texto.strip():
                        resultados.append({
                            "texto_resultado": texto[:500],
                            "fonte": "esaj_scraping",
                        })
            except Exception:
                pass

            if resultados:
                logger.info(
                    "[e-SAJ] %d resultados encontrados para '%s'",
                    len(resultados),
                    razao_social,
                )
                return resultados

            logger.info("[e-SAJ] Nenhum resultado encontrado na tentativa %d", tentativa)

        except Exception as e:
            logger.warning(
                "[e-SAJ] Erro na tentativa %d: %s", tentativa, e
            )

        finally:
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass

    logger.warning(
        "[e-SAJ] Todas as %d tentativas falharam para '%s'",
        max_tentativas,
        razao_social,
    )
    return []


def _fallback_datajud(
    razao_social: str,
    dir_saida: Path,
    config: dict,
) -> list[dict]:
    """
    Fallback: consulta API pública do DataJud (CNJ) para metadados processuais.

    A API do DataJud retorna apenas metadados (número, classe, valor da causa,
    movimentações), sem texto integral de peças.
    """
    url_api = config["urls"]["datajud_api"]
    classe = config["classe_processual"]

    logger.info(
        "[DataJud] Fallback: buscando metadados de '%s' (classe: %s)...",
        razao_social,
        classe,
    )

    # Query Elasticsearch do DataJud
    query = {
        "size": 10,
        "query": {
            "bool": {
                "must": [
                    {
                        "match": {
                            "dadosBasicos.polo.parte.pessoa.nome": razao_social
                        }
                    }
                ],
                "filter": [
                    {
                        "match": {
                            "dadosBasicos.classeProcessual": classe
                        }
                    }
                ],
            }
        },
        "_source": [
            "dadosBasicos.numero",
            "dadosBasicos.classeProcessual",
            "dadosBasicos.dataAjuizamento",
            "dadosBasicos.valorCausa",
            "dadosBasicos.orgaoJulgador",
            "dadosBasicos.polo",
            "movimento",
        ],
    }

    api_key = os.environ.get(
        "DATAJUD_API_KEY",
        "cDZHYzlZa0JadVREZDJCendQbXY6SkJlTzNjLV9TRENyQk1RdnFKZGRQdw==",
    )
    auth_header = api_key if api_key.startswith("APIKey ") else f"APIKey {api_key}"

    headers = {
        **HEADERS_PADRAO,
        "Content-Type": "application/json",
        "Authorization": auth_header,
    }

    try:
        resp = requests.post(
            url_api,
            json=query,
            headers=headers,
            timeout=30,
        )
        resp.raise_for_status()
        dados = resp.json()

        hits = dados.get("hits", {}).get("hits", [])
        logger.info(
            "[DataJud] %d resultados encontrados para '%s'",
            len(hits),
            razao_social,
        )

        resultados = []
        for hit in hits:
            source = hit.get("_source", {})
            basicos = source.get("dadosBasicos", {})
            resultado = {
                "numero_processo": basicos.get("numero", ""),
                "classe_processual": basicos.get("classeProcessual", ""),
                "data_ajuizamento": basicos.get("dataAjuizamento", ""),
                "valor_causa": basicos.get("valorCausa", ""),
                "orgao_julgador": basicos.get("orgaoJulgador", {}),
                "fonte": "datajud_fallback",
            }

            # Extrair últimas movimentações (limitar a 20)
            movimentos = source.get("movimento", [])
            if movimentos:
                resultado["movimentacoes"] = [
                    {
                        "data": m.get("dataHora", ""),
                        "nome": m.get("nome", ""),
                        "complemento": (m.get("complementosTabelados") or [{}])[0].get("descricao", "")
                        if m.get("complementosTabelados")
                        else "",
                    }
                    for m in movimentos[:20]
                ]

            resultados.append(resultado)

        return resultados

    except requests.RequestException as e:
        logger.error("[DataJud] Falha na consulta: %s", e)
        return []


def executar(
    slugs_empresa: list[str] | None = None,
    dry_run: bool = False,
) -> dict[str, str]:
    """
    Executa a ingestão de processos de RJ via e-SAJ + fallback DataJud.

    Args:
        slugs_empresa: Lista de slugs das empresas a processar (None = todas).
        dry_run: Se True, apenas mostra o que faria.

    Returns:
        Dict com status por empresa: "scraping_ok", "fallback_metadados", "sem_dados".
    """
    config_empresas = carregar_config_empresas()
    config_fonte = carregar_config_fonte("esaj")
    saida_dir_rel = config_fonte["saida_dir"]

    empresas = config_empresas["empresas"]
    if slugs_empresa:
        empresas = [e for e in empresas if e["slug"] in slugs_empresa]

    status_por_empresa: dict[str, str] = {}

    for empresa in empresas:
        slug = empresa["slug"]
        razao_social = empresa["razao_social"]
        dir_saida = DIR_DATA_RAW / slug / saida_dir_rel
        dir_saida.mkdir(parents=True, exist_ok=True)

        manifesto = ManifestoManager(DIR_DATA_RAW / slug, empresa=slug)

        if dry_run:
            logger.info(
                "[DRY-RUN] Buscaria processos de RJ para '%s' no e-SAJ",
                razao_social,
            )
            status_por_empresa[slug] = "dry_run"
            continue

        logger.info("=" * 60)
        logger.info("Processando: %s", razao_social)
        logger.info("=" * 60)

        # Tentativa 1: Scraping e-SAJ
        resultados = _tentar_scraping_esaj(razao_social, dir_saida, config_fonte)

        if resultados:
            # Salvar resultados do scraping
            for i, res in enumerate(resultados):
                nome = f"esaj_resultado_{i+1:03d}.json"
                caminho = dir_saida / nome
                conteudo = json.dumps(res, ensure_ascii=False, indent=2)
                caminho.write_text(conteudo, encoding="utf-8")

                manifesto.registrar(
                    url_origem=config_fonte["urls"]["esaj_busca"],
                    arquivo_local=f"{saida_dir_rel}/{nome}",
                    hash_sha256=calcular_sha256(caminho),
                    tipo_fonte="esaj",
                    status="ok",
                )

            status_por_empresa[slug] = "scraping_ok"
            continue

        # Tentativa 2: Fallback DataJud
        logger.info("[%s] Scraping falhou. Ativando fallback DataJud...", slug)
        resultados = _fallback_datajud(razao_social, dir_saida, config_fonte)

        if resultados:
            for i, res in enumerate(resultados):
                numero = res.get("numero_processo", f"proc_{i+1}")
                numero_limpo = str(numero).replace(".", "_").replace("-", "_")
                nome = f"metadados_{numero_limpo}.json"
                caminho = dir_saida / nome
                conteudo = json.dumps(res, ensure_ascii=False, indent=2)
                caminho.write_text(conteudo, encoding="utf-8")

                manifesto.registrar(
                    url_origem=config_fonte["urls"]["datajud_api"],
                    arquivo_local=f"{saida_dir_rel}/{nome}",
                    hash_sha256=calcular_sha256(caminho),
                    tipo_fonte="esaj",
                    status="fallback_metadados",
                    metadados_extra={
                        "numero_processo": str(numero),
                        "fonte_fallback": "datajud_cnj",
                    },
                )

            status_por_empresa[slug] = "fallback_metadados"
        else:
            status_por_empresa[slug] = "sem_dados"
            logger.warning(
                "[%s] Nenhum dado obtido (scraping + fallback)", slug
            )

    # Resumo
    logger.info("Ingestão e-SAJ concluída: %s", status_por_empresa)
    return status_por_empresa
