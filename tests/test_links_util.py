"""
Testes unitários para o módulo de links utilitários.
"""

from __future__ import annotations

from src.dados.links_util import (
    resolver_link_cvm,
    resolver_link_documento_marco,
    resolver_link_tribunal,
    sanitizar_cnj,
)


def test_sanitizar_cnj():
    assert sanitizar_cnj(" 1057756-77.2019.8.26.0100 ") == "1057756-77.2019.8.26.0100"
    assert sanitizar_cnj(None) == ""


def test_resolver_link_tribunal_tjsp():
    link = resolver_link_tribunal("1057756-77.2019.8.26.0100", "TJSP")
    assert "esaj.tjsp.jus.br" in link
    assert "cbPesquisa=NUMPROC" in link
    assert "1057756-77.2019.8.26.0100" in link


def test_resolver_link_tribunal_tjrj():
    link = resolver_link_tribunal("0033100-84.2023.8.19.0001", "TJRJ")
    assert "tjrj.jus.br" in link
    assert "0033100-84.2023.8.19.0001" in link


def test_resolver_link_cvm():
    link = resolver_link_cvm("11312")
    assert "rad.cvm.gov.br" in link
    assert "codigoCVM=11312" in link

    link_vazio = resolver_link_cvm("")
    assert "dados.cvm.gov.br" in link_vazio


def test_resolver_link_documento_marco_substitui_generico():
    # URL genérica https://esaj.tjsp.jus.br deve ser substituída pela busca direta do CNJ
    link = resolver_link_documento_marco(
        url_existente="https://esaj.tjsp.jus.br",
        numero_cnj="1057756-77.2019.8.26.0100",
        tribunal="TJSP",
        empresa_slug="novonor-odebrecht",
    )
    assert link != "https://esaj.tjsp.jus.br"
    assert "cbPesquisa=NUMPROC" in link


def test_resolver_link_documento_marco_cvm():
    link = resolver_link_documento_marco(
        url_existente="",
        numero_cnj="0033100-84.2023.8.19.0001",
        tribunal="TJRJ",
        empresa_slug="oi",
        tipo_evento="FATO_RELEVANTE_CVM",
        autor="CVM",
    )
    assert "rad.cvm.gov.br" in link
    assert "codigoCVM=11312" in link
