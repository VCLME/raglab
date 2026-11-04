"""Labelled examples behind the intent centroids.

Written for the router, independently of the frozen evaluation sets: none of
these sentences comes from `benchmarks/abstention/questions.jsonl` or from
the PIAF / LexML ground truths, so the evaluation stays out of sample.

- documentary: questions whose answer would sit in an indexed text
  (encyclopedic in French, federal law in Portuguese, the French consumer
  code, EU compliance acts in English, French and Portuguese, plus mixes);
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
            "Quel délai de rétractation le consommateur a-t-il après un achat à distance ?",
            "Quelles informations le vendeur doit-il donner avant la conclusion du contrat ?",
            "Dans quel délai une violation de données personnelles doit-elle être notifiée à l'autorité ?",
            "Quelles obligations pèsent sur le fournisseur d'un système d'IA à haut risque ?",
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
            "Quando o responsável pelo tratamento deve nomear um encarregado da proteção de dados?",
            "Que medidas de gestão de riscos de cibersegurança a diretiva exige das entidades essenciais?",
        ],
        "en": [
            "What rights does the data subject have to obtain erasure of personal data?",
            "Within how many hours must a personal data breach be reported to the supervisory authority?",
            "Which AI practices are prohibited under the regulation?",
            "What must a provider of a high-risk AI system document before placing it on the market?",
            "Which entities fall within the scope of the cybersecurity directive?",
            "How must financial entities manage ICT third-party risk?",
            "What are the conditions for the lawful processing of personal data?",
            "Who designates the national competent authorities?",
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
        "en": [
            "Hi there!",
            "Good morning, how are you?",
            "Thanks, that helps a lot.",
            "What is your name?",
            "Are you an AI?",
            "How do you work?",
            "I did not understand your answer.",
            "Can you say that more simply?",
            "See you later!",
            "Okay, got it.",
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
        "en": [
            "How many vacation days do I have left this year?",
            "Where is my parcel right now?",
            "What is the weather forecast for tomorrow in Dublin?",
            "What is the share price of Siemens today?",
            "Who won the football match last night?",
            "Write a cover letter for a marketing job.",
            "Translate this paragraph into Spanish.",
            "Write a Python script that renames my files.",
            "When is our next team meeting?",
            "Book a table for two tonight.",
        ],
    },
}


def iter_examples():
    """Yield (intent, language, text) for every labelled example."""
    for intent, by_language in EXAMPLES.items():
        for language, texts in by_language.items():
            for text in texts:
                yield intent, language, text
