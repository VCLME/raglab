"""Labelled examples behind the intent centroids.

Written for the router, independently of the frozen evaluation sets: none of
these sentences comes from `benchmarks/abstention/questions.jsonl` or from
the PIAF / LexML ground truths, so the evaluation stays out of sample.

- documentary: questions whose answer would sit in an indexed text
  (encyclopedic in French, federal law in Portuguese, plus the reverse mix);
- conversational: talking to the assistant rather than asking about the texts;
- out_of_scope: requests no document collection can answer (personal data,
  live information, tasks to perform, private company matters).
"""

from __future__ import annotations

EXAMPLES: dict[str, dict[str, list[str]]] = {
    "documentary": {
        "fr": [
            "En quelle année la bataille de Marignan a-t-elle eu lieu ?",
            "Quel est le rôle de la chlorophylle dans la photosynthèse ?",
            "Qui a fondé la ville de Marseille dans l'Antiquité ?",
            "Combien d'habitants compte l'agglomération lyonnaise au XIXe siècle ?",
            "De quelle famille de plantes fait partie la tomate ?",
            "Quelle est la principale ressource économique de la Nouvelle-Calédonie ?",
            "Pourquoi le roi a-t-il convoqué les états généraux ?",
            "Quel compositeur a écrit cet opéra créé à Vienne ?",
            "Comment se reproduisent les fougères ?",
            "Quelle langue parlait-on dans le royaume wisigoth ?",
            "Quel traité a mis fin à la guerre de Trente Ans ?",
            "Dans quel club l'attaquant a-t-il commencé sa carrière professionnelle ?",
            "Que prévoit le texte sur la durée du mandat présidentiel ?",
            "Quelles sont les conditions fixées par la loi pour obtenir cette exonération ?",
            "Quel organisme est chargé de contrôler l'application du règlement ?",
        ],
        "pt": [
            "Qual é o prazo para a empresa recolher a contribuição prevista na lei?",
            "O que estabelece o art. 5º da Lei nº 8.112 sobre a posse em cargo público?",
            "Quais documentos devem acompanhar o pedido de registro do medicamento?",
            "Qual órgão fiscaliza a aplicação das normas sobre agrotóxicos?",
            "Quem pode requerer a isenção do imposto de renda prevista nesta norma?",
            "Qual é a pena para quem descumpre a obrigação de informar o Fisco?",
            "Como é calculado o valor do benefício previdenciário segundo a lei?",
            "Quais são as atribuições do Conselho Nacional criado pela lei?",
            "A partir de quando a alíquota reduzida passa a valer?",
            "O que a lei define como microempresa para fins tributários?",
            "Que percentual da receita deve ser destinado ao fundo?",
            "Quem foi o primeiro governador da capitania de Pernambuco?",
            "Qual é a extensão do rio São Francisco?",
            "Em que ano foi fundada a cidade de Salvador?",
            "Como funciona o processo de fotossíntese nas algas?",
        ],
    },
    "conversational": {
        "fr": [
            "Coucou !",
            "Bonsoir, comment vas-tu ?",
            "Merci, c'est exactement ce que je cherchais.",
            "Super, merci bien !",
            "Comment tu t'appelles ?",
            "Tu es un modèle d'intelligence artificielle ?",
            "Comment est-ce que tu fonctionnes ?",
            "Je n'ai pas compris ta réponse.",
            "Tu peux reformuler plus simplement ?",
            "Ce n'est pas ce que je voulais dire.",
            "À plus tard !",
            "Bonne soirée et merci.",
            "Tu aimes la musique ?",
            "Tu t'ennuies parfois ?",
            "Très bien, compris.",
            "Ah oui, intéressant.",
        ],
        "pt": [
            "Oi!",
            "Boa tarde, como você está?",
            "Obrigada, ajudou muito.",
            "Perfeito, muito obrigado!",
            "Qual é o seu nome?",
            "Você é uma inteligência artificial?",
            "Como você funciona?",
            "Não gostei da resposta.",
            "Pode resumir em poucas palavras?",
            "Acho que você se enganou.",
            "Até logo!",
            "Boa noite e obrigado.",
            "Você gosta de música?",
            "Você fica entediado?",
            "Certo, compreendi.",
            "Ah, legal.",
        ],
    },
    "out_of_scope": {
        "fr": [
            "Combien me reste-t-il de congés payés cette année ?",
            "Où en est la livraison de ma commande ?",
            "Quel est mon numéro de sécurité sociale ?",
            "Quelle météo est prévue demain à Lille ?",
            "Quel est le cours de l'action Airbus en ce moment ?",
            "Quels sont les résultats des matchs de ce soir ?",
            "Rédige une lettre de motivation pour un poste de comptable.",
            "Traduis ce paragraphe en allemand.",
            "Écris une fonction Python qui trie une liste.",
            "Calcule 17 % de 2 350 euros.",
            "Qui est le responsable de mon service ?",
            "Quand a lieu la prochaine réunion d'équipe ?",
            "Quel est le budget du projet interne de cette année ?",
            "Peux-tu réserver une table au restaurant pour ce soir ?",
        ],
        "pt": [
            "Quanto falta para pagar o meu financiamento?",
            "Qual é o status do meu pedido na loja?",
            "Qual é a minha senha do aplicativo do banco?",
            "Vai chover hoje em Recife?",
            "Quanto está valendo o euro hoje?",
            "Quem ganhou o jogo de ontem à noite?",
            "Escreva um e-mail pedindo aumento ao meu chefe.",
            "Traduza este texto para o inglês.",
            "Crie uma planilha com os meus gastos do mês.",
            "Quanto é 15% de 3.400 reais?",
            "Quem é o gerente do meu departamento?",
            "Quando é a próxima reunião da diretoria da empresa?",
            "Qual é a meta de vendas da nossa equipe neste trimestre?",
            "Marque uma consulta médica para amanhã.",
        ],
    },
}


def iter_examples():
    """Yield (intent, language, text) for every labelled example."""
    for intent, by_language in EXAMPLES.items():
        for language, texts in by_language.items():
            for text in texts:
                yield intent, language, text
