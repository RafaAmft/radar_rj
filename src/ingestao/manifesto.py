"""
Gerenciador do manifesto de ingestão (ingestion_manifest.json).

Cada empresa possui um manifesto próprio em data/raw/<empresa>/ingestion_manifest.json.
O manifesto registra todas as ingestões feitas, com URL de origem, hash SHA-256,
timestamp e tipo de fonte, permitindo idempotência e auditoria.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

VERSAO_MANIFESTO = "1.0"


class ManifestoManager:
    """Gerencia o ingestion_manifest.json de uma empresa ou diretório."""

    def __init__(self, diretorio: str | Path, empresa: str = ""):
        """
        Args:
            diretorio: Diretório onde o manifesto será salvo/lido.
            empresa: Nome/slug da empresa (ex: "oi", "americanas").
        """
        self.diretorio = Path(diretorio)
        self.empresa = empresa
        self.caminho = self.diretorio / "ingestion_manifest.json"
        self._dados: dict[str, Any] = self._carregar()

    def _carregar(self) -> dict[str, Any]:
        """Carrega manifesto existente ou cria um novo."""
        if self.caminho.exists():
            try:
                with open(self.caminho, "r", encoding="utf-8") as f:
                    dados = json.load(f)
                logger.debug("Manifesto carregado: %s", self.caminho)
                return dados
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(
                    "Manifesto corrompido, criando novo: %s (%s)", self.caminho, e
                )

        return {
            "versao": VERSAO_MANIFESTO,
            "empresa": self.empresa,
            "gerado_em": self._agora_iso(),
            "entradas": [],
        }

    def _salvar(self) -> None:
        """Persiste o manifesto em disco."""
        self.diretorio.mkdir(parents=True, exist_ok=True)
        self._dados["atualizado_em"] = self._agora_iso()
        with open(self.caminho, "w", encoding="utf-8") as f:
            json.dump(self._dados, f, ensure_ascii=False, indent=2)
        logger.debug("Manifesto salvo: %s", self.caminho)

    @staticmethod
    def _agora_iso() -> str:
        """Retorna timestamp ISO 8601 com timezone."""
        return datetime.now(timezone.utc).isoformat()

    def registrar(
        self,
        url_origem: str,
        arquivo_local: str,
        hash_sha256: str,
        tipo_fonte: str,
        status: str = "ok",
        metadados_extra: dict[str, Any] | None = None,
    ) -> None:
        """
        Registra uma entrada de ingestão no manifesto.

        Args:
            url_origem: URL de onde o dado foi baixado.
            arquivo_local: Caminho relativo ao diretório da empresa.
            hash_sha256: Hash SHA-256 do arquivo local.
            tipo_fonte: Tipo de fonte (ex: "cvm_dfp", "cvm_ipe", "itd", "esaj").
            status: Status da ingestão ("ok", "fallback_metadados", "erro").
            metadados_extra: Dict com metadados adicionais opcionais.
        """
        entrada: dict[str, Any] = {
            "url_origem": url_origem,
            "arquivo_local": arquivo_local,
            "hash_sha256": hash_sha256,
            "timestamp_ingestao": self._agora_iso(),
            "tipo_fonte": tipo_fonte,
            "status": status,
        }
        if metadados_extra:
            entrada["metadados"] = metadados_extra

        self._dados["entradas"].append(entrada)
        self._salvar()

        logger.info(
            "Registrado no manifesto: %s → %s [%s]",
            tipo_fonte,
            arquivo_local,
            status,
        )

    def ja_ingerido(self, url_origem: str) -> bool:
        """
        Verifica se uma URL já foi ingerida com sucesso.

        Returns:
            True se a URL já consta no manifesto com status 'ok'.
        """
        return any(
            e.get("url_origem") == url_origem and e.get("status") == "ok"
            for e in self._dados.get("entradas", [])
        )

    def ja_ingerido_arquivo(self, arquivo_local: str) -> bool:
        """
        Verifica se um arquivo local já foi registrado com sucesso.

        Returns:
            True se o arquivo já consta no manifesto com status 'ok'.
        """
        return any(
            e.get("arquivo_local") == arquivo_local and e.get("status") == "ok"
            for e in self._dados.get("entradas", [])
        )

    @property
    def total_entradas(self) -> int:
        """Retorna o número total de entradas no manifesto."""
        return len(self._dados.get("entradas", []))

    @property
    def entradas(self) -> list[dict[str, Any]]:
        """Retorna a lista de entradas do manifesto."""
        return self._dados.get("entradas", [])

    def resumo(self) -> dict[str, int]:
        """
        Retorna contagem de entradas por tipo_fonte e status.

        Returns:
            Dict no formato {"cvm_dfp:ok": 5, "esaj:fallback_metadados": 1}.
        """
        contagem: dict[str, int] = {}
        for e in self.entradas:
            chave = f"{e.get('tipo_fonte', '?')}:{e.get('status', '?')}"
            contagem[chave] = contagem.get(chave, 0) + 1
        return contagem
