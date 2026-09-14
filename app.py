"""
Radar RJ - Plataforma de Inteligência em Recuperações Judiciais & Distressed Assets.

Dashboard analítico construído em Streamlit apresentando:
1. Ranking das maiores Recuperações Judiciais do Brasil
2. Página dedicada de Linha do Tempo Processual & Documentos da CVM
3. Manifestações e Relatórios Mensais de Atividades (RMAs) dos Administradores Judiciais
4. Decomposição detalhada de passivos concursais por classes da Lei 11.101/05
5. Simulador financeiro de cessão de créditos e distressed assets
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# Configuração de caminhos do projeto
ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.banco.repositorio import BancoDados
from src.dados.links_util import (
    COMPANHIAS_CVM,
    resolver_link_cvm,
    resolver_link_documento_marco,
    resolver_link_tribunal,
)
from src.visualizacao.timeline_dupla import renderizar_timeline_dupla

# Configuração de Página Streamlit
st.set_page_config(
    page_title="Radar RJ - Inteligência em Recuperações Judiciais",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Estilização CSS personalizada (Dark Mode Sofisticado & Glassmorphism)
CUSTOM_CSS = """
<style>
    /* Estilo Geral */
    .stApp {
        background-color: #0B0F19;
        color: #E2E8F0;
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    }
    
    /* Top Header e Títulos */
    h1, h2, h3, h4 {
        color: #F8FAFC !important;
        font-weight: 700;
        letter-spacing: -0.02em;
    }
    
    /* Cards Métricas / KPI */
    .kpi-card {
        background: linear-gradient(135deg, #131D31 0%, #0F172A 100%);
        border: 1px solid #1E293B;
        border-radius: 12px;
        padding: 20px 24px;
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.25);
        transition: transform 0.2s ease, border-color 0.2s ease;
    }
    .kpi-card:hover {
        transform: translateY(-2px);
        border-color: #38BDF8;
    }
    .kpi-title {
        color: #94A3B8;
        font-size: 0.85rem;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        margin-bottom: 6px;
    }
    .kpi-value {
        color: #F8FAFC;
        font-size: 1.9rem;
        font-weight: 800;
    }
    .kpi-subtitle {
        color: #38BDF8;
        font-size: 0.8rem;
        margin-top: 4px;
    }
    
    /* Timeline Card */
    .timeline-item {
        position: relative;
        padding-left: 32px;
        margin-bottom: 24px;
        border-left: 2px solid #334155;
    }
    .timeline-dot {
        position: absolute;
        left: -9px;
        top: 0;
        width: 16px;
        height: 16px;
        border-radius: 50%;
        background-color: #38BDF8;
        border: 3px solid #0B0F19;
    }
    .timeline-card {
        background-color: #131D31;
        border: 1px solid #1E293B;
        border-radius: 10px;
        padding: 18px 22px;
        box-shadow: 0 4px 15px rgba(0, 0, 0, 0.2);
    }
    
    /* Badges de Órgãos e Atores */
    .badge-juizo { background-color: #1E3A8A; color: #93C5FD; padding: 4px 12px; border-radius: 12px; font-size: 0.75rem; font-weight: 600; }
    .badge-aj { background-color: #064E3B; color: #6EE7B7; padding: 4px 12px; border-radius: 12px; font-size: 0.75rem; font-weight: 600; }
    .badge-recuperanda { background-color: #78350F; color: #FCD34D; padding: 4px 12px; border-radius: 12px; font-size: 0.75rem; font-weight: 600; }
    .badge-credor { background-color: #581C87; color: #D8B4FE; padding: 4px 12px; border-radius: 12px; font-size: 0.75rem; font-weight: 600; }
    .badge-cvm { background-color: #4C1D95; color: #E9D5FF; padding: 4px 12px; border-radius: 12px; font-size: 0.75rem; font-weight: 700; border: 1px solid #7C3AED; }
    
    /* Botões de Ação Direta */
    .btn-tribunal {
        display: inline-block;
        margin-top: 10px;
        margin-right: 8px;
        background-color: #1E40AF;
        color: #FFFFFF !important;
        padding: 6px 14px;
        border-radius: 6px;
        text-decoration: none !important;
        font-size: 0.8rem;
        font-weight: 600;
        transition: background-color 0.2s;
    }
    .btn-tribunal:hover { background-color: #2563EB; }
    
    .btn-cvm {
        display: inline-block;
        margin-top: 10px;
        margin-right: 8px;
        background-color: #6D28D9;
        color: #FFFFFF !important;
        padding: 6px 14px;
        border-radius: 6px;
        text-decoration: none !important;
        font-size: 0.8rem;
        font-weight: 600;
        transition: background-color 0.2s;
    }
    .btn-cvm:hover { background-color: #7C3AED; }
    
    .btn-aj {
        display: inline-block;
        margin-top: 10px;
        margin-right: 8px;
        background-color: #047857;
        color: #FFFFFF !important;
        padding: 6px 14px;
        border-radius: 6px;
        text-decoration: none !important;
        font-size: 0.8rem;
        font-weight: 600;
        transition: background-color 0.2s;
    }
    .btn-aj:hover { background-color: #059669; }

    /* Custom Tabs */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
        background-color: #0F172A;
        padding: 6px;
        border-radius: 10px;
        border: 1px solid #1E293B;
    }
    .stTabs [data-baseweb="tab"] {
        border-radius: 8px;
        color: #94A3B8;
        padding: 8px 18px;
    }
    .stTabs [aria-selected="true"] {
        background-color: #2563EB !important;
        color: #FFFFFF !important;
    }
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


@st.cache_resource
def get_banco() -> BancoDados:
    """Instância singleton do repositório SQLite com auto-seed em ambiente web."""
    banco = BancoDados("data/radar.db")
    banco.inicializar_schema()
    stats = banco.obter_estatisticas_gerais()
    if stats.get("total_processos", 0) == 0:
        from scripts.carregar_top50_banco import carregar_catalogo_para_banco
        carregar_catalogo_para_banco("data/radar.db")
    return banco


banco = get_banco()


# ------------------------------------------------------------------------------
# SIDEBAR: Navegação Principal e Filtros Globais
# ------------------------------------------------------------------------------
with st.sidebar:
    st.markdown(
        """
        <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 20px;">
            <div style="background: linear-gradient(135deg, #2563EB, #38BDF8); width: 44px; height: 44px; border-radius: 10px; display: flex; align-items: center; justify-content: center; font-size: 24px;">⚖️</div>
            <div>
                <h3 style="margin: 0; font-size: 1.3rem;">RADAR RJ</h3>
                <span style="font-size: 0.75rem; color: #94A3B8; letter-spacing: 0.05em; text-transform: uppercase;">Inteligência Concursal & CVM</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("### 🧭 Navegação")
    pagina_selecionada = st.radio(
        "Selecione o Módulo",
        [
            "📊 Visão Geral & Ranking Top 50",
            "⏳ Linha do Tempo & Documentos CVM",
            "📑 Relatórios & Manifestações do AJ",
            "💳 Quadro de Credores & Dívidas",
            "💡 Simulador de Crédito Concursal",
        ],
        index=0,
        label_visibility="collapsed",
    )

    st.markdown("---")
    st.markdown("### 🔎 Filtros Globais")
    termo_busca = st.text_input("Buscar Empresa, CNJ ou AJ", placeholder="Ex: Oi, Americanas, 1057756...")

    # Dados base para alimentar opções dos selects
    todos_processos = banco.obter_top_processos(limite=200)
    df_base = pd.DataFrame(todos_processos)

    tribunais_disponiveis = ["Todos"] + sorted(list(df_base["tribunal"].dropna().unique())) if not df_base.empty else ["Todos"]
    filtro_tribunal = st.selectbox("Tribunal", tribunais_disponiveis)

    setores_disponiveis = ["Todos"] + sorted(list(df_base["setor"].dropna().unique())) if not df_base.empty else ["Todos"]
    filtro_setor = st.selectbox("Setor Econômico", setores_disponiveis)

    ajs_disponiveis = ["Todos"] + sorted(list(df_base["administrador_judicial"].dropna().unique())) if not df_base.empty else ["Todos"]
    filtro_aj = st.selectbox("Administrador Judicial", ajs_disponiveis)

    st.markdown("---")
    stats_gerais = banco.obter_estatisticas_gerais()
    st.markdown("#### 📊 Dimensão da Base")
    st.markdown(f"• **{stats_gerais.get('total_empresas', 0)}** Empresas Monitoradas")
    st.markdown(f"• **{stats_gerais.get('total_processos', 0)}** Processos Judiciais")
    st.markdown(f"• **{stats_gerais.get('total_marcos', 0)}** Marcos Cronológicos")
    st.markdown(f"• **{stats_gerais.get('total_documentos', 0)}** Documentos & Peças Catalogados")
    st.markdown(f"• **{stats_gerais.get('total_credores', 0)}** Credores Habilitados")
    st.markdown("---")
    st.caption("Radar RJ © 2026 • Plataforma de Inteligência em Distressed Assets")


# ------------------------------------------------------------------------------
# APLICAÇÃO DOS FILTROS
# ------------------------------------------------------------------------------
tribunal_param = "" if filtro_tribunal == "Todos" else filtro_tribunal
setor_param = "" if filtro_setor == "Todos" else filtro_setor
processos_filtrados = banco.obter_top_processos(
    limite=100,
    tribunal=tribunal_param,
    setor=setor_param,
    busca=termo_busca,
)

if filtro_aj != "Todos":
    processos_filtrados = [p for p in processos_filtrados if p.get("administrador_judicial") == filtro_aj]

df_filtrado = pd.DataFrame(processos_filtrados)


# ==============================================================================
# PÁGINA 1: VISÃO GERAL & RANKING TOP 50
# ==============================================================================
if pagina_selecionada == "📊 Visão Geral & Ranking Top 50":
    st.markdown(
        """
        <div style="margin-bottom: 24px;">
            <h1 style="margin-bottom: 4px;">Monitor Nacional das Maiores Recuperações Judiciais</h1>
            <p style="color: #94A3B8; font-size: 1.05rem; margin-top: 0;">
                Catálogo executivo de distressed assets, passivos concursais e acompanhamento de grandes litígios empresariais.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Cards KPI
    passivo_total = sum(p["valor_causa"] for p in processos_filtrados) if processos_filtrados else 0.0
    casos_ativos = len(processos_filtrados)
    passivo_medio = passivo_total / casos_ativos if casos_ativos > 0 else 0.0
    ajs_ativos = len(set(p.get("administrador_judicial") for p in processos_filtrados if p.get("administrador_judicial")))

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(
            f"""
            <div class="kpi-card">
                <div class="kpi-title">Volume Total de Dívida</div>
                <div class="kpi-value">R$ {passivo_total / 1e9:.1f}B</div>
                <div class="kpi-subtitle">Passivo concursal agregado</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with c2:
        st.markdown(
            f"""
            <div class="kpi-card">
                <div class="kpi-title">Casos Filtrados</div>
                <div class="kpi-value">{casos_ativos}</div>
                <div class="kpi-subtitle">RJs sob monitoramento</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with c3:
        st.markdown(
            f"""
            <div class="kpi-card">
                <div class="kpi-title">Passivo Médio / Caso</div>
                <div class="kpi-value">R$ {passivo_medio / 1e9:.2f}B</div>
                <div class="kpi-subtitle">Ticket médio da amostra</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with c4:
        st.markdown(
            f"""
            <div class="kpi-card">
                <div class="kpi-title">Administradores Judiciais</div>
                <div class="kpi-value">{ajs_ativos}</div>
                <div class="kpi-subtitle">Firmas e escritórios nomeados</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown("<br>", unsafe_allow_html=True)

    if df_filtrado.empty:
        st.warning("Nenhum processo encontrado com os filtros selecionados.")
    else:
        # Gráficos Analíticos
        g_col1, g_col2 = st.columns([3, 2])
        with g_col1:
            st.markdown("#### 🏆 Top 10 Maiores Recuperações por Volume de Dívida")
            top10 = df_filtrado.head(10).copy()
            top10["valor_bi"] = top10["valor_causa"] / 1e9

            fig_bar = px.bar(
                top10,
                x="valor_bi",
                y="nome_razao_social",
                orientation="h",
                color="setor",
                text="valor_bi",
                labels={"valor_bi": "Passivo Declarado (R$ Bilhões)", "nome_razao_social": "Recuperanda / Grupo"},
                color_discrete_sequence=px.colors.qualitative.Prism,
            )
            fig_bar.update_layout(
                yaxis=dict(autorange="reversed"),
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#E2E8F0"),
                margin=dict(l=10, r=20, t=10, b=10),
                height=420,
            )
            fig_bar.update_traces(texttemplate='R$ %{text:.1f}B', textposition='outside')
            st.plotly_chart(fig_bar, use_container_width=True)

        with g_col2:
            st.markdown("#### 🏭 Concentração Setorial do Passivo")
            setor_agg = df_filtrado.groupby("setor")["valor_causa"].sum().reset_index()
            fig_pie = px.pie(
                setor_agg,
                values="valor_causa",
                names="setor",
                hole=0.45,
                color_discrete_sequence=px.colors.qualitative.Dark24,
            )
            fig_pie.update_layout(
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#E2E8F0"),
                margin=dict(l=10, r=10, t=10, b=10),
                height=420,
            )
            st.plotly_chart(fig_pie, use_container_width=True)

        st.markdown("---")
        st.markdown("### 📋 Tabela das Maiores Recuperações Judiciais")

        # Exibição da tabela principal com link funcional
        df_exibicao = df_filtrado.copy()
        df_exibicao["Valor Declarado"] = df_exibicao["valor_causa"].apply(lambda v: f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
        df_exibicao = df_exibicao[[
            "nome_razao_social", "setor", "tribunal", "numero_cnj", "Valor Declarado",
            "administrador_judicial", "status_processual", "data_distribuicao"
        ]].rename(columns={
            "nome_razao_social": "Empresa / Grupo",
            "setor": "Setor",
            "tribunal": "Tribunal",
            "numero_cnj": "Número CNJ",
            "administrador_judicial": "Administrador Judicial",
            "status_processual": "Status Processual",
            "data_distribuicao": "Data Distribuição",
        })
        st.dataframe(df_exibicao, use_container_width=True, height=450)


# ==============================================================================
# PÁGINA 2: LINHA DO TEMPO PROCESSUAL & DOCUMENTOS CVM (PÁGINA DEDICADA)
# ==============================================================================
elif pagina_selecionada == "⏳ Linha do Tempo & Documentos CVM":
    st.markdown(
        """
        <div style="margin-bottom: 24px;">
            <div style="display: flex; align-items: center; gap: 10px;">
                <h1 style="margin: 0;">Linha do Tempo Processual & Documentos da CVM</h1>
                <span class="badge-cvm">Módulo Exclusivo</span>
            </div>
            <p style="color: #94A3B8; font-size: 1.05rem; margin-top: 6px;">
                Rastreamento cronológico de atos do Judiciário, Fatos Relevantes CVM, Editais de Assembleia e Relatórios de Administradores Judiciais com links diretos validados.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Seletor do Caso
    opcoes_casos = {f"{p['nome_razao_social']} ({p.get('tribunal', 'N/A')} - {p.get('numero_cnj', 'S/N')})": (p.get("processo_id") or p.get("id")) for p in processos_filtrados}
    lista_nomes_casos = list(opcoes_casos.keys())

    col_sel1, col_sel2 = st.columns([4, 1.4])
    with col_sel1:
        caso_escolhido = st.selectbox("Selecione a Recuperanda / Processo Judicial:", lista_nomes_casos if lista_nomes_casos else ["Nenhum processo encontrado"])
    with col_sel2:
        st.markdown("<div style='margin-top: 28px;'></div>", unsafe_allow_html=True)
        btn_sync = st.button("🔄 Sincronizar e-SAJ", use_container_width=True, help="Consulta o Tribunal e-SAJ ao vivo e atualiza os marcos estratégicos")

    if not lista_nomes_casos or caso_escolhido == "Nenhum processo encontrado":
        st.warning("Nenhum processo disponível para visualização da linha do tempo.")
    else:
        proc_id = opcoes_casos[caso_escolhido]

        if btn_sync:
            with st.spinner("Consultando Tribunal e-SAJ e aplicando filtro de relevância..."):
                from scripts.sincronizar_movimentacoes_esaj import sincronizar_processo_esaj
                novos_marcos = sincronizar_processo_esaj(processo_id=proc_id, db_path="data/radar.db")
                if novos_marcos > 0:
                    st.success(f"Sucesso! {novos_marcos} novos marcos estratégicos adicionados.")
                else:
                    st.info("Processo já atualizado com as últimas movimentações disponíveis.")
                st.rerun()

        dossie = banco.obter_dossie_processo(proc_id)
        linha_tempo_bruta = banco.obter_linha_do_tempo(proc_id)
        documentos_processo = banco.obter_documentos_processo(proc_id)

        # KPIs no topo da página dedicada
        total_marcos_caso = len(linha_tempo_bruta)
        marcos_cvm = sum(1 for m in linha_tempo_bruta if m.get("autor") == "CVM" or "CVM" in m.get("tipo_evento", ""))
        marcos_juizo = sum(1 for m in linha_tempo_bruta if m.get("autor") == "JUIZO")
        marcos_aj = sum(1 for m in linha_tempo_bruta if m.get("autor") == "AJ")

        mk1, mk2, mk3, mk4 = st.columns(4)
        with mk1:
            st.markdown(
                f"""
                <div class="kpi-card">
                    <div class="kpi-title">Marcos do Caso</div>
                    <div class="kpi-value">{total_marcos_caso}</div>
                    <div class="kpi-subtitle">Atos registrados na cronologia</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with mk2:
            st.markdown(
                f"""
                <div class="kpi-card">
                    <div class="kpi-title">Documentos CVM</div>
                    <div class="kpi-value">{marcos_cvm}</div>
                    <div class="kpi-subtitle">Fatos Relevantes & IPE</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with mk3:
            st.markdown(
                f"""
                <div class="kpi-card">
                    <div class="kpi-title">Decisões Judiciais</div>
                    <div class="kpi-value">{marcos_juizo}</div>
                    <div class="kpi-subtitle">Despachos e sentenças</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with mk4:
            st.markdown(
                f"""
                <div class="kpi-card">
                    <div class="kpi-title">Peças do AJ</div>
                    <div class="kpi-value">{marcos_aj}</div>
                    <div class="kpi-subtitle">RMAs, Editais e Relatórios</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        st.markdown("<br>", unsafe_allow_html=True)

        # Abas internas da página dedicada: Cronologia Visual vs Repositório de Documentos
        subtab_cronologia, subtab_docs, subtab_todos_docs = st.tabs([
            "🕒 Cronologia Visual dos Atos (Timeline)",
            "📁 Peças e Documentos deste Caso",
            "🌐 Repositório Geral de Documentos CVM & Peças (Todos os Casos)",
        ])

        with subtab_cronologia:
            renderizar_timeline_dupla(processo_id=proc_id, dossie=dossie, db=banco)

        with subtab_docs:
            st.markdown(f"#### 📁 Documentos e Peças Catalogados de `{caso_escolhido}`")
            if not documentos_processo:
                st.info("Nenhum arquivo digital indexado individualmente para este processo ainda.")
            else:
                for doc in documentos_processo:
                    col_d1, col_d2, col_d3 = st.columns([5, 2, 2])
                    with col_d1:
                        st.markdown(f"**📄 {doc.get('titulo')}**")
                        st.caption(f"Identificador: `{doc.get('slug_documento', 'N/A')}`")
                    with col_d2:
                        cat = doc.get("categoria", "OUTROS")
                        if "CVM" in cat:
                            st.markdown(f"<span class='badge-cvm'>{cat}</span>", unsafe_allow_html=True)
                        else:
                            st.markdown(f"<span class='badge-juizo'>{cat}</span>", unsafe_allow_html=True)
                    with col_d3:
                        url_doc = doc.get("url_download") or resolver_link_tribunal(dossie.get("numero_cnj"), dossie.get("tribunal"))
                        st.markdown(f"<a href='{url_doc}' target='_blank' class='btn-tribunal' style='margin-top:0;'>Abrir Peça ↗</a>", unsafe_allow_html=True)
                    st.markdown("<hr style='margin: 8px 0; border-color: #1E293B;'>", unsafe_allow_html=True)

        with subtab_todos_docs:
            st.markdown("#### 🌐 Repositório Geral de Documentos CVM & Peças dos Tribunais")
            termo_doc = st.text_input("Filtrar documentos por palavra-chave (ex: Fato Relevante, PRJ, AGC, Homologação)", placeholder="Digite um termo para pesquisar...")
            filtro_cat = st.selectbox("Categoria de Documento:", ["Todos", "CVM_FATO_RELEVANTE", "INICIAL", "DECISAO", "PRJ", "AGC", "RMA", "QGC", "OUTROS"])

            docs_gerais = banco.obter_todos_documentos(limite=150, busca=termo_doc, categoria=filtro_cat)
            st.markdown(f"Localizados **{len(docs_gerais)} documentos** no acervo:")

            if docs_gerais:
                df_docs = pd.DataFrame(docs_gerais)
                df_docs_show = df_docs[[
                    "titulo", "categoria", "nome_razao_social", "tribunal", "numero_cnj", "url_download"
                ]].rename(columns={
                    "titulo": "Título do Documento / Peça",
                    "categoria": "Categoria",
                    "nome_razao_social": "Recuperanda",
                    "tribunal": "Tribunal / Órgão",
                    "numero_cnj": "Número CNJ",
                    "url_download": "Link de Acesso Oficial",
                })
                st.dataframe(
                    df_docs_show,
                    column_config={
                        "Link de Acesso Oficial": st.column_config.LinkColumn(
                            "Link de Acesso Oficial",
                            display_text="Acessar Documento ↗",
                        ),
                    },
                    use_container_width=True,
                    height=450,
                )


# ==============================================================================
# PÁGINA 3: MANIFESTAÇÕES & RELATÓRIOS DO AJ
# ==============================================================================
elif pagina_selecionada == "📑 Relatórios & Manifestações do AJ":
    st.markdown(
        """
        <div style="margin-bottom: 24px;">
            <h1 style="margin-bottom: 4px;">Relatórios Mensais de Atividades (RMAs) e Manifestações do AJ</h1>
            <p style="color: #94A3B8; font-size: 1.05rem; margin-top: 0;">
                Auditoria de despesas, caixa operacional, faturamento e cumprimento de obrigações sob fiscalização do Administrador Judicial.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    marcos_aj = banco.obter_marcos_por_tipo("RMA_AJ", limite=100)
    if not marcos_aj:
        st.info("Nenhum relatório de atividade do AJ registrado na base no momento.")
    else:
        st.markdown(f"Exibindo **{len(marcos_aj)} relatórios e manifestações** emitidos pelos Administradores Judiciais:")

        col_aj1, col_aj2 = st.columns([1, 1])
        for idx, r in enumerate(marcos_aj):
            target_col = col_aj1 if idx % 2 == 0 else col_aj2
            with target_col:
                link_relatorio = r.get("url_documento") or resolver_link_tribunal(r.get("numero_cnj"), r.get("tribunal"))
                st.markdown(
                    f"""
                    <div style="background-color: #131D31; border: 1px solid #1E293B; border-radius: 10px; padding: 20px; margin-bottom: 16px;">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                            <span class="badge-aj">📋 Relatório Mensal (RMA)</span>
                            <span style="color: #94A3B8; font-size: 0.85rem;">📅 {r.get('data_evento')}</span>
                        </div>
                        <h4 style="margin: 6px 0; color: #F8FAFC;">{r.get('nome_razao_social')}</h4>
                        <div style="color: #38BDF8; font-size: 0.85rem; margin-bottom: 8px;">
                            <strong>AJ:</strong> {r.get('administrador_judicial') or 'Não informado'} • <strong>Tribunal:</strong> {r.get('tribunal')}
                        </div>
                        <p style="color: #CBD5E1; font-size: 0.9rem; line-height: 1.4;">
                            {r.get('descricao') or 'Relatório mensal contendo demonstrações contábeis e fiscais do período.'}
                        </p>
                        <div style="margin-top: 12px;">
                            <a href="{link_relatorio}" target="_blank" class="btn-aj">Acessar Peça / Portal do AJ ↗</a>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )


# ==============================================================================
# PÁGINA 4: QUADRO DE CREDORES & DÍVIDAS
# ==============================================================================
elif pagina_selecionada == "💳 Quadro de Credores & Dívidas":
    st.markdown(
        """
        <div style="margin-bottom: 24px;">
            <h1 style="margin-bottom: 4px;">Decomposição de Passivos e Quadro Geral de Credores (QGC)</h1>
            <p style="color: #94A3B8; font-size: 1.05rem; margin-top: 0;">
                Detalhamento dos créditos concursais segregados pelas 4 Classes da Lei 11.101/2005 e análise de concentração de risco.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    opcoes_casos = {f"{p['nome_razao_social']} ({p.get('tribunal', 'N/A')})": (p.get("processo_id") or p.get("id")) for p in processos_filtrados}
    lista_nomes_casos = list(opcoes_casos.keys())

    if not lista_nomes_casos:
        st.warning("Nenhum processo encontrado para análise de credores.")
    else:
        caso_selecionado = st.selectbox("Selecione o Caso Concursal:", lista_nomes_casos)
        proc_id = opcoes_casos[caso_selecionado]
        dossie = banco.obter_dossie_processo(proc_id)

        if dossie:
            resumo_credores = dossie.get("resumo_credores", {})
            dist_classes = resumo_credores.get("distribuicao_classes", {})

            # Informações Gerais
            st.markdown(
                f"""
                <div style="background-color: #131D31; border: 1px solid #1E293B; border-radius: 10px; padding: 20px; margin-bottom: 20px;">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <h3 style="margin: 0; color: #F8FAFC;">{dossie.get('nome_razao_social')}</h3>
                        <span style="font-size: 1.2rem; font-weight: 800; color: #38BDF8;">Passivo: R$ {dossie.get('valor_causa', 0.0):,.2f}</span>
                    </div>
                    <div style="color: #94A3B8; font-size: 0.9rem; margin-top: 8px;">
                        CNJ: <strong>{dossie.get('numero_cnj')}</strong> • Vara: <strong>{dossie.get('vara_comarca')}</strong> • AJ: <strong>{dossie.get('administrador_judicial')}</strong>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            if dist_classes and any(dist_classes.values()):
                c_graf, c_tab = st.columns([1, 1])
                with c_graf:
                    df_classes = pd.DataFrame([{"Classe": k, "Valor": v} for k, v in dist_classes.items() if v > 0])
                    fig_classes = px.pie(
                        df_classes,
                        values="Valor",
                        names="Classe",
                        hole=0.45,
                        color_discrete_sequence=px.colors.qualitative.Bold,
                        title="Divisão Percentual por Classe Concursal",
                    )
                    fig_classes.update_layout(
                        plot_bgcolor="rgba(0,0,0,0)",
                        paper_bgcolor="rgba(0,0,0,0)",
                        font=dict(color="#E2E8F0"),
                    )
                    st.plotly_chart(fig_classes, use_container_width=True)

                with c_tab:
                    st.markdown("#### Detalhamento das Classes")
                    total_passivo = sum(dist_classes.values()) or 1.0
                    for k, v in dist_classes.items():
                        perc = (v / total_passivo) * 100
                        val_fmt = f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                        st.markdown(f"• **{k}**: {val_fmt} (`{perc:.1f}%`)")
            else:
                st.info("Quadro de credores individualizado em processamento ou agregação pelo Administrador Judicial.")


# ==============================================================================
# PÁGINA 5: SIMULADOR DE CRÉDITO CONCURSAL
# ==============================================================================
elif pagina_selecionada == "💡 Simulador de Crédito Concursal":
    st.markdown(
        """
        <div style="margin-bottom: 24px;">
            <h1 style="margin-bottom: 4px;">Simulador Financeiro de Cessão de Créditos & Distressed Debt</h1>
            <p style="color: #94A3B8; font-size: 1.05rem; margin-top: 0;">
                Modelagem de haircut, taxa interna de retorno (TIR) e valuation para aquisição de créditos em Recuperação Judicial.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    s1, s2 = st.columns([1, 1])
    with s1:
        st.markdown("#### Parâmetros da Transação")
        face_value = st.number_input("Valor de Face do Crédito (R$):", min_value=1000.0, value=5000000.0, step=100000.0)
        desagio = st.slider("Deságio Proposto / Compra (%):", min_value=10.0, max_value=95.0, value=65.0, step=1.0)
        prazo_anos = st.slider("Prazo Estimado de Recebimento (Anos):", min_value=1, max_value=15, value=4, step=1)
        haircut_plano = st.slider("Haircut do Plano de RJ (% sobre o valor de face):", min_value=0.0, max_value=80.0, value=30.0, step=5.0)

    with s2:
        st.markdown("#### Resultados Projetados")
        preco_aquisicao = face_value * (1.0 - (desagio / 100.0))
        valor_recuperavel = face_value * (1.0 - (haircut_plano / 100.0))
        lucro_bruto = valor_recuperavel - preco_aquisicao
        moic = (valor_recuperavel / preco_aquisicao) if preco_aquisicao > 0 else 0.0
        tir_anual = ((valor_recuperavel / preco_aquisicao) ** (1.0 / prazo_anos) - 1.0) * 100.0 if preco_aquisicao > 0 else 0.0

        st.markdown(
            f"""
            <div class="kpi-card" style="margin-bottom: 14px;">
                <div class="kpi-title">Preço de Aquisição</div>
                <div class="kpi-value">R$ {preco_aquisicao:,.2f}</div>
                <div class="kpi-subtitle">Desembolso inicial</div>
            </div>
            <div class="kpi-card" style="margin-bottom: 14px;">
                <div class="kpi-title">Valor Esperado a Receber</div>
                <div class="kpi-value">R$ {valor_recuperavel:,.2f}</div>
                <div class="kpi-subtitle">Após haircut do plano</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-title">Múltiplo (MOIC) / TIR Estimada</div>
                <div class="kpi-value">{moic:.2f}x • {tir_anual:.1f}% a.a.</div>
                <div class="kpi-subtitle">Retorno projetado em {prazo_anos} anos</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
