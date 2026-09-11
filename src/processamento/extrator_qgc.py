"""
Motor de extração estruturada de Quadros Gerais de Credores (QGC) e Relações de Credores.

Lê documentos judiciais de recuperação e falência, identifica tabelas e listas de credores,
normaliza classes (I a IV da Lei 11.101/2005), documentos (CNPJ/CPF) e valores monetários,
exportando em JSON analítico e CSV pronto para modelos financeiros e fundos de crédito.
"""

from __future__ import annotations

import csv
import json
import logging
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import pymupdf

logger = logging.getLogger(__name__)


@dataclass
class CredorRecord:
    """Registro estruturado de um credor em processo de Recuperação Judicial ou Falência."""

    nome: str
    documento: str = ""              # Formatado (ex: "55.788.528/0001-69" ou "123.456.789-00")
    documento_limpo: str = ""        # Apenas dígitos numéricos
    tipo_documento: str = "DESCONHECIDO"  # "CNPJ" | "CPF" | "ESTRANGEIRO" | "DESCONHECIDO"
    classe: str = "III - Quirografário"  # Classes I, II, III, IV ou Extraconcursal
    natureza: str = ""               # Ex: "Fornecimento de Insumos", "Prestação de Serviços", "Bancário"
    valor: float = 0.0               # Valor do crédito em formato numérico float
    moeda: str = "BRL"
    cidade: str = ""
    uf: str = ""
    pagina: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ResultadoQGC:
    """Resultado consolidado da extração de um Quadro Geral ou Relação de Credores."""

    nome_arquivo: str
    total_credores: int = 0
    valor_total_apurado: float = 0.0
    totais_por_classe: dict[str, float] = field(default_factory=dict)
    quantidade_por_classe: dict[str, int] = field(default_factory=dict)
    credores: list[CredorRecord] = field(default_factory=list)
    metadados: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "nome_arquivo": self.nome_arquivo,
            "total_credores": self.total_credores,
            "valor_total_apurado": round(self.valor_total_apurado, 2),
            "totais_por_classe": {k: round(v, 2) for k, v in self.totais_por_classe.items()},
            "quantidade_por_classe": self.quantidade_por_classe,
            "metadados": self.metadados,
            "credores": [c.to_dict() for c in self.credores],
        }


class ExtratorQGC:
    """Motor de parsing e tabulação de relações de credores da Lei 11.101/2005."""

    PADRAO_CNPJ = re.compile(r"\b(\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2})\b")
    PADRAO_CPF = re.compile(r"\b(\d{3}\.?\d{3}\.?\d{3}-?\d{2})\b")
    PADRAO_VALOR_MONETARIO = re.compile(
        r"(?:R\$\s*)?([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2})"
    )

    @staticmethod
    def normalizar_valor(texto_valor: Any) -> float:
        """
        Converte representações monetárias brasileiras para float.
        Exemplos:
          '12.674,00' -> 12674.00
          'R$ 1.500.000,50' -> 1500000.50
          '- 6.789,62-' -> 6789.62
          ' 0,00 ' -> 0.0
        """
        if not texto_valor:
            return 0.0
        if isinstance(texto_valor, (int, float)):
            return float(texto_valor)

        s = str(texto_valor).strip()
        # Remover símbolos de moeda e caracteres espúrios
        s = re.sub(r"[R$\s\-]", "", s)
        # Extrair apenas padrão numérico com ponto e vírgula
        match = re.search(r"([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2})|([0-9]+,[0-9]{2})", s)
        if match:
            num_str = match.group(0).replace(".", "").replace(",", ".")
            try:
                return float(num_str)
            except ValueError:
                pass
        return 0.0

    @classmethod
    def normalizar_documento(cls, texto_doc: Any) -> tuple[str, str, str]:
        """
        Higieniza e classifica um documento em CNPJ, CPF ou Desconhecido.
        Retorna: (formatado, apenas_digitos, tipo)
        """
        if not texto_doc:
            return ("", "", "DESCONHECIDO")

        s = str(texto_doc).strip()
        digitos = re.sub(r"\D", "", s)

        if len(digitos) == 14:
            formatado = (
                f"{digitos[:2]}.{digitos[2:5]}.{digitos[5:8]}/"
                f"{digitos[8:12]}-{digitos[12:]}"
            )
            return (formatado, digitos, "CNPJ")

        if len(digitos) == 11:
            formatado = f"{digitos[:3]}.{digitos[3:6]}.{digitos[6:9]}-{digitos[9:]}"
            return (formatado, digitos, "CPF")

        # Verificar se continha padrão formatado com pontuação
        m_cnpj = cls.PADRAO_CNPJ.search(s)
        if m_cnpj:
            d = re.sub(r"\D", "", m_cnpj.group(0))
            if len(d) == 14:
                return (m_cnpj.group(0), d, "CNPJ")

        m_cpf = cls.PADRAO_CPF.search(s)
        if m_cpf:
            d = re.sub(r"\D", "", m_cpf.group(0))
            if len(d) == 11:
                return (m_cpf.group(0), d, "CPF")

        return (s, digitos, "DESCONHECIDO" if not digitos else "ESTRANGEIRO")

    @staticmethod
    def normalizar_classe(texto_classe: str) -> str:
        """
        Enquadra a classe do crédito nas categorias jurídicas da Lei 11.101/2005.
        - Classe I: Trabalhista / Acidente de Trabalho
        - Classe II: Garantia Real
        - Classe III: Quirografário / Privilégio Especial/Geral / Abrangido
        - Classe IV: Microempresa (ME) e Empresa de Pequeno Porte (EPP)
        - Extraconcursal: Créditos não sujeitos aos efeitos da RJ
        """
        if not texto_classe:
            return "III - Quirografário"

        t_norm = unicodedata.normalize("NFKD", str(texto_classe).lower())
        t = "".join(c for c in t_norm if not unicodedata.combining(c))

        # Extraconcursal
        if any(k in t for k in ["extraconcursal", "art. 49", "alienacao fiduciaria", "trava"]):
            return "Extraconcursal"

        # Classe IV (ME/EPP)
        if re.search(r"\bclasse\s*(?:iv|4)\b", t) or any(
            k in t for k in ["me/epp", "microempresa", "pequeno porte", " epp"]
        ):
            return "IV - ME/EPP"

        # Classe III (Quirografário)
        if re.search(r"\bclasse\s*(?:iii|3)\b", t) or any(
            k in t for k in ["quirograf", "privilegio especial", "privilegio geral"]
        ):
            return "III - Quirografário"

        # Classe II (Garantia Real)
        if re.search(r"\bclasse\s*(?:ii|2)\b", t) or any(
            k in t for k in ["garantia real", "hipotec", "penhor"]
        ):
            return "II - Garantia Real"

        # Classe I (Trabalhista)
        if re.search(r"\bclasse\s*(?:i|1)\b", t) or any(
            k in t for k in ["trabalh", "acidente de trabalho"]
        ):
            return "I - Trabalhista"

        # Padrão ou classe III
        return "III - Quirografário"


    def extrair_pdf(self, caminho_pdf: str | Path) -> ResultadoQGC:
        """
        Executa o pipeline de extração estruturada de credores a partir de um PDF.
        """
        caminho = Path(caminho_pdf)
        if not caminho.exists():
            raise FileNotFoundError(f"Arquivo PDF não encontrado: {caminho}")

        logger.info("Iniciando extração estruturada de QGC em: %s", caminho.name)
        doc = pymupdf.open(caminho)

        credores: list[CredorRecord] = []
        documentos_vistos: set[tuple[str, str]] = set()

        # ----------------------------------------------------------------------
        # CAMADA 1: Extração Tabular Nativa (PyMuPDF TableFinder)
        # ----------------------------------------------------------------------
        for num_pag, page in enumerate(doc, start=1):
            try:
                tables = page.find_tables()
            except Exception as e:
                logger.debug("Falha ao buscar tabelas na página %d: %s", num_pag, e)
                continue

            for table in tables:
                linhas = table.extract()
                if not linhas or len(linhas) < 2:
                    continue

                # Mapeamento do cabeçalho da tabela
                header = [str(c).strip().lower() if c else "" for c in linhas[0]]
                idx_nome = -1
                idx_doc = -1
                idx_classe = -1
                idx_valor = -1
                idx_natureza = -1
                idx_cidade = -1
                idx_uf = -1

                for col_idx, col_name in enumerate(header):
                    col_norm = unicodedata.normalize("NFKD", col_name)
                    col_limpa = "".join(c for c in col_norm if not unicodedata.combining(c))

                    if any(k in col_limpa for k in ["credor", "razao social", "nome"]):
                        idx_nome = col_idx
                    elif any(k in col_limpa for k in ["cnpj", "cpf", "documento"]):
                        idx_doc = col_idx
                    elif "classe" in col_limpa:
                        idx_classe = col_idx
                    elif any(k in col_limpa for k in ["credito liquido", "credito", "valor", "saldo"]):
                        idx_valor = col_idx
                    elif any(k in col_limpa for k in ["natureza", "origem"]):
                        idx_natureza = col_idx
                    elif "cidade" in col_limpa or "municipio" in col_limpa:
                        idx_cidade = col_idx
                    elif "uf" in col_limpa or "estado" in col_limpa:
                        idx_uf = col_idx

                # Se ao menos localizou coluna de credor ou documento e valor
                if idx_nome != -1 or idx_doc != -1:
                    for row in linhas[1:]:
                        if not any(row):
                            continue

                        nome_raw = row[idx_nome] if idx_nome != -1 and idx_nome < len(row) else ""
                        nome = str(nome_raw).strip() if nome_raw else ""

                        doc_raw = row[idx_doc] if idx_doc != -1 and idx_doc < len(row) else ""
                        doc_formatado, doc_limpo, tipo_doc = self.normalizar_documento(doc_raw)

                        # Se não tem nome mas tem documento, ou vice-versa
                        if not nome and not doc_limpo:
                            continue

                        # Ignorar linhas de cabeçalho repetidas no meio da tabela
                        if any(k in nome.lower() for k in ["razão social", "razao social", "credor", "total geral"]):
                            continue

                        valor_raw = row[idx_valor] if idx_valor != -1 and idx_valor < len(row) else 0.0
                        valor = self.normalizar_valor(valor_raw)

                        classe_raw = row[idx_classe] if idx_classe != -1 and idx_classe < len(row) else ""
                        classe = self.normalizar_classe(classe_raw)

                        natureza_raw = row[idx_natureza] if idx_natureza != -1 and idx_natureza < len(row) else ""
                        natureza = str(natureza_raw).strip() if natureza_raw else ""

                        cidade_raw = row[idx_cidade] if idx_cidade != -1 and idx_cidade < len(row) else ""
                        cidade = str(cidade_raw).strip() if cidade_raw else ""

                        uf_raw = row[idx_uf] if idx_uf != -1 and idx_uf < len(row) else ""
                        uf = str(uf_raw).strip() if uf_raw else ""

                        chave = (doc_limpo or nome, classe)
                        if chave in documentos_vistos:
                            continue
                        documentos_vistos.add(chave)

                        credores.append(
                            CredorRecord(
                                nome=nome,
                                documento=doc_formatado,
                                documento_limpo=doc_limpo,
                                tipo_documento=tipo_doc,
                                classe=classe,
                                natureza=natureza,
                                valor=valor,
                                cidade=cidade,
                                uf=uf,
                                pagina=num_pag,
                            )
                        )

        # ----------------------------------------------------------------------
        # CAMADA 2: Fallback Heurístico (Scanning de Blocos Textuais)
        # ----------------------------------------------------------------------
        if len(credores) < 3:
            logger.info("[%s] Poucas tabelas nativas encontradas (%d). Acionando Camada 2 (Blocos de Texto)...", caminho.name, len(credores))
            classe_corrente = "III - Quirografário"

            for num_pag, page in enumerate(doc, start=1):
                texto_pag = page.get_text("text")
                linhas = [l.strip() for l in texto_pag.split("\n") if l.strip()]

                for i, linha in enumerate(linhas):
                    # Detecção de cabeçalho de classe na página
                    if any(c in linha.lower() for c in ["classe i", "classe ii", "classe iii", "classe iv", "quirograf", "trabalhist"]):
                        classe_corrente = self.normalizar_classe(linha)

                    # Verificar se a linha contém um CNPJ ou CPF
                    match_doc = self.PADRAO_CNPJ.search(linha) or self.PADRAO_CPF.search(linha)
                    if match_doc:
                        doc_str = match_doc.group(0)
                        doc_formatado, doc_limpo, tipo_doc = self.normalizar_documento(doc_str)

                        # O nome do credor geralmente antecede a linha do documento
                        nome_credor = ""
                        for j in range(max(0, i - 3), i):
                            cand = linhas[j]
                            if (
                                len(cand) >= 3
                                and not self.PADRAO_CNPJ.search(cand)
                                and not self.PADRAO_CPF.search(cand)
                                and not cand.lower().startswith("classe")
                                and not cand.lower().startswith("processo")
                            ):
                                nome_credor = cand

                        # O valor do crédito geralmente está na mesma linha ou logo a seguir
                        valor_credito = 0.0
                        for j in range(i, min(len(linhas), i + 4)):
                            match_v = self.PADRAO_VALOR_MONETARIO.search(linhas[j])
                            if match_v:
                                valor_credito = self.normalizar_valor(match_v.group(1))
                                if valor_credito > 0:
                                    break

                        if doc_limpo:
                            chave = (doc_limpo, classe_corrente)
                            if chave not in documentos_vistos:
                                documentos_vistos.add(chave)
                                credores.append(
                                    CredorRecord(
                                        nome=nome_credor or "Credor Não Identificado",
                                        documento=doc_formatado,
                                        documento_limpo=doc_limpo,
                                        tipo_documento=tipo_doc,
                                        classe=classe_corrente,
                                        valor=valor_credito,
                                        pagina=num_pag,
                                    )
                                )

        # ----------------------------------------------------------------------
        # Consolidação e Agregação Financeira
        # ----------------------------------------------------------------------
        valor_total = sum(c.valor for c in credores)
        totais_classe: dict[str, float] = {}
        qtd_classe: dict[str, int] = {}

        for c in credores:
            totais_classe[c.classe] = totais_classe.get(c.classe, 0.0) + c.valor
            qtd_classe[c.classe] = qtd_classe.get(c.classe, 0) + 1

        logger.info(
            "[%s] Extração concluída: %d credores estruturados | Total: R$ %.2f",
            caminho.name,
            len(credores),
            valor_total,
        )

        return ResultadoQGC(
            nome_arquivo=caminho.name,
            total_credores=len(credores),
            valor_total_apurado=valor_total,
            totais_por_classe=totais_classe,
            quantidade_por_classe=qtd_classe,
            credores=credores,
            metadados={
                "origem": str(caminho),
                "paginas_pdf": len(doc),
            },
        )

    def salvar_resultado(
        self, resultado: ResultadoQGC, dir_destino: str | Path
    ) -> tuple[Path, Path]:
        """
        Exporta o resultado do QGC para JSON estruturado e CSV analítico.

        Returns:
            Tupla contendo (caminho_json, caminho_csv).
        """
        destino = Path(dir_destino)
        destino.mkdir(parents=True, exist_ok=True)
        stem = Path(resultado.nome_arquivo).stem

        # 1. Salvar JSON
        caminho_json = destino / f"{stem}_credores.json"
        with open(caminho_json, "w", encoding="utf-8") as f:
            json.dump(resultado.to_dict(), f, indent=2, ensure_ascii=False)

        # 2. Salvar CSV
        caminho_csv = destino / f"{stem}_credores.csv"
        colunas = [
            "classe",
            "nome",
            "documento",
            "documento_limpo",
            "tipo_documento",
            "natureza",
            "valor",
            "moeda",
            "cidade",
            "uf",
            "pagina",
        ]
        with open(caminho_csv, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=colunas, delimiter=";")
            writer.writeheader()
            for c in resultado.credores:
                writer.writerow(c.to_dict())

        logger.info("Dossiê de credores salvo:")
        logger.info("  JSON: %s", caminho_json)
        logger.info("  CSV : %s", caminho_csv)

        return (caminho_json, caminho_csv)
