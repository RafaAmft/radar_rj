"""
Motor de Cruzamento e Reconciliação Inteligente de Fontes.
Responsável por casar processos judiciais de tribunais estaduais com a base de
Administradores Judiciais (Brizola, Ruiz, EXM, Kroll) e CVM.
"""

from __future__ import annotations

import difflib
import json
import logging
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from src.banco.repositorio import BancoDados
from src.ingestao.download import DIR_DATA_RAW
from src.ingestao.tribunais.base import limpar_numero_cnj

logger = logging.getLogger(__name__)

# Termos societários e complementos a remover na comparação de nomes
TERMOS_IGNORAR = [
    r"\bltda\b",
    r"\blimitada\b",
    r"\bs/?a\b",
    r"\bs\.a\.\b",
    r"\bepp\b",
    r"\bme\b",
    r"\beireli\b",
    r"\bcia\b",
    r"\bcompanhia\b",
    r"\bparticipacoes\b",
    r"\bparticipacao\b",
    r"\bempreendimentos\b",
    r"\bem recuperacao judicial\b",
    r"\brecuperacao judicial\b",
    r"\brecuperanda\b",
    r"\bgrupo\b",
    r"\bindustria e comercio\b",
    r"\bindustria\b",
    r"\bcomercio\b",
    r"\bservicos\b",
]


def normalizar_nome_empresa(nome: str) -> str:
    """Normaliza o nome/razão social para comparação comparativa resiliente."""
    if not nome:
        return ""

    # Remover acentuação
    texto = unicodedata.normalize("NFKD", nome).encode("ASCII", "ignore").decode("utf-8")
    texto = texto.lower()

    # Normalizar variações de S.A. / S/A
    texto = re.sub(r"\bs\s*[\./]?\s*a(?:\.|\b)", " ", texto)

    # Remover termos societários conhecidos
    for termo in TERMOS_IGNORAR:
        texto = re.sub(termo, " ", texto)

    # Remover pontuação e caracteres não alfanuméricos
    texto = re.sub(r"[^\w\s]", " ", texto)
    # Remover letras e conectivos residuais isolados
    texto = re.sub(r"\b(?:[sa]|e|de|da|do)\b", " ", texto)
    # Colapsar espaços
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto


def calcular_similaridade(nome_a: str, nome_b: str) -> float:
    """Calcula a similaridade difusa entre duas razões sociais (0.0 a 1.0)."""
    norm_a = normalizar_nome_empresa(nome_a)
    norm_b = normalizar_nome_empresa(nome_b)

    if not norm_a or not norm_b:
        return 0.0

    if norm_a == norm_b:
        return 1.0

    # Se um for substring exata do outro e tiver tamanho razoável
    if (len(norm_a) >= 5 and norm_a in norm_b) or (len(norm_b) >= 5 and norm_b in norm_a):
        return 0.95

    return difflib.SequenceMatcher(None, norm_a, norm_b).ratio()


@dataclass
class ResultadoMatch:
    """Representa um vínculo estabelecido entre um processo e uma fonte externa."""

    processo_cnj: str
    empresa_id: int
    empresa_nome: str
    fonte_aj: str
    tipo_match: str  # 'cnj', 'razao_social', 'administrador_judicial'
    confianca: float  # 0.0 a 1.0
    detalhes: str
    documentos_vinculados: int = 0

    def para_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ResultadoReconciliacao:
    """Relatório consolidado do processo de reconciliação de fontes."""

    total_processos_analisados: int = 0
    total_matches_encontrados: int = 0
    matches: list[ResultadoMatch] = field(default_factory=list)
    acoes_disparadas: list[str] = field(default_factory=list)

    def para_dict(self) -> dict[str, Any]:
        return {
            "total_processos_analisados": self.total_processos_analisados,
            "total_matches_encontrados": self.total_matches_encontrados,
            "matches": [m.para_dict() for m in self.matches],
            "acoes_disparadas": self.acoes_disparadas,
        }


class ReconciliadorFontes:
    """
    Motor de Reconciliação e Cruzamento entre Processos de Tribunais e Fontes de AJs/CVM.
    """

    MAPA_AJS_KEYWORDS = {
        "aj_ruiz": ["ruiz", "aj ruiz", "rubens ricardo martins de almeida"],
        "brizola": ["brizola", "japur", "brizola e japur"],
        "exm": ["exm", "exm partners", "eduardo scarpellini"],
        "kroll": ["kroll", "kroll associates"],
    }

    def __init__(self, banco: BancoDados | None = None) -> None:
        self.banco = banco or BancoDados()

    def reconciliar_processos(
        self,
        processos_cnj: list[str] | None = None,
        limiar_similaridade: float = 0.85,
        disparar_extracao: bool = True,
    ) -> int:
        """
        Executa a reconciliação para os processos informados (ou todos os do banco).
        Retorna a quantidade de matches estabelecidos.
        """
        res = self.executar_reconciliacao(
            processos_cnj=processos_cnj,
            limiar_similaridade=limiar_similaridade,
            disparar_extracao=disparar_extracao,
        )
        return res.total_matches_encontrados

    def executar_reconciliacao(
        self,
        processos_cnj: list[str] | None = None,
        limiar_similaridade: float = 0.85,
        disparar_extracao: bool = True,
    ) -> ResultadoReconciliacao:
        """
        Executa a reconciliação completa gerando relatório analítico.
        """
        relatorio = ResultadoReconciliacao()

        # 1. Carregar processos a analisar
        processos_para_analisar = self._carregar_processos_alvo(processos_cnj)
        relatorio.total_processos_analisados = len(processos_para_analisar)

        if not processos_para_analisar:
            logger.info("[Reconciliador] Nenhum processo encontrado para reconciliar.")
            return relatorio

        # 2. Carregar referências conhecidas de empresas e AJs
        catalogo_empresas = self._carregar_catalogo_empresas()
        catalogo_ajs = self._carregar_catalogo_manifesto_ajs()

        logger.info(
            "[Reconciliador] Analisando %d processos contra catálogo de %d empresas e %d referências de AJ...",
            len(processos_para_analisar),
            len(catalogo_empresas),
            len(catalogo_ajs),
        )

        for proc in processos_para_analisar:
            cnj = proc.get("numero_cnj", "")
            cnj_limpo = limpar_numero_cnj(cnj)
            proc_id = proc.get("id")
            proc_empresa_id = proc.get("empresa_id")
            empresa_nome = proc.get("empresa_nome", "")
            aj_nome = proc.get("administrador_judicial", "")

            match_encontrado: ResultadoMatch | None = None

            # Nível 1: Match Exato por CNJ no catálogo de AJs
            for item_aj in catalogo_ajs:
                if item_aj.get("cnj_limpo") and item_aj["cnj_limpo"] == cnj_limpo:
                    match_encontrado = ResultadoMatch(
                        processo_cnj=cnj,
                        empresa_id=proc_empresa_id,
                        empresa_nome=empresa_nome or item_aj.get("empresa", ""),
                        fonte_aj=item_aj.get("fonte", "aj"),
                        tipo_match="cnj",
                        confianca=1.0,
                        detalhes=f"Match exato de número CNJ com fonte {item_aj.get('fonte')}",
                        documentos_vinculados=item_aj.get("total_docs", 0),
                    )
                    break

            # Nível 2: Match por Razão Social (Fuzzy) com outras empresas cadastradas
            if not match_encontrado and empresa_nome:
                melhor_score = 0.0
                melhor_empresa: dict[str, Any] | None = None

                for emp in catalogo_empresas:
                    if emp["id"] == proc_empresa_id:
                        # Ignorar a própria empresa já associada ao processo
                        continue

                    score = calcular_similaridade(empresa_nome, emp["nome_razao_social"])
                    if score > melhor_score:
                        melhor_score = score
                        melhor_empresa = emp

                if melhor_score >= limiar_similaridade and melhor_empresa:
                    match_encontrado = ResultadoMatch(
                        processo_cnj=cnj,
                        empresa_id=melhor_empresa["id"],
                        empresa_nome=melhor_empresa["nome_razao_social"],
                        fonte_aj=melhor_empresa.get("origem_fonte", "conhecida"),
                        tipo_match="razao_social",
                        confianca=round(melhor_score, 2),
                        detalhes=(
                            f"Match fonético/fuzzy ({int(melhor_score*100)}%) entre "
                            f"'{empresa_nome}' e '{melhor_empresa['nome_razao_social']}'"
                        ),
                    )

            # Nível 3: Match por Administrador Judicial nomeado
            if not match_encontrado and aj_nome:
                aj_normalizado = aj_nome.lower()
                for fonte, keywords in self.MAPA_AJS_KEYWORDS.items():
                    if any(kw in aj_normalizado for kw in keywords):
                        match_encontrado = ResultadoMatch(
                            processo_cnj=cnj,
                            empresa_id=proc_empresa_id,
                            empresa_nome=empresa_nome,
                            fonte_aj=fonte,
                            tipo_match="administrador_judicial",
                            confianca=0.90,
                            detalhes=f"Administrador Judicial '{aj_nome}' identificado como fonte '{fonte}'",
                        )
                        break

            if match_encontrado:
                relatorio.total_matches_encontrados += 1
                relatorio.matches.append(match_encontrado)
                logger.info(
                    "[Reconciliador] Match estabelecido: CNJ %s -> %s (%s, confiança: %.2f)",
                    cnj,
                    match_encontrado.empresa_nome,
                    match_encontrado.tipo_match,
                    match_encontrado.confianca,
                )

                # Ação 1: Atualizar vínculo da empresa no banco caso tenha casado com outra existente
                if proc_id and match_encontrado.empresa_id != proc_empresa_id:
                    self._vincular_processo_a_empresa(proc_id, match_encontrado.empresa_id)
                    relatorio.acoes_disparadas.append(
                        f"Processo {cnj} vinculado à empresa ID {match_encontrado.empresa_id}"
                    )

                # Ação 2: Disparar extração de QGC se houver peças de credores disponíveis
                if disparar_extracao and match_encontrado.documentos_vinculados > 0:
                    docs_processados = self._processar_pecas_qgc_vinculadas(
                        match_encontrado.empresa_id, proc_id
                    )
                    if docs_processados > 0:
                        relatorio.acoes_disparadas.append(
                            f"Extração de QGC executada para {docs_processados} peças vinculadas"
                        )

        return relatorio

    def _carregar_processos_alvo(self, processos_cnj: list[str] | None = None) -> list[dict[str, Any]]:
        """Busca os processos a analisar a partir do banco de dados."""
        conn = self.banco.conectar()
        cur = conn.cursor()
        query = """
            SELECT p.id, p.numero_cnj, p.empresa_id, p.administrador_judicial, e.nome_razao_social
            FROM processos p
            LEFT JOIN empresas e ON p.empresa_id = e.id
        """
        params: list[Any] = []
        if processos_cnj:
            placeholders = ",".join("?" for _ in processos_cnj)
            query += f" WHERE p.numero_cnj IN ({placeholders})"
            params = list(processos_cnj)

        cur.execute(query, params)
        linhas = cur.fetchall()
        return [
            {
                "id": l[0],
                "numero_cnj": l[1],
                "empresa_id": l[2],
                "administrador_judicial": l[3],
                "empresa_nome": l[4] or "",
            }
            for l in linhas
        ]

    def _carregar_catalogo_empresas(self) -> list[dict[str, Any]]:
        """Carrega lista de empresas já cadastradas no banco."""
        conn = self.banco.conectar()
        cur = conn.cursor()
        cur.execute("SELECT id, slug, nome_razao_social, cnpj, origem_fonte FROM empresas")
        return [
            {
                "id": l[0],
                "slug": l[1],
                "nome_razao_social": l[2],
                "cnpj": l[3],
                "origem_fonte": l[4],
            }
            for l in cur.fetchall()
        ]

    def _carregar_catalogo_manifesto_ajs(self) -> list[dict[str, Any]]:
        """Carrega referências de processos e documentos existentes em data/raw."""
        caminho_manifesto = DIR_DATA_RAW / "ingestion_manifest.json"
        if not caminho_manifesto.exists():
            return []

        try:
            with open(caminho_manifesto, "r", encoding="utf-8") as f:
                dados = json.load(f)

            catalogo: dict[str, dict[str, Any]] = {}
            for item in dados.get("arquivos", []):
                fonte = item.get("fonte", "")
                empresa = item.get("empresa", "")
                metadados = item.get("metadados_extra", {})
                num_processo = metadados.get("numero_processo") or metadados.get("processo", "")
                cnj_limpo = limpar_numero_cnj(num_processo)

                chave = cnj_limpo if cnj_limpo else f"{fonte}_{empresa}"
                if chave not in catalogo:
                    catalogo[chave] = {
                        "fonte": fonte,
                        "empresa": empresa,
                        "cnj_limpo": cnj_limpo,
                        "total_docs": 0,
                        "arquivos": [],
                    }

                catalogo[chave]["total_docs"] += 1
                catalogo[chave]["arquivos"].append(item.get("caminho_relativo"))

            return list(catalogo.values())
        except Exception as e:
            logger.warning("[Reconciliador] Erro ao carregar catalogo de AJs: %s", e)
            return []

    def _vincular_processo_a_empresa(self, processo_id: int, nova_empresa_id: int) -> None:
        """Atualiza a chave estrangeira empresa_id do processo no banco."""
        conn = self.banco.conectar()
        with conn:
            conn.execute(
                "UPDATE processos SET empresa_id = ? WHERE id = ?",
                (nova_empresa_id, processo_id),
            )
        logger.info(
            "[Reconciliador] Processo ID %d atualizado para Empresa ID %d",
            processo_id,
            nova_empresa_id,
        )

    def _processar_pecas_qgc_vinculadas(self, empresa_id: int, processo_id: int | None) -> int:
        """Aciona a extração de QGC para documentos associados que ainda não foram extraídos."""
        try:
            from src.processamento.extrator_qgc import ExtratorQGC

            conn = self.banco.conectar()
            cur = conn.cursor()
            cur.execute(
                """
                SELECT d.id, d.caminho_arquivo, d.titulo
                FROM documentos d
                LEFT JOIN credores c ON c.documento_id = d.id
                WHERE d.empresa_id = ? AND d.categoria = 'QGC' AND c.id IS NULL
                LIMIT 5
                """,
                (empresa_id,),
            )
            docs = cur.fetchall()

            if not docs:
                return 0

            extrator = ExtratorQGC()
            total_processados = 0

            for doc_id, caminho_arq, titulo in docs:
                if not caminho_arq or not Path(caminho_arq).exists():
                    continue

                logger.info("[Reconciliador] Disparando extração QGC para documento %s (%s)...", doc_id, titulo)
                resultado = extrator.extrair_pdf(caminho_arq)
                if resultado.total_credores > 0:
                    lote_credores = [
                        {
                            "nome": c.nome,
                            "documento": c.documento,
                            "documento_limpo": c.documento_limpo,
                            "tipo_documento": c.tipo_documento,
                            "classe": c.classe,
                            "natureza": c.natureza,
                            "valor": c.valor,
                            "moeda": c.moeda,
                            "cidade": c.cidade,
                            "uf": c.uf,
                            "pagina": c.pagina,
                        }
                        for c in resultado.credores
                    ]
                    self.banco.salvar_credores_lote(
                        credores=lote_credores,
                        processo_id=processo_id,
                        documento_id=doc_id,
                    )
                    total_processados += 1

            return total_processados
        except Exception as e:
            logger.warning("[Reconciliador] Não foi possível executar extração automática de QGC: %s", e)
            return 0
