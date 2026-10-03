import hashlib
import math
import re

import requests
from decouple import config

DIMENSOES = 1536  # tem de coincidir com PersonalTrainer.embedding


class GeradorEmbeddings:
    """Interface: qualquer gerador devolve um vetor de DIMENSOES floats."""

    def gerar(self, texto):
        raise NotImplementedError


class OpenAIEmbeddings(GeradorEmbeddings):
    # endpoint e modelo documentados pela OpenAI; text-embedding-3-small devolve 1536 dimensoes
    URL = "https://api.openai.com/v1/embeddings"
    MODELO = "text-embedding-3-small"

    def gerar(self, texto):
        resposta = requests.post(
            self.URL,
            headers={"Authorization": f"Bearer {config('OPENAI_API_KEY')}"},
            json={"model": self.MODELO, "input": texto},
            timeout=10,
        )
        resposta.raise_for_status()
        return resposta.json()["data"][0]["embedding"]


class HashEmbeddings(GeradorEmbeddings):
    """Gerador local e deterministico (bag-of-words por hashing). Sem rede nem custo:
    serve para desenvolvimento e testes; capta semelhanca lexical, nao semantica."""

    def gerar(self, texto):
        vetor = [0.0] * DIMENSOES
        for palavra in re.findall(r"\w+", texto.lower()):
            h = int(hashlib.sha256(palavra.encode()).hexdigest(), 16)
            vetor[h % DIMENSOES] += 1.0
        norma = math.sqrt(sum(v * v for v in vetor))
        return [v / norma for v in vetor] if norma else vetor


def obter_gerador():
    """EMBEDDINGS_BACKEND=openai|hash (por omissao: openai so se houver OPENAI_API_KEY real)."""
    backend = config("EMBEDDINGS_BACKEND", default="")
    if not backend:
        chave = config("OPENAI_API_KEY", default="")
        backend = "openai" if chave and not chave.startswith("sk-ficticia") else "hash"
    return OpenAIEmbeddings() if backend == "openai" else HashEmbeddings()


def texto_do_trainer(pt):
    partes = [pt.especialidade, pt.localizacao, pt.biografia]
    partes += [c.nome for c in pt.certificacoes.all()]
    return " ".join(p for p in partes if p)


def atualizar_embedding(pt, gerador=None):
    """Recalcula e grava o embedding do PT. Falhas do servico externo nao propagam."""
    texto = texto_do_trainer(pt)
    if not texto:
        return False
    try:
        pt.embedding = (gerador or obter_gerador()).gerar(texto)
    except requests.RequestException:
        return False
    pt.save(update_fields=["embedding"])
    return True