"""
Módulo de Resolução Automática de Companhias Abertas da CVM.

Cruza informações cadastrais (CNPJ, Razão Social, Ticker e Nome Fantasia) com a base oficial
aberta da Comissão de Valores Mobiliários (cad_cia_aberta.csv) disponibilizada pelo Governo Federal.
"""

from __future__ import annotations

import io
import logging
import re
import urllib.request
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

URL_CADASTRO_CVM = "https://dados.cvm.gov.br/dados/CIA_ABERTA/CAD/DADOS/cad_cia_aberta.csv"
CAMINHO_CACHE_PADRAO = Path(__file__).resolve().parent.parent.parent / "data" / "cad_cia_aberta.csv"

# Tabela de referência direta e alta prioridade para o ecossistema de RJs do Radar
CVM_OVERRIDES: dict[str, dict[str, str]] = {
    "pdg": {"codigo_cvm": "20478", "ticker": "PDGR3", "razao": "PDG Realty S.A. Empreendimentos e Participações", "cnpj_raiz": "02950811"},
    "pdg-realty": {"codigo_cvm": "20478", "ticker": "PDGR3", "razao": "PDG Realty S.A. Empreendimentos e Participações", "cnpj_raiz": "02950811"},
    "oi": {"codigo_cvm": "11312", "ticker": "OIBR3", "razao": "Oi S.A. - Em Recuperação Judicial", "cnpj_raiz": "76535764"},
    "americanas": {"codigo_cvm": "20990", "ticker": "AMER3", "razao": "Americanas S.A. - Em Recuperação Judicial", "cnpj_raiz": "00776574"},
    "light": {"codigo_cvm": "01987", "ticker": "LIGT3", "razao": "Light S.A.", "cnpj_raiz": "03378521"},
    "gol": {"codigo_cvm": "19410", "ticker": "GOLL4", "razao": "Gol Linhas Aéreas Inteligentes S.A.", "cnpj_raiz": "06164253"},
    "marisa": {"codigo_cvm": "20885", "ticker": "AMAR3", "razao": "Marisa Lojas S.A.", "cnpj_raiz": "61189288"},
    "paranapanema": {"codigo_cvm": "02259", "ticker": "PMAM3", "razao": "Paranapanema S.A.", "cnpj_raiz": "00302481"},
    "agrogalaxy": {"codigo_cvm": "26000", "ticker": "AGXY3", "razao": "AgroGalaxy Participações S.A.", "cnpj_raiz": "34914101"},
    "novonor-odebrecht": {"codigo_cvm": "15102", "ticker": "", "razao": "Novonor S.A.", "cnpj_raiz": "15102288"},
    "osx": {"codigo_cvm": "21342", "ticker": "OSXB3", "razao": "OSX Brasil S.A.", "cnpj_raiz": "09112683"},
    "unigel": {"codigo_cvm": "26301", "ticker": "", "razao": "Unigel Participações S.A.", "cnpj_raiz": "08320485"},
    "saraiva": {"codigo_cvm": "02216", "ticker": "SLED4", "razao": "Saraiva Livreiros S.A.", "cnpj_raiz": "61365284"},
    "lupatech": {"codigo_cvm": "20290", "ticker": "LUPA3", "razao": "Lupatech S.A.", "cnpj_raiz": "89463822"},
    "viver": {"codigo_cvm": "21016", "ticker": "VIVR3", "razao": "Viver Incorporadora e Construtora S.A.", "cnpj_raiz": "08343492"},
    "invepar": {"codigo_cvm": "22551", "ticker": "IVPR4", "razao": "Investimentos e Participações em Infraestrutura S.A.", "cnpj_raiz": "03758318"},
    "triunfo": {"codigo_cvm": "20044", "ticker": "TPIS3", "razao": "Triunfo Participações e Investimentos S.A.", "cnpj_raiz": "03052718"},
    "renova": {"codigo_cvm": "22004", "ticker": "RNEW4", "razao": "Renova Energia S.A.", "cnpj_raiz": "04495756"},
}


class CvmResolver:
    """
    Gerenciador e resolvedor dinâmico de códigos de registro da CVM.
    Permite busca por CNPJ raiz, CNPJ completo ou denominação social.
    """

    def __init__(self, caminho_cache: Path | str = CAMINHO_CACHE_PADRAO):
        self.caminho_cache = Path(caminho_cache)
        self._df_cvm: pd.DataFrame | None = None

    @staticmethod
    def sanitizar_cnpj(cnpj: str | None) -> str:
        """Mantém apenas dígitos do CNPJ."""
        if not cnpj:
            return ""
        return re.sub(r"\D", "", str(cnpj)).strip()

    def carregar_dados(self, forcar_download: bool = False) -> pd.DataFrame:
        """
        Carrega o catálogo de companhias abertas da CVM do cache ou realiza o download.
        """
        if self._df_cvm is not None and not forcar_download:
            return self._df_cvm

        dados_bytes = None

        if self.caminho_cache.exists() and not forcar_download:
            try:
                dados_bytes = self.caminho_cache.read_bytes()
                logger.info("Carregado catálogo CVM do cache local: %s", self.caminho_cache)
            except Exception as e:
                logger.warning("Falha ao ler cache CVM local (%s). Baixando novamente...", e)

        if dados_bytes is None:
            try:
                logger.info("Baixando dados abertos oficiais da CVM (%s)...", URL_CADASTRO_CVM)
                req = urllib.request.Request(
                    URL_CADASTRO_CVM,
                    headers={"User-Agent": "RadarRJ/1.0 (Monitoramento de RJs)"},
                )
                with urllib.request.urlopen(req, timeout=15) as resp:
                    dados_bytes = resp.read()

                # Salvar em cache
                self.caminho_cache.parent.mkdir(parents=True, exist_ok=True)
                self.caminho_cache.write_bytes(dados_bytes)
                logger.info("Catálogo CVM salvo em cache: %s", self.caminho_cache)
            except Exception as e:
                logger.error("Erro ao baixar dados da CVM: %s", e)
                # Fallback: retorna DataFrame vazio mas operacional com overrides
                self._df_cvm = pd.DataFrame(columns=["CNPJ_LIMPO", "CNPJ_RAIZ", "DENOM_SOCIAL", "CD_CVM", "SIT"])
                return self._df_cvm

        try:
            df = pd.read_csv(io.BytesIO(dados_bytes), sep=";", encoding="latin1", dtype=str)
            df["CNPJ_LIMPO"] = df["CNPJ_CIA"].astype(str).str.replace(r"\D", "", regex=True)
            df["CNPJ_RAIZ"] = df["CNPJ_LIMPO"].str[:8]
            df["DENOM_NORMALIZADA"] = df["DENOM_SOCIAL"].astype(str).str.upper().str.strip()
            df["CD_CVM_NORM"] = df["CD_CVM"].astype(str).str.strip().str.zfill(5)
            self._df_cvm = df
            return self._df_cvm
        except Exception as e:
            logger.error("Erro ao processar CSV da CVM: %s", e)
            self._df_cvm = pd.DataFrame(columns=["CNPJ_LIMPO", "CNPJ_RAIZ", "DENOM_SOCIAL", "CD_CVM", "SIT"])
            return self._df_cvm

    def buscar_por_cnpj(self, cnpj: str | None) -> dict[str, Any] | None:
        """Localiza a companhia aberta na CVM por CNPJ completo ou CNPJ raiz (8 dígitos)."""
        cnpj_limpo = self.sanitizar_cnpj(cnpj)
        if not cnpj_limpo or len(cnpj_limpo) < 8:
            return None

        # 1. Checar overrides
        cnpj_raiz = cnpj_limpo[:8]
        for key, val in CVM_OVERRIDES.items():
            if val.get("cnpj_raiz") == cnpj_raiz:
                return {
                    "codigo_cvm": str(val["codigo_cvm"]).zfill(5),
                    "ticker": val.get("ticker", ""),
                    "razao_social": val.get("razao", ""),
                    "cnpj": cnpj_limpo,
                    "situacao": "ATIVO",
                }

        df = self.carregar_dados()
        if df.empty:
            return None

        # 2. Busca por CNPJ completo (14 dígitos)
        if len(cnpj_limpo) == 14:
            match = df[df["CNPJ_LIMPO"] == cnpj_limpo]
            if not match.empty:
                row = match.iloc[0]
                return {
                    "codigo_cvm": str(row["CD_CVM_NORM"]),
                    "ticker": "",
                    "razao_social": str(row["DENOM_SOCIAL"]),
                    "cnpj": str(row["CNPJ_CIA"]),
                    "situacao": str(row.get("SIT", "ATIVO")),
                }

        # 3. Busca por CNPJ raiz (8 dígitos)
        match_raiz = df[df["CNPJ_RAIZ"] == cnpj_raiz]
        if not match_raiz.empty:
            row = match_raiz.iloc[0]
            return {
                "codigo_cvm": str(row["CD_CVM_NORM"]),
                "ticker": "",
                "razao_social": str(row["DENOM_SOCIAL"]),
                "cnpj": str(row["CNPJ_CIA"]),
                "situacao": str(row.get("SIT", "ATIVO")),
            }

        return None

    def buscar_por_termo(self, termo: str | None) -> dict[str, Any] | None:
        """Localiza companhia por ticker ou fragmento relevante de razão social."""
        if not termo or not str(termo).strip():
            return None

        termo_limpo = str(termo).upper().strip()

        # Checar overrides por chave ou ticker
        for key, val in CVM_OVERRIDES.items():
            if (
                key.upper() in termo_limpo
                or termo_limpo in key.upper()
                or (val.get("ticker") and val["ticker"].upper() in termo_limpo)
            ):
                return {
                    "codigo_cvm": str(val["codigo_cvm"]).zfill(5),
                    "ticker": val.get("ticker", ""),
                    "razao_social": val.get("razao", ""),
                    "cnpj": val.get("cnpj_raiz", ""),
                    "situacao": "ATIVO",
                }

        df = self.carregar_dados()
        if df.empty:
            return None

        # Buscar por termo na denominação social
        matches = df[df["DENOM_NORMALIZADA"].str.contains(re.escape(termo_limpo), na=False)]
        if not matches.empty:
            # Priorizar ativas
            ativas = matches[matches["SIT"] == "ATIVO"]
            row = ativas.iloc[0] if not ativas.empty else matches.iloc[0]
            return {
                "codigo_cvm": str(row["CD_CVM_NORM"]),
                "ticker": "",
                "razao_social": str(row["DENOM_SOCIAL"]),
                "cnpj": str(row["CNPJ_CIA"]),
                "situacao": str(row.get("SIT", "ATIVO")),
            }

        return None

    def resolver(
        self,
        cnpj: str | None = None,
        termo_busca: str | None = None,
        slug: str | None = None,
    ) -> dict[str, Any] | None:
        """
        Método de resolução unificado:
        1. Avalia slug nos overrides prioritários
        2. Avalia CNPJ (14 dígitos ou raiz)
        3. Avalia termo textual ou razão social
        """
        if slug:
            slug_norm = slug.lower().strip()
            for key, val in CVM_OVERRIDES.items():
                if key in slug_norm or slug_norm in key:
                    return {
                        "codigo_cvm": str(val["codigo_cvm"]).zfill(5),
                        "ticker": val.get("ticker", ""),
                        "razao_social": val.get("razao", ""),
                        "cnpj": val.get("cnpj_raiz", ""),
                        "situacao": "ATIVO",
                    }

        if cnpj:
            res_cnpj = self.buscar_por_cnpj(cnpj)
            if res_cnpj:
                return res_cnpj

        if termo_busca:
            res_termo = self.buscar_por_termo(termo_busca)
            if res_termo:
                return res_termo

        return None


# Instância global singleton para reuso em todo o projeto
cvm_resolver = CvmResolver()


def obter_info_cvm(
    cnpj: str | None = None,
    razao_social: str | None = None,
    slug: str | None = None,
) -> dict[str, Any] | None:
    """Função utilitária rápida para resolver dados de companhia aberta na CVM."""
    return cvm_resolver.resolver(cnpj=cnpj, termo_busca=razao_social, slug=slug)
