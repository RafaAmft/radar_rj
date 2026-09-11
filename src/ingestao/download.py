"""
Utilitários de download, hash e extração de arquivos.

Funções compartilhadas por todos os extratores:
- download_com_retry: download resiliente com backoff exponencial
- calcular_sha256: hash SHA-256 de arquivo local
- extrair_zip_em_memoria: lê ZIP de bytes e retorna dict {nome: conteúdo}
- carregar_yaml: carrega YAML de config
"""

from __future__ import annotations

import hashlib
import io
import logging
import time
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
import yaml
from tqdm import tqdm

logger = logging.getLogger(__name__)

# Raiz do projeto (dois níveis acima de src/ingestao/)
RAIZ_PROJETO = Path(__file__).resolve().parent.parent.parent
DIR_CONFIG = RAIZ_PROJETO / "config"
DIR_DATA_RAW = RAIZ_PROJETO / "data" / "raw"

# Headers padrão para requests (simular navegador comum)
HEADERS_PADRAO = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Controle global de taxa de requisições por domínio
_ULTIMA_REQUISICAO_POR_DOMINIO: dict[str, float] = {}


def resetar_rate_limit() -> None:
    """Limpa o registro de requisições por domínio (útil para testes)."""
    _ULTIMA_REQUISICAO_POR_DOMINIO.clear()


def aplicar_rate_limit(url_ou_dominio: str, delay_minimo: float = 1.0) -> float:
    """
    Garante um intervalo mínimo entre requisições consecutivas ao mesmo domínio/host.

    Args:
        url_ou_dominio: URL completa ou nome de domínio/host (ex: 'dados.cvm.gov.br').
        delay_minimo: Tempo mínimo em segundos entre chamadas ao mesmo domínio.

    Returns:
        Tempo em segundos que a execução esperou (0.0 se não precisou pausar).
    """
    if delay_minimo <= 0:
        return 0.0

    if "://" in url_ou_dominio:
        dominio = urlparse(url_ou_dominio).netloc.lower()
    else:
        dominio = url_ou_dominio.lower()

    agora = time.time()
    ultimo_acesso = _ULTIMA_REQUISICAO_POR_DOMINIO.get(dominio, 0.0)
    tempo_passado = agora - ultimo_acesso
    tempo_espera = 0.0

    if tempo_passado < delay_minimo:
        tempo_espera = delay_minimo - tempo_passado
        logger.debug(
            "Rate limit [%s]: aguardando %.2fs antes da próxima requisição",
            dominio,
            tempo_espera,
        )
        time.sleep(tempo_espera)

    _ULTIMA_REQUISICAO_POR_DOMINIO[dominio] = time.time()
    return tempo_espera


def carregar_yaml(caminho: str | Path) -> dict[str, Any]:
    """Carrega e retorna o conteúdo de um arquivo YAML."""
    caminho = Path(caminho)
    if not caminho.exists():
        raise FileNotFoundError(f"Arquivo de configuração não encontrado: {caminho}")
    with open(caminho, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def carregar_config_empresas() -> dict[str, Any]:
    """Carrega config/empresas.yaml."""
    return carregar_yaml(DIR_CONFIG / "empresas.yaml")


def carregar_config_fonte(nome_fonte: str) -> dict[str, Any]:
    """Carrega config/fontes/<nome_fonte>.yaml."""
    return carregar_yaml(DIR_CONFIG / "fontes" / f"{nome_fonte}.yaml")


def calcular_sha256(caminho: str | Path) -> str:
    """Calcula o hash SHA-256 de um arquivo local."""
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()


def calcular_sha256_bytes(conteudo: bytes) -> str:
    """Calcula o hash SHA-256 de um conteúdo em bytes."""
    return hashlib.sha256(conteudo).hexdigest()


def download_com_retry(
    url: str,
    destino: str | Path | None = None,
    max_tentativas: int = 3,
    timeout: int = 60,
    stream: bool = False,
    desc: str | None = None,
    delay_rate_limit: float = 1.0,
) -> bytes | Path:
    """
    Faz download de uma URL com retry e backoff exponencial.

    Args:
        url: URL para download.
        destino: Caminho local para salvar. Se None, retorna bytes.
        max_tentativas: Número máximo de tentativas.
        timeout: Timeout em segundos por tentativa.
        stream: Se True, faz download em streaming (para arquivos grandes).
        desc: Descrição para a barra de progresso.
        delay_rate_limit: Intervalo mínimo em segundos entre downloads do mesmo domínio.

    Returns:
        Se destino fornecido, retorna Path do arquivo salvo.
        Se destino é None, retorna bytes do conteúdo.
    """
    ultima_excecao = None

    for tentativa in range(1, max_tentativas + 1):
        try:
            aplicar_rate_limit(url, delay_minimo=delay_rate_limit)
            logger.info(
                "Download [%d/%d]: %s", tentativa, max_tentativas, url
            )
            resp = requests.get(
                url, headers=HEADERS_PADRAO, timeout=timeout, stream=stream
            )
            resp.raise_for_status()

            if destino is not None:
                destino = Path(destino)
                destino.parent.mkdir(parents=True, exist_ok=True)

                tamanho_total = int(resp.headers.get("content-length", 0))
                desc_barra = desc or destino.name

                with open(destino, "wb") as f:
                    if stream and tamanho_total > 0:
                        with tqdm(
                            total=tamanho_total,
                            unit="B",
                            unit_scale=True,
                            desc=desc_barra,
                        ) as barra:
                            for chunk in resp.iter_content(chunk_size=8192):
                                f.write(chunk)
                                barra.update(len(chunk))
                    elif stream:
                        for chunk in resp.iter_content(chunk_size=8192):
                            f.write(chunk)
                    else:
                        f.write(resp.content)

                logger.info("Salvo em: %s", destino)
                return destino

            return resp.content

        except (requests.RequestException, IOError) as e:
            ultima_excecao = e
            if tentativa < max_tentativas:
                espera = 2**tentativa
                logger.warning(
                    "Falha na tentativa %d: %s. Aguardando %ds...",
                    tentativa,
                    e,
                    espera,
                )
                time.sleep(espera)
            else:
                logger.error(
                    "Todas as %d tentativas falharam para: %s",
                    max_tentativas,
                    url,
                )

    raise ConnectionError(
        f"Download falhou após {max_tentativas} tentativas: {url}"
    ) from ultima_excecao


def extrair_zip_em_memoria(conteudo_zip: bytes) -> dict[str, bytes]:
    """
    Extrai um ZIP a partir de bytes em memória.

    Returns:
        Dict mapeando nome do arquivo interno → conteúdo em bytes.
    """
    resultado = {}
    with zipfile.ZipFile(io.BytesIO(conteudo_zip)) as zf:
        for nome in zf.namelist():
            if not nome.endswith("/"):  # pular diretórios
                resultado[nome] = zf.read(nome)
    return resultado


def verificar_tamanho_remoto(url: str, timeout: int = 15) -> int | None:
    """
    Faz um HEAD request para obter o Content-Length de um recurso remoto.

    Returns:
        Tamanho em bytes, ou None se não disponível.
    """
    try:
        resp = requests.head(url, headers=HEADERS_PADRAO, timeout=timeout)
        resp.raise_for_status()
        cl = resp.headers.get("content-length")
        return int(cl) if cl else None
    except requests.RequestException:
        return None
