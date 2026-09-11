"""Testes dos utilitários de download."""

from __future__ import annotations

import hashlib
import zipfile
import io
from pathlib import Path

import pytest

from src.ingestao.download import (
    calcular_sha256,
    calcular_sha256_bytes,
    extrair_zip_em_memoria,
    carregar_yaml,
)


class TestSHA256:
    """Testes de cálculo de hash SHA-256."""

    def test_hash_arquivo(self, tmp_path: Path) -> None:
        """Calcula hash SHA-256 de um arquivo corretamente."""
        conteudo = b"dados de teste para hash"
        arquivo = tmp_path / "teste.txt"
        arquivo.write_bytes(conteudo)

        resultado = calcular_sha256(arquivo)
        esperado = hashlib.sha256(conteudo).hexdigest()

        assert resultado == esperado
        assert len(resultado) == 64  # SHA-256 = 64 chars hex

    def test_hash_bytes(self) -> None:
        """Calcula hash SHA-256 de bytes corretamente."""
        conteudo = b"dados de teste para hash"
        resultado = calcular_sha256_bytes(conteudo)
        esperado = hashlib.sha256(conteudo).hexdigest()

        assert resultado == esperado

    def test_hash_arquivo_vazio(self, tmp_path: Path) -> None:
        """Hash de arquivo vazio é determinístico."""
        arquivo = tmp_path / "vazio.txt"
        arquivo.write_bytes(b"")

        resultado = calcular_sha256(arquivo)
        esperado = hashlib.sha256(b"").hexdigest()

        assert resultado == esperado

    def test_hashes_diferentes(self, tmp_path: Path) -> None:
        """Conteúdos diferentes produzem hashes diferentes."""
        arq1 = tmp_path / "a.txt"
        arq2 = tmp_path / "b.txt"
        arq1.write_bytes(b"conteudo A")
        arq2.write_bytes(b"conteudo B")

        assert calcular_sha256(arq1) != calcular_sha256(arq2)


class TestExtrairZip:
    """Testes de extração de ZIP em memória."""

    def _criar_zip(self, arquivos: dict[str, bytes]) -> bytes:
        """Helper: cria um ZIP em memória com os arquivos fornecidos."""
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for nome, conteudo in arquivos.items():
                zf.writestr(nome, conteudo)
        return buffer.getvalue()

    def test_extrai_arquivos(self) -> None:
        """Extrai corretamente os arquivos de um ZIP."""
        arquivos_originais = {
            "dados.csv": b"col1;col2\nval1;val2",
            "info.txt": b"informacao qualquer",
        }
        zip_bytes = self._criar_zip(arquivos_originais)

        resultado = extrair_zip_em_memoria(zip_bytes)

        assert set(resultado.keys()) == {"dados.csv", "info.txt"}
        assert resultado["dados.csv"] == b"col1;col2\nval1;val2"
        assert resultado["info.txt"] == b"informacao qualquer"

    def test_ignora_diretorios(self) -> None:
        """Diretórios dentro do ZIP são ignorados."""
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as zf:
            zf.writestr("pasta/", "")
            zf.writestr("pasta/arquivo.txt", b"conteudo")
        zip_bytes = buffer.getvalue()

        resultado = extrair_zip_em_memoria(zip_bytes)

        assert "pasta/" not in resultado
        assert "pasta/arquivo.txt" in resultado

    def test_zip_vazio(self) -> None:
        """ZIP sem arquivos retorna dict vazio."""
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as zf:
            pass
        zip_bytes = buffer.getvalue()

        resultado = extrair_zip_em_memoria(zip_bytes)
        assert resultado == {}


class TestCarregarYaml:
    """Testes de carregamento de YAML."""

    def test_carrega_yaml_valido(self, tmp_path: Path) -> None:
        """Carrega um arquivo YAML válido."""
        conteudo = "chave: valor\nlista:\n  - item1\n  - item2\n"
        arquivo = tmp_path / "config.yaml"
        arquivo.write_text(conteudo, encoding="utf-8")

        resultado = carregar_yaml(arquivo)

        assert resultado["chave"] == "valor"
        assert resultado["lista"] == ["item1", "item2"]

    def test_arquivo_nao_existe(self, tmp_path: Path) -> None:
        """Lança FileNotFoundError para arquivo inexistente."""
        with pytest.raises(FileNotFoundError):
            carregar_yaml(tmp_path / "inexistente.yaml")
