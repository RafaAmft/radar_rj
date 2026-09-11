# Radar de Oportunidades em Recuperação de Ativos — Catalogador de Ingestão

Pipeline automatizado de ingestão e catalogação de dados públicos para monitoramento de processos de **Recuperação Judicial (RJ)**, **Extrajudicial** e **Falências** no Brasil.

O sistema integra dados regulatórios da **CVM**, bases processuais dos **Tribunais de Justiça (e-SAJ/DataJud)** e datasets jurisprudenciais (**ITD/STF**), construindo um repositório auditável e idempotente para geração de inteligência em *Special Situations* e *Distressed Assets*.

---

## 🏛️ Fontes de Dados (Fase 1)

| Extrator | Fonte Pública | Tipo de Dado | Frequência | Resiliência |
|:---|:---|:---|:---:|:---:|
| `cvm-dfp` | Dados Abertos CVM | Demonstrações Financeiras Padronizadas (DFP e ITR) | Anual / Trimestral | 🟢 Alta (ZIPs estáticos) |
| `cvm-ipe` | Dados Abertos CVM | Informações Periódicas e Eventuais (Fatos Relevantes, Atas de AGC, PRJs) | Diária / Eventual | 🟢 Alta (CSV + PDF) |
| `itd` | UFPR / C3SL | Acórdãos estruturados do STF (ementa, relatório, votos) | Amostra pontual | 🟢 Alta (JSON streaming) |
| `esaj` | TJSP (e-SAJ) / CNJ | Consulta pública de processos de RJ (Fallback automático via DataJud) | Sob demanda | 🟡 Média (Best-effort) |

---

## 📁 Estrutura do Projeto

```text
Catalogador/
├── config/
│   ├── empresas.yaml                 # Catálogo de empresas-alvo (razão social, CNPJ, CVM, slug)
│   └── fontes/
│       ├── cvm_dfp_itr.yaml          # Configurações de download DFP/ITR da CVM
│       ├── cvm_ipe.yaml              # Configurações do índice IPE da CVM
│       ├── esaj.yaml                 # Configurações do e-SAJ e fallback DataJud
│       └── itd.yaml                  # Configurações do dataset ITD (UFPR/STF)
├── src/
│   └── ingestao/
│       ├── cli.py                    # Orquestrador central de linha de comando
│       ├── cvm_dfp_itr.py            # Extrator 1: DFP e ITR (BPA, BPP, DRE, DFC, etc.)
│       ├── cvm_ipe.py                # Extrator 2: Fatos Relevantes, AGCs e Comunicados
│       ├── itd_acordaos.py           # Extrator 3: Amostra estrutural do STF
│       ├── esaj_tjsp.py              # Extrator 4: Processos judiciais e DataJud
│       ├── download.py               # Utilitários HTTP, retry exponencial, rate limit e hashes
│       └── manifesto.py              # Gestão de idempotência (ingestion_manifest.json)
├── tests/
│   ├── test_download.py              # Testes de hash, ZIPs e YAML
│   ├── test_manifesto.py             # Testes de auditoria e idempotência
│   ├── test_rate_limit.py            # Testes de throttle por domínio e slugs dinâmicos
│   └── test_extratores.py            # Testes unitários dos extratores com mocks
├── data/
│   └── raw/                          # Repositório de dados brutos (ignorado no Git)
├── logs/                             # Logs diários de auditoria das execuções
├── .env.example                      # Template de variáveis de ambiente
├── pyproject.toml                    # Metadados do pacote e dependências
└── README.md                         # Documentação técnica
```

---

## 🚀 Instalação e Configuração

### 1. Pré-requisitos
- Python 3.10 ou superior
- Ambiente virtual (`venv` ou `conda`)

### 2. Clonar e Instalar em Modo Editável
```powershell
# Criar ambiente virtual
python -m venv venv
.\venv\Scripts\Activate.ps1

# Instalar o pacote em modo editável com dependências de desenvolvimento
pip install -e ".[dev]"
```

### 3. Configurar Variáveis de Ambiente
Copie o arquivo de exemplo e configure a chave de acesso do DataJud (CNJ):
```powershell
cp .env.example .env
```

---

## 💻 Como Usar a CLI

A CLI orquestradora unifica todos os extratores e oferece controle granular de escopo, anos e taxas.

### Exemplos de Execução

```powershell
# 1. Ajuda e lista de parâmetros disponíveis (slugs dinâmicos)
python -m src.ingestao.cli --help

# 2. Execução completa de todos os extratores (ordem recomendada)
python -m src.ingestao.cli --extrator todos

# 3. Baixar documentos da CVM IPE de uma empresa específica (ex: Oi) em 2024
python -m src.ingestao.cli --extrator cvm-ipe --empresa oi --ano 2024

# 4. Modo Simulação (Dry-Run) — não baixa nada, apenas lista o plano de ação
python -m src.ingestao.cli --extrator cvm-dfp --empresa americanas --dry-run

# 5. Execução limitada para testes (ex: baixar no máximo 5 PDFs)
python -m src.ingestao.cli --extrator cvm-ipe --empresa light --ano 2024 --limite 5

# 6. Extrator de processos judiciais (TJSP com fallback DataJud)
python -m src.ingestao.cli --extrator esaj --empresa oi
```

---

## 🔒 Idempotência e Auditoria

Todas as operações de ingestão são rastreadas através do arquivo `ingestion_manifest.json` presente em cada pasta de empresa (`data/raw/<slug>/ingestion_manifest.json`):

- **Hash SHA-256:** Cada arquivo baixado tem seu hash criptográfico validado e registrado.
- **Idempotência Real:** Se uma URL ou arquivo já foi ingerido com sucesso, o download é ignorado automaticamente.
- **Rate Limiting Coordenado:** O sistema respeita intervalos mínimos por domínio (ex: `dados.cvm.gov.br`, `cnj.jus.br`) para prevenir bloqueios de IP.
- **Logs Automatizados:** Cada execução gera um log detalhado em `logs/ingestao_YYYY-MM-DD.log`.

---

## 🧪 Bateria de Testes

O projeto possui cobertura de testes unitários sem dependência de internet (usando mocks):

```powershell
# Executar todos os testes
pytest -v

# Executar com relatório de cobertura
pytest --cov=src.ingestao
```

---

## 🗺️ Roadmap de Desenvolvimento

- [x] **Fase 1 (Concluída):** Ingestão CVM (DFP/ITR/IPE), Amostra ITD, Fallback DataJud, CLI com Rate Limiting e Manifestos.
- [ ] **Fase 2 (Próxima):** Scrapers de portais de Administradores Judiciais (Kroll, Preserva, AJ Regional), OCR para PDFs escaneados (PyMuPDF + Tesseract).
- [ ] **Fase 3 (Futura):** Motor NER para extração estruturada de créditos (QGCs), editais de leilão e banco relacional PostgreSQL.
- [ ] **Fase 4 (Futura):** Interface Web de Sourcing, Dashboard de Oportunidades e Alertas em Tempo Real.
