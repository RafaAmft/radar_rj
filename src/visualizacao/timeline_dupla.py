"""
Componente de Linha do Tempo Dupla (Processo Judicial + Regulatório CVM).

Implementa a visualização sincronizada em 3 camadas:
1. Navegador de Fases Macro (Topo da página com botões de salto temporal e rangeslider)
2. Timeline Detalhada em Duas Raias (Processo Judicial na superior, CVM na inferior,
   com marcadores semânticos e linhas de correlação cruzada em intervalos <= 5 dias)
3. Painel de Detalhe Lateral (Acionado por clique no ponto, com metadados do ato,
   resumo e botão de ação para consulta externa).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.banco.repositorio import BancoDados
from src.dados.links_util import (
    obter_acao_externa_marco,
    resolver_link_documento_marco,
)

# Paleta de Cores do Design System Radar RJ
CORES_EMISSORES: dict[str, dict[str, str]] = {
    "JUIZO": {
        "nome": "Juízo & Decisões",
        "fill": "#3B82F6",       # Azul vibrante
        "border": "#1E3A8A",     # Azul escuro
        "bg_badge": "#1E3A8A",
        "text_badge": "#93C5FD",
        "badge_class": "badge-juizo",
        "icone": "🏛️",
    },
    "CVM": {
        "nome": "Regulatório CVM",
        "fill": "#A855F7",       # Roxo vibrante
        "border": "#4C1D95",     # Roxo escuro
        "bg_badge": "#4C1D95",
        "text_badge": "#E9D5FF",
        "badge_class": "badge-cvm",
        "icone": "🏢",
    },
    "AJ": {
        "nome": "Administrador Judicial",
        "fill": "#10B981",       # Esmeralda vibrante
        "border": "#064E3B",     # Esmeralda escuro
        "bg_badge": "#064E3B",
        "text_badge": "#6EE7B7",
        "badge_class": "badge-aj",
        "icone": "📋",
    },
    "RECUPERANDA": {
        "nome": "Recuperanda",
        "fill": "#F59E0B",       # Âmbar vibrante
        "border": "#78350F",     # Âmbar escuro
        "bg_badge": "#78350F",
        "text_badge": "#FCD34D",
        "badge_class": "badge-recuperanda",
        "icone": "💼",
    },
    "MP": {
        "nome": "Ministério Público",
        "fill": "#EC4899",       # Rosa vibrante
        "border": "#831843",     # Rosa escuro
        "bg_badge": "#831843",
        "text_badge": "#FBCFE8",
        "badge_class": "badge-mp",
        "icone": "⚖️",
    },
    "OUTROS": {
        "nome": "Outras Partes / Credores",
        "fill": "#64748B",       # Cinza ardósia
        "border": "#1E293B",     # Cinza escuro
        "bg_badge": "#1E293B",
        "text_badge": "#94A3B8",
        "badge_class": "badge-credor",
        "icone": "👥",
    },
}

# Definição das Fases Macro do Processo de Recuperação Judicial
ORDEM_FASES: list[str] = [
    "Distribuição",
    "Deferimento",
    "Plano apresentado",
    "Assembleias",
    "Homologação",
    "Pós-homologação",
]


def normalizar_emissor(autor: str | None, tipo_evento: str | None) -> str:
    """Normaliza o emissor para uma das chaves semânticas de CORES_EMISSORES."""
    autor_norm = (autor or "").upper().strip()
    tipo_norm = (tipo_evento or "").upper().strip()

    if autor_norm == "CVM" or "CVM" in tipo_norm:
        return "CVM"
    if autor_norm in ("JUIZO", "JUIZ", "MAGISTRADO", "VARA", "TRIBUNAL"):
        return "JUIZO"
    if autor_norm in ("AJ", "ADMINISTRADOR", "ADMINISTRADOR_JUDICIAL"):
        return "AJ"
    if autor_norm in ("RECUPERANDA", "DEVEDORA", "EMPRESA"):
        return "RECUPERANDA"
    if autor_norm in ("MP", "MINISTERIO_PUBLICO", "PROMOTORIA"):
        return "MP"
    return "OUTROS"


def classificar_fase_macro(
    marco: dict[str, Any],
    data_deferimento: str | None = None,
    data_prj: str | None = None,
    data_agc: str | None = None,
    data_homologacao: str | None = None,
) -> str:
    """
    Classifica um evento individual em uma das fases macro do processo.
    Utiliza uma combinação de tipo_evento, título e marcos cronológicos-chave.
    """
    tipo = str(marco.get("tipo_evento", "")).upper()
    titulo = str(marco.get("titulo", "")).lower()
    data = str(marco.get("data_evento", ""))

    # 1. Checagens diretas por tipo e título
    if "HOMOLOGA" in tipo or "homologa" in titulo:
        return "Homologação"

    if data_homologacao and data > data_homologacao:
        return "Pós-homologação"

    if "AGC" in tipo or "ASSEMBLEIA" in tipo or "assembleia" in titulo:
        return "Assembleias"

    if "PRJ" in tipo or "PLANO" in tipo or "plano de recupera" in titulo:
        return "Plano apresentado"

    if "DEFERI" in tipo or "PROCESSAMENTO" in tipo or ("decis" in tipo and "processamento" in titulo):
        return "Deferimento"

    if "DISTRIB" in tipo or "INICIAL" in tipo or "ajuizamento" in titulo:
        return "Distribuição"

    # 2. Posição temporal relativa aos marcos conhecidos
    if data_homologacao and data >= data_homologacao:
        return "Pós-homologação"

    if data_agc and data >= data_agc:
        return "Assembleias"

    if data_prj and data >= data_prj:
        return "Plano apresentado"

    if data_deferimento and data >= data_deferimento:
        return "Deferimento"

    return "Distribuição"


def extrair_fases_processo(marcos: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """
    Mapeia os limites de data e contagem de eventos de cada fase macro presente no caso.
    Retorna dicionário indexado pelo nome da fase.
    """
    if not marcos:
        return {}

    # Ordenar eventos cronologicamente
    marcos_ordenados = sorted(
        marcos,
        key=lambda m: (str(m.get("data_evento") or ""), int(m.get("id") or 0)),
    )

    # Identificar datas-chave dos marcos âncora
    data_deferimento = None
    data_prj = None
    data_agc = None
    data_homologacao = None

    for m in marcos_ordenados:
        tipo = str(m.get("tipo_evento", "")).upper()
        titulo = str(m.get("titulo", "")).lower()
        d = str(m.get("data_evento", ""))

        if not data_deferimento and ("DEFERI" in tipo or "PROCESSAMENTO" in tipo or "processamento" in titulo):
            data_deferimento = d
        if not data_prj and ("PRJ" in tipo or "plano" in titulo):
            data_prj = d
        if not data_agc and ("AGC" in tipo or "assembleia" in titulo):
            data_agc = d
        if not data_homologacao and ("HOMOLOGA" in tipo or "homologa" in titulo):
            data_homologacao = d

    # Agrupar eventos por fase
    fases_map: dict[str, dict[str, Any]] = {
        fase: {
            "nome": fase,
            "data_inicio": None,
            "data_fim": None,
            "marcos": [],
            "total": 0,
        }
        for fase in ORDEM_FASES
    }

    for m in marcos_ordenados:
        fase_nome = classificar_fase_macro(
            m,
            data_deferimento=data_deferimento,
            data_prj=data_prj,
            data_agc=data_agc,
            data_homologacao=data_homologacao,
        )
        fase_dict = fases_map[fase_nome]
        fase_dict["marcos"].append(m)
        fase_dict["total"] += 1

        d = str(m.get("data_evento", ""))
        if d:
            if not fase_dict["data_inicio"] or d < fase_dict["data_inicio"]:
                fase_dict["data_inicio"] = d
            if not fase_dict["data_fim"] or d > fase_dict["data_fim"]:
                fase_dict["data_fim"] = d

    return fases_map


def detectar_correlacoes(
    marcos_judiciais: list[dict[str, Any]],
    marcos_cvm: list[dict[str, Any]],
    limiar_dias: int = 5,
) -> list[dict[str, Any]]:
    """
    Localiza pares de atos (Processo Judicial vs CVM) cuja diferença de datas seja <= limiar_dias.
    """
    correlacoes = []
    for mj in marcos_judiciais:
        dj_str = str(mj.get("data_evento", ""))
        if not dj_str:
            continue
        try:
            dj = datetime.strptime(dj_str[:10], "%Y-%m-%d").date()
        except ValueError:
            continue

        for mc in marcos_cvm:
            dc_str = str(mc.get("data_evento", ""))
            if not dc_str:
                continue
            try:
                dc = datetime.strptime(dc_str[:10], "%Y-%m-%d").date()
            except ValueError:
                continue

            diff = abs((dj - dc).days)
            if diff <= limiar_dias:
                correlacoes.append({
                    "marco_jud": mj,
                    "marco_cvm": mc,
                    "data_jud": dj_str,
                    "data_cvm": dc_str,
                    "diferenca_dias": diff,
                })

    return correlacoes


def construir_figura_timeline_dupla(
    marcos: list[dict[str, Any]],
    fases_map: dict[str, dict[str, Any]],
    intervalo_data: tuple[str, str] | None = None,
    mostrar_correlacoes: bool = False,
    limiar_dias: int = 5,
) -> go.Figure:
    """
    Constrói a figura Plotly com duas raias (Y=1: Processo Judicial; Y=0: Regulatório CVM),
    rangeslider horizontal e conectores pontilhados de correlação temporal.
    """
    fig = go.Figure()

    # Separar eventos em duas raias
    marcos_judiciais: list[dict[str, Any]] = []
    marcos_cvm: list[dict[str, Any]] = []

    for m in marcos:
        emissor = normalizar_emissor(m.get("autor"), m.get("tipo_evento"))
        if emissor == "CVM":
            marcos_cvm.append(m)
        else:
            marcos_judiciais.append(m)

    # 1. Adicionar linhas de correlação cruzada (se ativado)
    if mostrar_correlacoes and marcos_judiciais and marcos_cvm:
        pares = detectar_correlacoes(marcos_judiciais, marcos_cvm, limiar_dias=limiar_dias)
        for par in pares:
            # Traço pontilhado conectando (data_jud, 1) a (data_cvm, 0)
            dias_txt = "mesmo dia" if par["diferenca_dias"] == 0 else f"{par['diferenca_dias']} dia(s)"
            fig.add_trace(
                go.Scatter(
                    x=[par["data_jud"], par["data_cvm"]],
                    y=[1, 0],
                    mode="lines",
                    line=dict(color="rgba(56, 189, 248, 0.65)", width=2, dash="dot"),
                    hoverinfo="text",
                    text=f"⚡ Correlação Cruzada ({dias_txt}):<br>• Judiciário: {par['marco_jud'].get('titulo')}<br>• CVM: {par['marco_cvm'].get('titulo')}",
                    showlegend=False,
                )
            )

    # 2. Agrupar e plotar marcadores por emissor (raia superior e inferior)
    # Lista de emissores presentes nos marcos
    emissores_presentes: dict[str, list[dict[str, Any]]] = {}
    for m in marcos:
        emissor = normalizar_emissor(m.get("autor"), m.get("tipo_evento"))
        emissores_presentes.setdefault(emissor, []).append(m)

    for emissor_key, grupo in emissores_presentes.items():
        cfg = CORES_EMISSORES.get(emissor_key, CORES_EMISSORES["OUTROS"])
        y_val = 0 if emissor_key == "CVM" else 1

        x_datas = []
        customdata_list = []

        for m in grupo:
            d_str = str(m.get("data_evento") or "")
            x_datas.append(d_str)

            # Formatar data para exibição no tooltip
            try:
                dt_formatada = datetime.strptime(d_str[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
            except Exception:
                dt_formatada = d_str

            fase_nome = classificar_fase_macro(m)

            customdata_list.append([
                int(m.get("id") or 0),
                str(m.get("titulo") or "Ato Processual"),
                dt_formatada,
                cfg["nome"],
                str(m.get("tipo_evento") or "GERAL"),
                fase_nome,
                str(m.get("descricao") or "Sem observações adicionais."),
                str(m.get("url_documento") or ""),
                emissor_key,
            ])

        hovertemplate = (
            "<b>%{customdata[1]}</b><br>"
            "📅 <b>Data:</b> %{customdata[2]}<br>"
            "🏷️ <b>Tipo:</b> %{customdata[4]}<br>"
            "👤 <b>Emissor:</b> %{customdata[3]}<br>"
            "📌 <b>Fase:</b> %{customdata[5]}<br>"
            "<span style='color:#38BDF8; font-size:11px;'>👉 Clique para inspecionar detalhes no painel lateral</span>"
            "<extra></extra>"
        )

        fig.add_trace(
            go.Scatter(
                x=x_datas,
                y=[y_val] * len(x_datas),
                mode="markers",
                name=f"{cfg['icone']} {cfg['nome']}",
                marker=dict(
                    size=16,
                    color=cfg["fill"],
                    line=dict(width=2, color=cfg["border"]),
                    symbol="circle",
                ),
                selected=dict(
                    marker=dict(
                        size=22,
                        color="#38BDF8",
                        opacity=1.0,
                    )
                ),
                unselected=dict(
                    marker=dict(
                        opacity=0.45,
                    )
                ),
                customdata=customdata_list,
                hovertemplate=hovertemplate,
            )
        )

    # 3. Linhas guias horizontais de base para cada raia
    if marcos:
        datas_todas = [str(m.get("data_evento") or "") for m in marcos if m.get("data_evento")]
        if datas_todas:
            d_min = min(datas_todas)
            d_max = max(datas_todas)
            # Linha de fundo da raia judicial
            fig.add_shape(
                type="line",
                x0=d_min,
                x1=d_max,
                y0=1,
                y1=1,
                line=dict(color="rgba(51, 65, 85, 0.5)", width=1),
                layer="below",
            )
            # Linha de fundo da raia CVM
            fig.add_shape(
                type="line",
                x0=d_min,
                x1=d_max,
                y0=0,
                y1=0,
                line=dict(color="rgba(76, 29, 149, 0.4)", width=1),
                layer="below",
            )

    # Configuração de Layout e Tema Dark
    layout_xaxis: dict[str, Any] = dict(
        type="date",
        rangeslider=dict(
            visible=True,
            thickness=0.08,
            bgcolor="#0F172A",
            bordercolor="#1E293B",
        ),
        gridcolor="rgba(51, 65, 85, 0.35)",
        tickfont=dict(color="#94A3B8", size=11),
        zeroline=False,
    )

    if intervalo_data and intervalo_data[0] and intervalo_data[1]:
        layout_xaxis["range"] = [intervalo_data[0], intervalo_data[1]]

    fig.update_layout(
        paper_bgcolor="rgba(19, 29, 49, 0.7)",
        plot_bgcolor="rgba(11, 15, 25, 0.85)",
        font=dict(color="#E2E8F0", family="Inter, sans-serif"),
        margin=dict(l=20, r=20, t=30, b=10),
        height=380,
        hovermode="closest",
        clickmode="event+select",
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.05,
            xanchor="center",
            x=0.5,
            font=dict(size=11, color="#CBD5E1"),
        ),
        yaxis=dict(
            tickvals=[0, 1],
            ticktext=["<b>🏢 Regulatório CVM</b>", "<b>🏛️ Processo Judicial</b>"],
            range=[-0.45, 1.45],
            gridcolor="rgba(51, 65, 85, 0.35)",
            tickfont=dict(size=12, color="#F8FAFC"),
            zeroline=False,
            fixedrange=True,  # Trava o zoom vertical para navegação focar no tempo
        ),
        xaxis=layout_xaxis,
    )

    return fig


def renderizar_timeline_dupla(
    processo_id: int,
    dossie: dict[str, Any] | None = None,
    db: BancoDados | None = None,
    db_path: str = "data/radar.db",
) -> None:
    """
    Ponto de entrada principal do componente para ser chamado dentro da página do ativo.
    Renderiza as 3 camadas completas com gestão de estado reativo.
    """
    banco = db or BancoDados(db_path)

    # 1. Consulta única no banco de dados para os marcos do processo
    marcos_brutos = banco.obter_linha_do_tempo(processo_id)

    if not marcos_brutos:
        st.info("Nenhum marco processual ou regulatório registrado para este ativo ainda.")
        return

    # Buscar dossiê se não fornecido
    if dossie is None:
        dossie = banco.obter_dossie_processo(processo_id) or {}

    # Dicionário de busca rápida de marcos por ID
    mapa_marcos = {int(m["id"]): m for m in marcos_brutos if m.get("id")}

    # Extrair fases e marcos âncora
    fases_map = extrair_fases_processo(marcos_brutos)

    # Chaves de session_state individualizadas por processo
    key_fase = f"fase_ativa_p{processo_id}"
    key_range = f"range_data_p{processo_id}"
    key_sel_id = f"marco_selecionado_p{processo_id}"
    key_corr = f"mostrar_correlacoes_p{processo_id}"

    if key_fase not in st.session_state:
        st.session_state[key_fase] = "Todas as Fases"
    if key_sel_id not in st.session_state:
        st.session_state[key_sel_id] = None

    # ==========================================================================
    # CAMADA 1: NAVEGADOR DE FASES (TOPO DA PÁGINA)
    # ==========================================================================
    st.markdown("##### 🧭 Navegador de Fases Macro")

    # Criar lista de opções de fase com contagem
    opcoes_fases = ["Todas as Fases"]
    for f_nome in ORDEM_FASES:
        total_f = fases_map.get(f_nome, {}).get("total", 0)
        if total_f > 0:
            opcoes_fases.append(f"{f_nome} ({total_f})")

    # Renderizar botões de pílulas para navegação imediata em 1 clique
    col_pills, col_corr = st.columns([4, 2])
    with col_pills:
        # Seletor de Fase
        fase_escolhida_raw = st.pills(
            label="Selecione a Fase Processual para Filtrar:",
            options=opcoes_fases,
            default=st.session_state[key_fase] if st.session_state[key_fase] in opcoes_fases else "Todas as Fases",
            key=f"pills_{processo_id}",
            label_visibility="collapsed",
        )
        if fase_escolhida_raw:
            st.session_state[key_fase] = fase_escolhida_raw

    with col_corr:
        mostrar_corr = st.checkbox(
            "⚡ Mostrar correlações (≤ 5 dias)",
            value=st.session_state.get(key_corr, False),
            key=key_corr,
            help="Traça linhas pontilhadas conectando decisões judiciais e comunicados CVM ocorridos em janela de até 5 dias.",
        )

    # Determinar intervalo de datas da fase selecionada
    fase_atual = st.session_state[key_fase]
    intervalo_data: tuple[str, str] | None = None

    if fase_atual != "Todas as Fases":
        # Extrair nome puro da fase (sem contagem)
        nome_puro = fase_atual.split(" (")[0]
        f_info = fases_map.get(nome_puro)
        if f_info and f_info["data_inicio"] and f_info["data_fim"]:
            try:
                # Adiciona margem de 10 dias antes e depois para folga visual
                dt_ini = datetime.strptime(f_info["data_inicio"][:10], "%Y-%m-%d") - timedelta(days=10)
                dt_fim = datetime.strptime(f_info["data_fim"][:10], "%Y-%m-%d") + timedelta(days=10)
                intervalo_data = (dt_ini.strftime("%Y-%m-%d"), dt_fim.strftime("%Y-%m-%d"))
            except Exception:
                intervalo_data = (f_info["data_inicio"], f_info["data_fim"])

    # ==========================================================================
    # CAMADA 2: TIMELINE DUPLA EM DUAS RAIAS
    # ==========================================================================
    fig = construir_figura_timeline_dupla(
        marcos=marcos_brutos,
        fases_map=fases_map,
        intervalo_data=intervalo_data,
        mostrar_correlacoes=mostrar_corr,
        limiar_dias=5,
    )

    # Layout responsivo: se houver marco selecionado, abre coluna lateral de detalhe
    id_selecionado = st.session_state.get(key_sel_id)

    if id_selecionado and id_selecionado in mapa_marcos:
        col_timeline, col_painel = st.columns([7, 5])
    else:
        col_timeline, col_painel = st.columns([8, 4])

    with col_timeline:
        st.markdown(
            """
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
                <span style="font-size: 0.82rem; color: #94A3B8;">
                    Duas Raias: <b>Superior</b> = Processo Judicial | <b>Inferior</b> = Regulatório CVM
                </span>
                <span style="font-size: 0.8rem; color: #38BDF8;">
                    🖱️ <i>Use o rangeslider inferior para zoom temporal livre</i>
                </span>
            </div>
            """,
            unsafe_allow_html=True,
        )

        chart_event = st.plotly_chart(
            fig,
            use_container_width=True,
            on_select="rerun",
            selection_mode="points",
            key=f"plotly_chart_{processo_id}",
        )

        # Capturar evento de clique nos marcadores
        if chart_event and "selection" in chart_event:
            pts = chart_event["selection"].get("points", [])
            if pts:
                pt = pts[0]
                cd = pt.get("customdata")
                if cd and len(cd) > 0:
                    clicado_id = int(cd[0])
                    if st.session_state.get(key_sel_id) != clicado_id:
                        st.session_state[key_sel_id] = clicado_id
                        st.rerun()

    # ==========================================================================
    # CAMADA 3: PAINEL DE DETALHE LATERAL
    # ==========================================================================
    with col_painel:
        id_atual = st.session_state.get(key_sel_id)

        if id_atual and id_atual in mapa_marcos:
            m_sel = mapa_marcos[id_atual]
            autor_sel = normalizar_emissor(m_sel.get("autor"), m_sel.get("tipo_evento"))
            cfg_sel = CORES_EMISSORES.get(autor_sel, CORES_EMISSORES["OUTROS"])
            fase_sel = classificar_fase_macro(m_sel)

            # Informações de ação externa e link validado
            acao_info = obter_acao_externa_marco(m_sel, dossie=dossie)

            # Data formatada
            d_raw = str(m_sel.get("data_evento") or "")
            try:
                data_bonita = datetime.strptime(d_raw[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
            except Exception:
                data_bonita = d_raw

            st.markdown(
                f"""
                <div class="timeline-card" style="border-left: 4px solid {cfg_sel['fill']};">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                        <span class="{cfg_sel['badge_class']}">{cfg_sel['icone']} {cfg_sel['nome']}</span>
                        <span style="color: #94A3B8; font-size: 0.85rem; font-weight: 600;">📅 {data_bonita}</span>
                    </div>
                    <div style="font-size: 0.78rem; color: #38BDF8; text-transform: uppercase; font-weight: 700; margin-bottom: 4px;">
                        Fase: {fase_sel} • Tipo: {m_sel.get('tipo_evento', 'ATO')}
                    </div>
                    <h4 style="margin: 0 0 12px 0; font-size: 1.15rem; color: #F8FAFC;">
                        {m_sel.get('titulo', 'Ato Processual')}
                    </h4>
                    <p style="color: #CBD5E1; font-size: 0.9rem; line-height: 1.5; margin-bottom: 18px; background: rgba(15, 23, 42, 0.6); padding: 12px; border-radius: 8px; border: 1px solid #1E293B;">
                        {m_sel.get('descricao') or 'Nenhuma descrição complementar registrada para esta movimentação.'}
                    </p>
                    <div style="margin-top: 10px;">
                        <a href="{acao_info['url']}" target="_blank" class="{acao_info['btn_class']}" style="display: block; text-align: center; width: 100%;">
                            {acao_info['icone']} {acao_info['label']}
                        </a>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            st.markdown("<div style='margin-top: 10px;'></div>", unsafe_allow_html=True)
            if st.button("✕ Fechar Detalhes", key=f"btn_close_detalhe_{processo_id}", use_container_width=True):
                st.session_state[key_sel_id] = None
                st.rerun()

        else:
            # Card instrutivo quando nenhum ponto foi selecionado
            st.markdown(
                """
                <div class="kpi-card" style="border-style: dashed; border-color: #334155; text-align: center; padding: 28px 18px;">
                    <div style="font-size: 2.2rem; margin-bottom: 8px;">🎯</div>
                    <div style="color: #F8FAFC; font-weight: 700; font-size: 1rem; margin-bottom: 6px;">
                        Inspeção de Marco
                    </div>
                    <p style="color: #94A3B8; font-size: 0.85rem; line-height: 1.4; margin-bottom: 14px;">
                        Clique em qualquer marcador na <b>Linha do Tempo</b> ao lado para visualizar a fundamentação detalhada do ato e acessar o link direto do documento oficial.
                    </p>
                </div>
                """,
                unsafe_allow_html=True,
            )

            # Seletor direto alternativo para navegação rápida
            opcoes_dropdown = ["(Selecione um marco para detalhar)"] + [
                f"{m.get('data_evento')} | {m.get('titulo')} [{m.get('autor')}]" for m in marcos_brutos
            ]
            escolha = st.selectbox(
                "Ou inspecione diretamente pela lista:",
                opcoes_dropdown,
                key=f"select_marco_lista_{processo_id}",
            )
            if escolha and escolha != "(Selecione um marco para detalhar)":
                idx = opcoes_dropdown.index(escolha) - 1
                st.session_state[key_sel_id] = int(marcos_brutos[idx]["id"])
                st.rerun()
