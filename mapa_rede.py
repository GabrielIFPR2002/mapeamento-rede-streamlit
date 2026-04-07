import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import igraph as ig
import random


SENHA_ACESSO = st.secrets["SENHA_ACESSO"]  # Senha para a aba privada


# =========================================
# Funções auxiliares
# =========================================
def obter_iniciais(nome_completo):
    ignorar = ['de', 'da', 'do', 'das', 'dos', 'e']
    palavras = str(nome_completo).split()
    iniciais = [p[0].upper() for p in palavras if p.lower() not in ignorar]
    return "".join(iniciais)


def gerar_mapa_gerencia_pessoa(df):
    
    mapa = {}

    pessoas = pd.unique(df[['Entrevistado', 'Alvo']].values.ravel('K'))

    for pessoa in pessoas:
        if pd.isna(pessoa):
            continue

        linhas = df[
            (df['Entrevistado'] == pessoa) | (df['Alvo'] == pessoa)
        ]['Gerencia'].dropna()

        if linhas.empty:
            mapa[pessoa] = 'Sem Gerência'
        else:
            mapa[pessoa] = linhas.value_counts().idxmax()

    return mapa


def gerar_mapa_anonimo_por_gerencia(df):
  
    random.seed(42)
    mapa = {}

    # Consolida gerência por pessoa para garantir consistência com as cores
    mapa_gerencia = gerar_mapa_gerencia_pessoa(df)

    # Pessoas presentes no grafo (entrevistados + alvos)
    pessoas = pd.unique(df[['Entrevistado', 'Alvo']].values.ravel('K'))
    pessoas = [p for p in pessoas if pd.notna(p)]

    # Agrupa pessoas por gerência consolidada
    agrupado = {}
    for p in pessoas:
        ger = mapa_gerencia.get(p, 'Sem Gerência')
        agrupado.setdefault(ger, []).append(p)

    # Embaralha e atribui IDs por gerência
    for gerencia, lista in agrupado.items():
        lista_local = list(set(lista))
        random.shuffle(lista_local)
        for i, nome in enumerate(lista_local, start=1):
            mapa[nome] = {"id": i, "gerencia": gerencia}

    return mapa



def criar_grafico_rede(df, mapa_anonimo, modo_privacidade=False):
    """
    Gera o grafo com hover sem 'extra' e sem 'trace 1'.
    """
    try:
        # Criação das arestas a partir do CSV
        edges = [
            (row['Entrevistado'], row['Alvo'])
            for _, row in df.iterrows()
            if pd.notna(row['Entrevistado']) and pd.notna(row['Alvo'])
        ]

        # Se não houver arestas válidas, aborta
        if not edges:
            st.warning("Nenhuma aresta válida encontrada no CSV (verifique colunas 'Entrevistado' e 'Alvo').")
            return None

        # Criação do grafo não direcionado
        g = ig.Graph.TupleList(edges, directed=False)

        # Mapa definitivo de gerência por pessoa (base única para cor/hover/legenda)
        mapa_gerencia_pessoa = gerar_mapa_gerencia_pessoa(df)

        # Identificação das gerências e definição da paleta de cores (estável)
        gerencias = sorted(set(mapa_gerencia_pessoa.values()))
        cores_paleta = [
            '#e74c3c',  # red
            '#3498db',  # blue
            '#2ecc71',  # green
            '#e67e22',  # orange
            '#9b59b6',  # purple
            '#8d6e63',  # brown
            '#e91e63',  # pink
            '#7f8c8d',  # gray
            '#3d9970',  # olive-ish
            '#16a085',  # teal
        ]
        mapa_cores = {ger: cores_paleta[i % len(cores_paleta)] for i, ger in enumerate(gerencias)}

        # Listas auxiliares
        hover_info = []
        tamanhos = []
        cores_nos = []
        texto_exibicao = []

        # Para cada nó do grafo
        for nome in g.vs['name']:
            conexoes_como_entrevistado = len(df[df['Entrevistado'] == nome])
            conexoes_como_alvo = len(df[df['Alvo'] == nome])
            total_conexoes = conexoes_como_entrevistado + conexoes_como_alvo

            # Tamanho do nó proporcional a quantas vezes foi 'Alvo'
            tamanhos.append(15 + (conexoes_como_alvo * 5))

            # Gerência consolidada
            gerencia_pessoa = mapa_gerencia_pessoa.get(nome, 'Sem Gerência')
            cores_nos.append(mapa_cores.get(gerencia_pessoa, 'black'))

            # Texto/hovers
            if modo_privacidade:
                dados_anon = mapa_anonimo[nome]
                id_num = dados_anon["id"]
                ger = dados_anon["gerencia"]

                texto_exibicao.append(str(id_num))
                hover_info.append(
                    f"&lt;b&gt;Usuário Anônimo&lt;/b&gt;&lt;br&gt;"
                    f"Identificador: {ger}-{id_num}&lt;br&gt;"
                    f"Área: {ger}&lt;br&gt;"
                    f"Total de Conexões: {total_conexoes}&lt;br&gt;"
                    f"Como Entrevistado: {conexoes_como_entrevistado}&lt;br&gt;"
                    f"Como Alvo: {conexoes_como_alvo}"
                )
            else:
                texto_exibicao.append(obter_iniciais(nome))
                hover_info.append(
                    f"&lt;b&gt;{nome}&lt;/b&gt;&lt;br&gt;"
                    f"Gerência: {gerencia_pessoa}&lt;br&gt;"
                    f"Total de Conexões: {total_conexoes}&lt;br&gt;"
                    f"Como Entrevistado: {conexoes_como_entrevistado}&lt;br&gt;"
                    f"Como Alvo: {conexoes_como_alvo}"
                )

        if "layout_posicoes" not in st.session_state:
            random.seed(42)
            layout = g.layout("fr")
            st.session_state["layout_posicoes"] = [(pos[0], pos[1]) for pos in layout]

        layout = st.session_state["layout_posicoes"]

        node_x = [pos[0] for pos in layout]
        node_y = [pos[1] for pos in layout]

        edge_x, edge_y = [], []
        for edge in g.es:
            x1, y1 = layout[edge.source]
            x2, y2 = layout[edge.target]
            edge_x.extend([x1, x2, None])
            edge_y.extend([y1, y2, None])

        fig = go.Figure()

        fig.add_trace(
            go.Scatter(
                x=edge_x,
                y=edge_y,
                mode='lines',
                line=dict(color='rgba(100,100,100,0.5)', width=1),
                hoverinfo='skip',
                showlegend=False,
                name=''
            )
        )

        fig.add_trace(
            go.Scatter(
                x=node_x,
                y=node_y,
                mode='markers+text',
                text=texto_exibicao,
                hovertext=hover_info,                     
                textposition='middle center',
                textfont=dict(color='black', size=[max(10, int(s * 0.45)) for s in tamanhos]),
                marker=dict(
                    size=tamanhos,
                    color=cores_nos,
                    line=dict(width=1, color='white')
                ),
                hovertemplate='%{hovertext}&lt;extra&gt;&lt;/extra&gt;',
                showlegend=False,
                name=''
            )
        )

        for ger in gerencias:
            fig.add_trace(
                go.Scatter(
                    x=[None], y=[None],
                    mode='markers',
                    marker=dict(size=10, color=mapa_cores.get(ger, 'black')),
                    name=ger,
                    showlegend=True
                )
            )

        fig.update_layout(
            plot_bgcolor='white',
            height=700,
            showlegend=True,
            hovermode='closest',
            margin=dict(l=10, r=10, t=10, b=10)
        )

        return fig

    except Exception as e:
        st.error(f"Erro ao gerar gráfico: {e}")
        return None


# =========================================
# Interface Streamlit
# =========================================
def main():
    st.set_page_config(page_title="Mapeamento de Rede", layout="wide")
    st.title("🕸️ Mapeamento de Relacionamentos")

    with st.sidebar:
        st.header("📋 Instruções")
        st.markdown("""
        **Formato do arquivo CSV:**

        O arquivo deve conter as seguintes colunas:

        - `Entrevistado`  
        - `Alvo`  
        - `Gerencia`
        """)

    uploaded_file = st.file_uploader("📁 Carregue o arquivo CSV", type=['csv'])

    if uploaded_file:
        try:
            df = pd.read_csv(uploaded_file, encoding='utf-8-sig')
        except Exception:
            df = pd.read_csv(uploaded_file, encoding='latin1')

        mapa_anonimo = gerar_mapa_anonimo_por_gerencia(df)

        tab_publica, tab_privada = st.tabs(
            ["🔒 Aba Pública (Anônima)", "🔑 Aba Privada (Nomes Reais)"]
        )

        with tab_publica:
            fig_anon = criar_grafico_rede(df, mapa_anonimo, True)
            if fig_anon:
                st.plotly_chart(fig_anon, use_container_width=True)

        with tab_privada:
            senha = st.text_input("Insira a senha:", type="password")

            if senha == SENHA_ACESSO:
                fig_real = criar_grafico_rede(df, mapa_anonimo, False)
                if fig_real:
                    st.plotly_chart(fig_real, use_container_width=True)
                st.dataframe(df)
            elif senha:
                st.error("Senha incorreta.")


if __name__ == "__main__":
    main()
