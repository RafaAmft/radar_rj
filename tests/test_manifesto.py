"""Testes do ManifestoManager."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.ingestao.manifesto import ManifestoManager, VERSAO_MANIFESTO


@pytest.fixture
def dir_temp(tmp_path: Path) -> Path:
    """Diretório temporário para testes."""
    return tmp_path / "empresa_teste"


class TestManifestoManager:
    """Testes do gerenciador de manifesto."""

    def test_cria_manifesto_novo(self, dir_temp: Path) -> None:
        """Manifesto é criado com estrutura correta quando não existe."""
        m = ManifestoManager(dir_temp, empresa="teste")

        assert m.total_entradas == 0
        assert m.empresa == "teste"

    def test_registrar_entrada(self, dir_temp: Path) -> None:
        """Registro de entrada adiciona ao manifesto e salva em disco."""
        m = ManifestoManager(dir_temp, empresa="teste")

        m.registrar(
            url_origem="https://exemplo.com/dados.zip",
            arquivo_local="cvm/dfp_itr/BPA_2024.csv",
            hash_sha256="abc123def456",
            tipo_fonte="cvm_dfp",
        )

        assert m.total_entradas == 1
        assert m.caminho.exists()

        # Verificar conteúdo salvo em disco
        with open(m.caminho, "r", encoding="utf-8") as f:
            dados = json.load(f)

        assert dados["versao"] == VERSAO_MANIFESTO
        assert dados["empresa"] == "teste"
        assert len(dados["entradas"]) == 1
        assert dados["entradas"][0]["url_origem"] == "https://exemplo.com/dados.zip"
        assert dados["entradas"][0]["hash_sha256"] == "abc123def456"
        assert dados["entradas"][0]["status"] == "ok"

    def test_ja_ingerido_url(self, dir_temp: Path) -> None:
        """ja_ingerido retorna True para URLs já registradas com status ok."""
        m = ManifestoManager(dir_temp, empresa="teste")
        url = "https://exemplo.com/dados.zip"

        assert m.ja_ingerido(url) is False

        m.registrar(
            url_origem=url,
            arquivo_local="arquivo.csv",
            hash_sha256="hash123",
            tipo_fonte="cvm_dfp",
        )

        assert m.ja_ingerido(url) is True

    def test_ja_ingerido_arquivo(self, dir_temp: Path) -> None:
        """ja_ingerido_arquivo retorna True para arquivos já registrados."""
        m = ManifestoManager(dir_temp, empresa="teste")
        arq = "cvm/dfp_itr/BPA_2024.csv"

        assert m.ja_ingerido_arquivo(arq) is False

        m.registrar(
            url_origem="https://exemplo.com/x.zip",
            arquivo_local=arq,
            hash_sha256="hash456",
            tipo_fonte="cvm_dfp",
        )

        assert m.ja_ingerido_arquivo(arq) is True

    def test_idempotencia_nao_bloqueia_status_diferente(
        self, dir_temp: Path
    ) -> None:
        """ja_ingerido retorna False para entradas com status != ok."""
        m = ManifestoManager(dir_temp, empresa="teste")
        url = "https://exemplo.com/dados.zip"

        m.registrar(
            url_origem=url,
            arquivo_local="arquivo.csv",
            hash_sha256="hash123",
            tipo_fonte="esaj",
            status="fallback_metadados",
        )

        # fallback_metadados não conta como "ok"
        assert m.ja_ingerido(url) is False

    def test_persistencia_entre_instancias(self, dir_temp: Path) -> None:
        """Dados persistem entre instâncias do ManifestoManager."""
        m1 = ManifestoManager(dir_temp, empresa="teste")
        m1.registrar(
            url_origem="https://url1.com",
            arquivo_local="arq1.csv",
            hash_sha256="h1",
            tipo_fonte="cvm_dfp",
        )

        # Nova instância deve carregar os dados
        m2 = ManifestoManager(dir_temp, empresa="teste")
        assert m2.total_entradas == 1
        assert m2.ja_ingerido("https://url1.com") is True

    def test_multiplos_registros(self, dir_temp: Path) -> None:
        """Múltiplos registros são acumulados corretamente."""
        m = ManifestoManager(dir_temp, empresa="teste")

        for i in range(5):
            m.registrar(
                url_origem=f"https://url{i}.com",
                arquivo_local=f"arq_{i}.csv",
                hash_sha256=f"hash_{i}",
                tipo_fonte="cvm_dfp",
            )

        assert m.total_entradas == 5

    def test_resumo(self, dir_temp: Path) -> None:
        """Resumo agrupa por tipo_fonte:status."""
        m = ManifestoManager(dir_temp, empresa="teste")

        m.registrar("u1", "a1", "h1", "cvm_dfp")
        m.registrar("u2", "a2", "h2", "cvm_dfp")
        m.registrar("u3", "a3", "h3", "cvm_ipe")
        m.registrar("u4", "a4", "h4", "esaj", status="fallback_metadados")

        resumo = m.resumo()
        assert resumo["cvm_dfp:ok"] == 2
        assert resumo["cvm_ipe:ok"] == 1
        assert resumo["esaj:fallback_metadados"] == 1

    def test_metadados_extra(self, dir_temp: Path) -> None:
        """Metadados extras são armazenados corretamente."""
        m = ManifestoManager(dir_temp, empresa="teste")

        m.registrar(
            url_origem="https://url.com",
            arquivo_local="arq.csv",
            hash_sha256="hash",
            tipo_fonte="cvm_dfp",
            metadados_extra={"ano": 2024, "tipo_demonstracao": "BPA"},
        )

        entrada = m.entradas[0]
        assert entrada["metadados"]["ano"] == 2024
        assert entrada["metadados"]["tipo_demonstracao"] == "BPA"
