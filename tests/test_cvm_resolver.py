"""
Testes unitários para o CvmResolver.
"""

from __future__ import annotations

from src.dados.cvm_resolver import CvmResolver, cvm_resolver


def test_cvm_resolver_overrides_conhecidos():
    # PDG Realty
    pdg = cvm_resolver.resolver(slug="pdg-realty")
    assert pdg is not None
    assert pdg["codigo_cvm"] == "20478"
    assert pdg["ticker"] == "PDGR3"

    # Oi S.A.
    oi = cvm_resolver.resolver(slug="oi")
    assert oi is not None
    assert oi["codigo_cvm"] == "11312"

    # Americanas S.A.
    amer = cvm_resolver.resolver(termo_busca="Americanas")
    assert amer is not None
    assert amer["codigo_cvm"] == "20990"


def test_cvm_resolver_sanitizar_cnpj():
    assert CvmResolver.sanitizar_cnpj("02.950.811/0001-89") == "02950811000189"
    assert CvmResolver.sanitizar_cnpj(None) == ""


def test_cvm_resolver_buscar_por_cnpj_raiz():
    # CNPJ raiz da PDG Realty
    res = cvm_resolver.buscar_por_cnpj("02.950.811/0001-89")
    assert res is not None
    assert res["codigo_cvm"] == "20478"


def test_cvm_resolver_nao_encontrado():
    res = cvm_resolver.resolver(cnpj="99999999999999", termo_busca="EMPRESA_INEXISTENTE_XYZ")
    assert res is None
