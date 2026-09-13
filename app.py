"""
Radar RJ - Plataforma de Inteligência em Recuperações Judiciais & Distressed Assets.

Dashboard analítico construído em Streamlit apresentando o ranking das maiores
Recuperações Judiciais do Brasil, linha do tempo de peças principais,
manifestações dos Administradores Judiciais e decomposição de passivos.
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
        padding-left: 28px;
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
        padding: 16px 20px;
    }
    
    /* Badges */
    .badge-juizo { background-color: #1E3A8A; color: #93C5FD; padding: 3px 10px; border-radius: 12px; font-size: 0.75rem; font-weight: 600; }
    .badge-aj { background-color: #064E3B; color: #6EE7B7; padding: 3px 10px; border-radius: 12px; font-size: 0.75rem; font-weight: 600; }
    .badge-recuperanda { background-color: #78350F; color: #FCD34D; padding: 3px 10px; border-radius: 12px; font-size: 0.75rem; font-weight: 600; }
    .badge-credor { background-color: #581C87; color: #D8B4FE; padding: 3px 10px; border-radius: 12px; font-size: 0.75rem; font-weight: 600; }
    
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
# SIDEBAR: Filtros Globais e Identidade
# ------------------------------------------------------------------------------
with st.sidebar:
    st.markdown(
        """
        <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 20px;">
            <div style="background: linear-gradient(135deg, #2563EB, #38BDF8); width: 42px; height: 42px; border-radius: 10px; display: flex; align-items: center; justify-content: center; font-size: 22px;">⚖️</div>
            <div>
                <h3 style="margin: 0; font-size: 1.25rem;">RADAR RJ</h3>
                <span style="font-size: 0.75rem; color: #94A3B8; letter-spacing: 0.05em; text-transform: uppercase;">Special Situations & Credit</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("### 🔎 Pesquisa e Filtros")
    termo_busca = st.text_input("Buscar Empresa, CNJ ou AJ", placeholder="Ex: Patense, Oi, 1057756...")

    # Obter dados brutos de processos para alimentar filtros
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
    st.markdown(f"• **{stats_gerais.get('total_credores', 0)}** Credores Habilitados")
    st.markdown("---")
    st.caption("Radar RJ © 2026 • Inteligência de Dados Públicos Concursais")


# ------------------------------------------------------------------------------
# FILTRAGEM DOS DADOS
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


# ------------------------------------------------------------------------------
# HEADER PRINCIPAL
# ------------------------------------------------------------------------------
st.markdown(
    """
    <div style="margin-bottom: 24px;">
        <h1 style="margin-bottom: 4px;">Monitor Nacional de Grandes Recuperações Judiciais</h1>
        <p style="color: #94A3B8; font-size: 1.05rem; margin-top: 0;">
            Auditoria automatizada, decomposição de passivos concursais e acompanhamento de peças de Administradores Judiciais.
        </p>
    </div>
    """,
    unsafe_allow_html=True,
)

# KPIs no Topo
passivo_total = df_filtrado["valor_causa"].sum() if not df_filtrado.empty else 0.0
total_casos = len(df_filtrado)
tribunais_ativos = df_filtrado["tribunal"].nunique() if not df_filtrado.empty else 0
ajs_ativos = df_filtrado["administrador_judicial"].nunique() if not df_filtrado.empty else 0

col1, col2, col3, col4 = st.columns(4)
with col1:
    st.markdown(
        f"""
        <div class="kpi-card">
            <div class="kpi-title">Passivo Total em Monitoramento</div>
            <div class="kpi-value">R$ {passivo_total / 1e9:.2f} B</div>
            <div class="kpi-subtitle">Em créditos concursais auditados</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
with col2:
    st.markdown(
        f"""
        <div class="kpi-card">
            <div class="kpi-title">Casos no Filtro</div>
            <div class="kpi-value">{total_casos} RJs</div>
            <div class="kpi-subtitle">Com grupos econômicos consolidados</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
with col3:
    st.markdown(
        f"""
        <div class="kpi-card">
            <div class="kpi-title">Tribunais Estaduais</div>
            <div class="kpi-value">{tribunais_ativos} TJs</div>
            <div class="kpi-subtitle">TJSP, TJRJ, TJMG, TJPR, TJMT...</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
with col4:
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


# ------------------------------------------------------------------------------
# TABS DE NAVEGAÇÃO
# ------------------------------------------------------------------------------
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📊 Visão de Mercado & Ranking",
    "🏢 Dossiê Individual do Caso",
    "⏳ Linha do Tempo de Peças",
    "📑 Relatórios do AJ (RMAs)",
    "💡 Simulador de Crédito",
])


# ==============================================================================
# TAB 1: VISÃO DE MERCADO & RANKING
# ==============================================================================
with tab1:
    if df_filtrado.empty:
        st.warning("Nenhum processo encontrado com os filtros selecionados.")
    else:
        # Gráficos Analíticos Superiores
        g_col1, g_col2 = st.columns([3, 2])
        
        with g_col1:
            st.markdown("#### 🏆 Top 10 Maiores Recuperações por Volume da Dívida")
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
            st.markdown("#### 🥧 Distribuição do Passivo por Setor")
            setor_agg = df_filtrado.groupby("setor")["valor_causa"].sum().reset_index()
            setor_agg["valor_bi"] = setor_agg["valor_causa"] / 1e9
            
            fig_pie = px.pie(
                setor_agg,
                names="setor",
                values="valor_bi",
                hole=0.45,
                color_discrete_sequence=px.colors.qualitative.Dark24,
            )
            fig_pie.update_layout(
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#E2E8F0"),
                margin=dict(l=10, r=10, t=10, b=10),
                height=420,
                legend=dict(orientation="h", yanchor="bottom", y=-0.3, xanchor="center", x=0.5),
            )
            st.plotly_chart(fig_pie, use_container_width=True)

        st.markdown("---")
        
        # Tabela Geral de Ranking
        st.markdown("#### 📋 Catálogo Geral e Filtros Avançados")
        
        df_exibicao = df_filtrado[[
            "nome_razao_social",
            "setor",
            "tribunal",
            "valor_causa",
            "status_processual",
            "administrador_judicial",
            "numero_cnj",
            "total_marcos",
        ]].copy()
        
        df_exibicao["Passivo (R$)"] = df_exibicao["valor_causa"].apply(
            lambda v: f"R$ {v / 1e9:.2f} Bilhões" if v >= 1e9 else f"R$ {v / 1e6:.1f} Milhões"
        )
        df_exibicao = df_exibicao.rename(columns={
            "nome_razao_social": "Recuperanda / Grupo",
            "setor": "Setor",
            "tribunal": "Tribunal",
            "status_processual": "Status Processual",
            "administrador_judicial": "Administrador Judicial",
            "numero_cnj": "Número Único CNJ",
            "total_marcos": "Marcos Auditados",
        })
        
        colunas_finais = ["Recuperanda / Grupo", "Setor", "Tribunal", "Passivo (R$)", "Status Processual", "Administrador Judicial", "Número Único CNJ", "Marcos Auditados"]
        st.dataframe(
            df_exibicao[colunas_finais],
            use_container_width=True,
            hide_index=True,
        )
        
        csv_data = df_exibicao[colunas_finais].to_csv(index=False).encode("utf-8")
        st.download_button(
            label="📥 Exportar Ranking para Planilha (CSV)",
            data=csv_data,
            file_name="ranking_maiores_rjs_brasil.csv",
            mime="text/csv",
        )


# ==============================================================================
# TAB 2: DOSSIÊ INDIVIDUAL DO CASO
# ==============================================================================
with tab2:
    st.markdown("### 🏢 Raio-X Detalhado da Recuperanda")
    
    # Seletor de caso
    opcoes_casos = {f"{p['nome_razao_social']} ({p['tribunal']})": p["processo_id"] for p in processos_filtrados}
    
    # Priorizar o Grupo Patense se presente, ou o primeiro
    index_padrao = 0
    for idx, (nome, _) in enumerate(opcoes_casos.items()):
        if "Patense" in nome:
            index_padrao = idx
            break
            
    caso_selecionado = st.selectbox(
        "Selecione o Processo para Analisar:",
        options=list(opcoes_casos.keys()),
        index=index_padrao if opcoes_casos else 0,
    )
    
    if caso_selecionado:
        proc_id = opcoes_casos[caso_selecionado]
        dossie = banco.obter_dossie_processo(proc_id)
        
        if dossie:
            # Painel Superior de Identificação
            st.markdown(
                f"""
                <div style="background-color: #131D31; border: 1px solid #1E293B; border-radius: 12px; padding: 24px; margin-bottom: 24px;">
                    <div style="display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 15px;">
                        <div>
                            <span style="background-color: #1E293B; color: #38BDF8; padding: 4px 10px; border-radius: 6px; font-size: 0.8rem; font-weight: 600;">{dossie.get('setor', 'Setor')}</span>
                            <span style="background-color: #064E3B; color: #6EE7B7; padding: 4px 10px; border-radius: 6px; font-size: 0.8rem; font-weight: 600; margin-left: 8px;">{dossie.get('status_processual', 'Em Andamento')}</span>
                            <h2 style="margin: 10px 0 6px 0; font-size: 1.8rem;">{dossie.get('nome_razao_social')}</h2>
                            <p style="color: #94A3B8; margin: 0; font-size: 0.95rem;">
                                CNPJ Raiz: <b>{dossie.get('cnpj') or 'Não Informado'}</b> • Foro: <b>{dossie.get('vara_comarca')}</b>
                            </p>
                        </div>
                        <div style="text-align: right;">
                            <div style="font-size: 0.85rem; color: #94A3B8; text-transform: uppercase;">Passivo Concursal Declarado</div>
                            <div style="font-size: 2.1rem; font-weight: 800; color: #38BDF8;">
                                R$ {dossie.get('valor_causa', 0) / 1e9:.2f} B
                            </div>
                            <div style="font-size: 0.85rem; color: #64748B;">Distribuição: {dossie.get('data_distribuicao') or 'Recente'}</div>
                        </div>
                    </div>
                    <hr style="border: 0; border-top: 1px solid #1E293B; margin: 18px 0;">
                    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 15px;">
                        <div>
                            <span style="color: #64748B; font-size: 0.8rem;">PROCESSO JUDICIAL (CNJ)</span>
                            <div style="font-size: 0.95rem; font-weight: 600; color: #F8FAFC;">{dossie.get('numero_cnj')}</div>
                        </div>
                        <div>
                            <span style="color: #64748B; font-size: 0.8rem;">ADMINISTRADOR JUDICIAL</span>
                            <div style="font-size: 0.95rem; font-weight: 600; color: #F8FAFC;">{dossie.get('administrador_judicial')}</div>
                        </div>
                        <div>
                            <span style="color: #64748B; font-size: 0.8rem;">TRIBUNAL</span>
                            <div style="font-size: 0.95rem; font-weight: 600; color: #F8FAFC;">{dossie.get('tribunal')}</div>
                        </div>
                        <div>
                            <span style="color: #64748B; font-size: 0.8rem;">PORTAL OFICIAL DOS AUTOS</span>
                            <div><a href="{dossie.get('url_detalhe')}" target="_blank" style="color: #38BDF8; font-size: 0.9rem; text-decoration: none;">Acessar Portal do Caso ↗</a></div>
                        </div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            
            # Análise da Composição do Passivo (Classes do QGC)
            resumo_credores = dossie.get("resumo_credores", {})
            totais_classe = resumo_credores.get("totais_por_classe", {})
            
            st.markdown("#### ⚖️ Estrutura e Classes do Passivo (Quadro Geral de Credores)")
            if totais_classe:
                c_col1, c_col2 = st.columns([3, 2])
                with c_col1:
                    df_classes = pd.DataFrame([
                        {"Classe": k, "Valor (R$)": v, "Percentual (%)": (v / sum(totais_classe.values())) * 100}
                        for k, v in totais_classe.items()
                    ])
                    
                    fig_classes = px.bar(
                        df_classes,
                        x="Classe",
                        y="Valor (R$)",
                        color="Classe",
                        text="Valor (R$)",
                        color_discrete_sequence=["#3B82F6", "#10B981", "#F59E0B", "#8B5CF6"],
                    )
                    fig_classes.update_layout(
                        plot_bgcolor="rgba(0,0,0,0)",
                        paper_bgcolor="rgba(0,0,0,0)",
                        font=dict(color="#E2E8F0"),
                        showlegend=False,
                        margin=dict(l=10, r=10, t=10, b=10),
                    )
                    fig_classes.update_traces(texttemplate='R$ %{text:,.2f}', textposition='outside')
                    st.plotly_chart(fig_classes, use_container_width=True)
                    
                with c_col2:
                    st.markdown(
                        f"""
                        <div style="background-color: #131D31; border: 1px solid #1E293B; border-radius: 8px; padding: 18px;">
                            <h4 style="margin-top: 0;">Detalhamento por Classe</h4>
                            <table style="width: 100%; font-size: 0.9rem; border-collapse: collapse;">
                                <thead>
                                    <tr style="border-bottom: 1px solid #334155; color: #94A3B8; text-align: left;">
                                        <th style="padding: 6px;">Classe</th>
                                        <th style="padding: 6px; text-align: right;">Total Declarado</th>
                                    </tr>
                                </thead>
                                <tbody>
                        """,
                        unsafe_allow_html=True,
                    )
                    for k, v in totais_classe.items():
                        st.markdown(
                            f"""
                            <tr style="border-bottom: 1px solid #1E293B;">
                                <td style="padding: 8px 6px;"><b>{k}</b></td>
                                <td style="padding: 8px 6px; text-align: right; color: #38BDF8;">R$ {v:,.2f}</td>
                            </tr>
                            """,
                            unsafe_allow_html=True,
                        )
                    st.markdown("</tbody></table></div>", unsafe_allow_html=True)
            else:
                st.info("Decomposição detalhada de classes do QGC em fase de habilitação pelo Administrador Judicial.")


# ==============================================================================
# TAB 3: LINHA DO TEMPO DE PEÇAS PRINCIPAIS
# ==============================================================================
with tab3:
    st.markdown("### ⏳ Cronologia Processual e Peças Relevantes")
    st.caption("Evolução dos atos do processo, desde a Petição Inicial até Deliberações da AGC e Sentenças.")
    
    if caso_selecionado:
        proc_id = opcoes_casos[caso_selecionado]
        timeline = banco.obter_linha_do_tempo(proc_id)
        
        if not timeline:
            st.info("Nenhum evento registrado na linha do tempo deste caso.")
        else:
            st.markdown(f"Exibindo **{len(timeline)} marcos cronológicos** de `{caso_selecionado}`:")
            
            for m in timeline:
                autor = m.get("autor", "AJ")
                badge_class = "badge-aj"
                if autor == "JUIZO":
                    badge_class = "badge-juizo"
                elif autor == "RECUPERANDA":
                    badge_class = "badge-recuperanda"
                elif autor == "CREDOR":
                    badge_class = "badge-credor"
                    
                url_doc = m.get("url_documento", "")
                link_btn = f"<a href='{url_doc}' target='_blank' style='display: inline-block; margin-top: 10px; background-color: #2563EB; color: white; padding: 5px 14px; border-radius: 6px; text-decoration: none; font-size: 0.8rem; font-weight: 600;'>📄 Visualizar Peça Oficial ↗</a>" if url_doc else ""
                
                st.markdown(
                    f"""
                    <div class="timeline-item">
                        <div class="timeline-dot"></div>
                        <div class="timeline-card">
                            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                                <span style="color: #94A3B8; font-size: 0.85rem; font-weight: 600;">📅 {m.get('data_evento')}</span>
                                <span class="{badge_class}">{autor}</span>
                            </div>
                            <h4 style="margin: 4px 0 8px 0; color: #F8FAFC;">{m.get('titulo')}</h4>
                            <p style="color: #CBD5E1; font-size: 0.9rem; margin-bottom: 0;">
                                {m.get('descricao') or 'Ato registrado nos autos principais do processo.'}
                            </p>
                            {link_btn}
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )


# ==============================================================================
# TAB 4: RELATÓRIOS DO ADMINISTRADOR JUDICIAL (RMAs)
# ==============================================================================
with tab4:
    st.markdown("### 📑 Acompanhamento e Manifestações do AJ")
    st.markdown(
        """
        O **Relatório Mensal de Atividades (RMA)** e as manifestações periódicas do Administrador Judicial são
        os instrumentos primordiais de auditoria financeira, operacional e contábil das recuperandas,
        apresentando faturamento real, queima de caixa, cumprimento das deliberações da AGC e adimplemento das parcelas do plano.
        """
    )
    
    # Listar processos com marcos do tipo RMA
    rmas_encontrados = []
    for p in processos_filtrados:
        tl = banco.obter_linha_do_tempo(p["processo_id"])
        for m in tl:
            if m.get("tipo_evento") in ["RMA_AJ", "MANIFESTACAO_AJ"]:
                rmas_encontrados.append({
                    "Recuperanda": p["nome_razao_social"],
                    "Tribunal": p["tribunal"],
                    "AJ": p["administrador_judicial"],
                    "Data": m["data_evento"],
                    "Título": m["titulo"],
                    "Síntese": m["descricao"],
                    "Link": m["url_documento"],
                })
                
    if rmas_encontrados:
        df_rma = pd.DataFrame(rmas_encontrados)
        st.markdown(f"#### 🔎 {len(rmas_encontrados)} Manifestações & Relatórios Recentes Identificados")
        for r in rmas_encontrados:
            st.markdown(
                f"""
                <div style="background-color: #131D31; border: 1px solid #1E293B; border-radius: 10px; padding: 18px; margin-bottom: 14px;">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <span style="color: #38BDF8; font-weight: 700; font-size: 1rem;">{r['Recuperanda']} ({r['Tribunal']})</span>
                        <span style="color: #94A3B8; font-size: 0.85rem;">📅 {r['Data']}</span>
                    </div>
                    <div style="color: #6EE7B7; font-size: 0.85rem; font-weight: 600; margin-top: 4px;">{r['AJ']}</div>
                    <h4 style="margin: 8px 0 6px 0;">{r['Título']}</h4>
                    <p style="color: #CBD5E1; font-size: 0.9rem; margin-bottom: 8px;">{r['Síntese']}</p>
                    <a href="{r['Link']}" target="_blank" style="color: #38BDF8; font-size: 0.85rem; text-decoration: none;">Acessar Relatório Completo ↗</a>
                </div>
                """,
                unsafe_allow_html=True,
            )
    else:
        st.info("Nenhuma manifestação periódica encontrada para os filtros aplicados.")


# ==============================================================================
# TAB 5: SIMULADOR DE CRÉDITO & DESÁGIO
# ==============================================================================
with tab5:
    st.markdown("### 💡 Simulador de Precificação de Créditos Estressados (Special Situations)")
    st.caption("Calcule o valor estimado de recuperação líquida com base nas regras do Plano de Recuperação Judicial (PRJ).")
    
    sim_col1, sim_col2 = st.columns(2)
    
    with sim_col1:
        st.markdown("#### Parâmetros da Simulação")
        valor_face = st.number_input("Valor de Face do Crédito (R$):", min_value=1000.0, value=1000000.0, step=50000.0, format="%.2f")
        desagio_pct = st.slider("Deságio Homologado no PRJ (%):", min_value=0, max_value=95, value=85, help="Exemplo: No caso Grupo Patense, Classe III tem deságio de 85%")
        carencia_anos = st.slider("Prazo de Carência de Principal (Anos):", min_value=1, max_value=10, value=5)
        taxa_desconto = st.slider("Taxa de Desconto Anual / Custo de Oportunidade (% a.a.):", min_value=5.0, max_value=30.0, value=15.0, step=0.5)
        
    with sim_col2:
        st.markdown("#### Estimativa de Liquidação")
        valor_liquido = valor_face * (1 - (desagio_pct / 100.0))
        # VPL simplificado considerando pagamento em parcela única após carência
        vpl = valor_liquido / ((1 + (taxa_desconto / 100.0)) ** carencia_anos)
        preco_justo_compra = vpl * 0.70  # Margem de segurança de 30% para o fundo
        
        st.markdown(
            f"""
            <div style="background: linear-gradient(135deg, #131D31 0%, #0F172A 100%); border: 1px solid #1E293B; border-radius: 12px; padding: 24px;">
                <div style="color: #94A3B8; font-size: 0.85rem; text-transform: uppercase;">Valor Nominal a Ser Pago pós-Deságio</div>
                <div style="font-size: 1.8rem; font-weight: 800; color: #38BDF8; margin-bottom: 12px;">
                    R$ {valor_liquido:,.2f}
                </div>
                
                <div style="color: #94A3B8; font-size: 0.85rem; text-transform: uppercase;">Valor Presente Líquido (VPL Projetado)</div>
                <div style="font-size: 1.6rem; font-weight: 700; color: #10B981; margin-bottom: 12px;">
                    R$ {vpl:,.2f}
                </div>
                
                <div style="color: #94A3B8; font-size: 0.85rem; text-transform: uppercase;">Preço-Alvo Sugerido de Cessão (Haircut Fundo)</div>
                <div style="font-size: 1.4rem; font-weight: 700; color: #F59E0B;">
                    R$ {preco_justo_compra:,.2f} ({preco_justo_compra / valor_face * 100:.1f}% do valor de face)
                </div>
                
                <hr style="border: 0; border-top: 1px solid #1E293B; margin: 16px 0;">
                <p style="font-size: 0.8rem; color: #64748B; margin: 0;">
                    *Modelo indicativo para análise preliminar de compra e cessão de créditos concursais (Art. 83 da Lei 11.101/2005).
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )
