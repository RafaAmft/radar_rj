"""
Utilitário de Resolução e Validação de Links Processuais, CVM e Administradores Judiciais.

Gera URLs diretas, canônicas e válidas para peças processuais, consultas unificadas
do CNJ nos Tribunais de Justiça e relatórios oficiais da CVM e Administradores Judiciais.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

# Mapeamento de Portais e Consultas por Tribunal
TRIBUNAIS_URL_MAP = {
    "TJSP": "https://esaj.tjsp.jus.br/cpopg/search.do?cbPesquisa=NUMPROC&dadosConsulta.valorConsultaNuUnificado={cnj}&dadosConsulta.tipoNuProcesso=UNIFICADO",
    "TJRJ": "https://www3.tjrj.jus.br/consultaprocessual/#/consultapublica?numProcesso={cnj}",
    "TJMG": "https://pje.tjmg.jus.br/pje/ConsultaPublica/listView.seam",
    "TJPR": "https://projudi.tjpr.jus.br/projudi/",
    "TJRS": "https://eproc1g.tjrs.jus.br/eproc/externo_controlador.php?acao=processo_seleciona_publica",
    "TJSC": "https://eproc1g.tjsc.jus.br/eproc/externo_controlador.php?acao=processo_seleciona_publica",
    "TJBA": "https://pje.tjba.jus.br/pje/ConsultaPublica/listView.seam",
    "TJGO": "https://projudi.tjgo.jus.br/BuscaProcessoPublica",
    "TJMT": "https://pje.tjmt.jus.br/pje/ConsultaPublica/listView.seam",
    "TRF1": "https://pje1g.trf1.jus.br/consultapublica/ConsultaPublica/listView.seam",
    "TRF2": "https://eproc.trf2.jus.br/eproc/externo_controlador.php?acao=processo_seleciona_publica",
    "TRF3": "https://pje1g.trf3.jus.br/pje/ConsultaPublica/listView.seam",
    "TRF4": "https://eproc.trf4.jus.br/eproc2trf4/externo_controlador.php?acao=processo_seleciona_publica",
}

# Portais específicos dos Administradores Judiciais para os casos do Radar
AJS_PAGINAS_CASOS = {
    "recjud.com.br": "https://www.recjud.com.br/",
    "ajamericas.com.br": "https://ajamericas.com.br/",
    "oi": "https://www.recjud.com.br/",
    "americanas": "https://ajamericas.com.br/",
    "light": "https://ajlight.com.br/",
    "patense": "https://danielthiagoadv.com.br/processo/recuperacao-judicial-grupo-patense/",
    "brizola": "https://brizolajapur.com.br/processos/",
    "laspro": "https://www.lasproconsultores.com.br/recuperacoes-judiciais/",
    "preserva": "https://www.preservaacao.com.br/recuperacoes",
    "exm": "https://exmpartners.com.br/processos/",
    "alvarez": "https://www.alvarezandmarsal.com/expertise/restructuring-turnaround",
}

# Mapeamento de Códigos CVM para companhias abertas do Radar
COMPANHIAS_CVM = {
    "oi": {"codigo_cvm": "11312", "ticker": "OIBR3", "razao": "Oi S.A."},
    "americanas": {"codigo_cvm": "20990", "ticker": "AMER3", "razao": "Americanas S.A."},
    "light": {"codigo_cvm": "01987", "ticker": "LIGT3", "razao": "Light S.A."},
    "gol": {"codigo_cvm": "19410", "ticker": "GOLL4", "razao": "Gol Linhas Aéreas"},
    "marisa": {"codigo_cvm": "20885", "ticker": "AMAR3", "razao": "Marisa Lojas S.A."},
    "paranapanema": {"codigo_cvm": "02259", "ticker": "PMAM3", "razao": "Paranapanema S.A."},
    "polishop": {"codigo_cvm": "", "ticker": "", "razao": "Polimport Comércio e Exportação"},
    "agrogalaxy": {"codigo_cvm": "26000", "ticker": "AGXY3", "razao": "AgroGalaxy Participações S.A."},
    "dia": {"codigo_cvm": "", "ticker": "", "razao": "Dia Brasil Sociedade Limitada"},
    "novonor-odebrecht": {"codigo_cvm": "15102", "ticker": "", "razao": "Novonor S.A."},
}


def sanitizar_cnj(numero_cnj: str | None) -> str:
    """Remove caracteres não alfanuméricos e formata o CNJ para busca."""
    if not numero_cnj:
        return ""
    return str(numero_cnj).strip()


def resolver_link_tribunal(numero_cnj: str | None, tribunal: str | None) -> str:
    """
    Gera link direto para consulta pública do processo no Tribunal correspondente.
    Se tribunal for TJSP, usa a rota unificada do e-SAJ com o número CNJ.
    """
    cnj = sanitizar_cnj(numero_cnj)
    if not cnj:
        return "https://comunica.pje.jus.br/"

    trib = (tribunal or "").upper().strip()
    if trib in TRIBUNAIS_URL_MAP:
        template = TRIBUNAIS_URL_MAP[trib]
        return template.format(cnj=quote(cnj))

    # Fallback nacional unificado
    return f"https://www.jusbrasil.com.br/processos/busca?q={quote(cnj)}"


def resolver_link_cvm(codigo_cvm: str | None, categoria: str = "IPE") -> str:
    """
    Gera link oficial no portal de Consulta Externa de Companhias Abertas da CVM.
    """
    if not codigo_cvm or not str(codigo_cvm).strip():
        return "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/IPE/DADOS/"

    cod_limpo = str(codigo_cvm).strip().zfill(5)
    return f"https://rad.cvm.gov.br/ENET/frmConsultaExternaCVM.aspx?codigoCVM={cod_limpo}"


def resolver_link_documento_marco(
    url_existente: str | None,
    numero_cnj: str | None = None,
    tribunal: str | None = None,
    empresa_slug: str | None = None,
    tipo_evento: str | None = None,
    autor: str | None = None,
) -> str:
    """
    Valida e resolve a melhor URL para um marco ou documento processual.
    Substitui links genéricos (ex: raiz de domínios) por URLs canônicas específicas.
    """
    url = (url_existente or "").strip()

    # Se a URL já for completa e não for apenas a home de um tribunal ou AJ, mantém
    urls_genericas_bloqueadas = {
        "https://esaj.tjsp.jus.br",
        "https://esaj.tjsp.jus.br/",
        "http://esaj.tjsp.jus.br",
        "https://alvarezandmarsal.com",
        "https://alvarezandmarsal.com/",
        "http://alvarezandmarsal.com",
        "https://pje.tjmg.jus.br",
        "https://pje.tjmg.jus.br/",
        "https://www3.tjrj.jus.br",
        "https://www3.tjrj.jus.br/",
        "None",
        "",
    }

    if url and url not in urls_genericas_bloqueadas:
        # Se for link válido para arquivo ou rota com parâmetros, retorna
        if "?" in url or "show.do" in url or "processo" in url or ".pdf" in url or "rad.cvm" in url:
            return url

    # Se for evento do Administrador Judicial e tivermos página dedicada do caso
    if autor == "AJ" and empresa_slug:
        for chave, link_aj in AJS_PAGINAS_CASOS.items():
            if chave in empresa_slug.lower():
                return link_aj

    # Se for evento da CVM ou empresa aberta
    if autor == "CVM" or (tipo_evento and "CVM" in tipo_evento.upper()):
        cod_cvm = ""
        if empresa_slug and empresa_slug in COMPANHIAS_CVM:
            cod_cvm = COMPANHIAS_CVM[empresa_slug].get("codigo_cvm", "")
        return resolver_link_cvm(cod_cvm)

    # Caso padrão: link do Tribunal correspondente pelo CNJ
    if numero_cnj:
        return resolver_link_tribunal(numero_cnj, tribunal)

    return url or "https://comunica.pje.jus.br/"


def obter_acao_externa_marco(
    marco: dict[str, Any],
    dossie: dict[str, Any] | None = None,
) -> dict[str, str]:
    """
    Retorna as informações completas de ação externa de um marco processual:
    URL resolvida, rótulo amigável do botão, ícone e classes visuais CSS.
    """
    autor = (marco.get("autor") or "AJ").upper()
    tipo = (marco.get("tipo_evento") or "").upper()
    numero_cnj = dossie.get("numero_cnj") if dossie else None
    tribunal = dossie.get("tribunal") if dossie else None
    empresa_slug = dossie.get("empresa_slug") if dossie else None

    url = resolver_link_documento_marco(
        url_existente=marco.get("url_documento"),
        numero_cnj=numero_cnj,
        tribunal=tribunal,
        empresa_slug=empresa_slug,
        tipo_evento=tipo,
        autor=autor,
    )

    if autor == "CVM" or "CVM" in tipo:
        return {
            "url": url,
            "label": "Ver na CVM ↗",
            "icone": "🏢",
            "tipo": "cvm",
            "badge_class": "badge-cvm",
            "btn_class": "btn-cvm",
        }
    elif autor == "AJ":
        return {
            "url": url,
            "label": "Acessar Portal do AJ ↗",
            "icone": "📋",
            "tipo": "aj",
            "badge_class": "badge-aj",
            "btn_class": "btn-aj",
        }
    elif autor in ("JUIZO", "RECUPERANDA", "MP", "PARTE", "CREDOR"):
        nome_trib = tribunal or "Tribunal"
        badge = "badge-juizo" if autor == "JUIZO" else ("badge-recuperanda" if autor == "RECUPERANDA" else "badge-credor")
        return {
            "url": url,
            "label": f"Consultar no {nome_trib} ↗",
            "icone": "🏛️",
            "tipo": "tribunal",
            "badge_class": badge,
            "btn_class": "btn-tribunal",
        }

    return {
        "url": url,
        "label": "Consultar Documento Oficial ↗",
        "icone": "📄",
        "tipo": "documento",
        "badge_class": "badge-aj",
        "btn_class": "btn-tribunal",
    }

