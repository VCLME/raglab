"""Build `benchmarks/br_expat/ground_truth.jsonl` from the owner's 30 questions.

The questions, expected answers and references are written by hand below
(see `benchmarks/br_expat/README.md` for where each reference was checked and
corrected). This script only turns each reference into offsets in the
collected texts, so a re-collection that moves a span is caught here rather
than silently in the benchmark:

- `expected_spans` (what `raglab bench` scores): the whole article, from its
  heading to the next article heading. "Article level": a chunk anywhere in
  the right article counts.
- `context.provision_spans`: the lines that actually carry the answer (a
  paragraph, an inciso). Stricter, used in the failure analysis.

Usage: python scripts/br_expat_ground_truth.py [--corpus data/lexml/br_expat/corpus]
Fails on any article or anchor it cannot find.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

THEMES = {
    "immigration": "Immigration et séjour",
    "company_tax": "Société (lucro presumido) et impôts",
    "inss_personal_tax": "INSS, retraite, fiscalité personnelle",
    "trap": "Pièges",
    "paraphrase": "Paraphrases familières",
}

# (file stem, article, anchors). The article is "20", "1.723", "15-B", or
# "Artigo 16" for the France-Brazil agreement, whose articles are headed that
# way. Each anchor is a substring of a line that carries the answer.
Ref = tuple[str, str, list[str]]

QUESTIONS: list[dict[str, Any]] = [
    # Immigration et séjour
    {
        "id": "brx-01",
        "theme": "immigration",
        "question": "Combien de temps un visiteur peut-il rester au Brésil, et peut-on prolonger ?",
        "answer": "Le visto de visita donne un séjour de 90 jours au plus, prolongeable par la Polícia Federal de 90 jours au plus, sans dépasser 180 jours par année migratoire.",
        "refs": [("decreto_9199_2017", "20", ["O visto de visita terá prazo de estada de até noventa dias"])],
    },
    {
        "id": "brx-02",
        "theme": "immigration",
        "question": "La prolongation du séjour visiteur est-elle possible pour tous les pays ?",
        "answer": "Non : la prorrogation n'est possible que pour les ressortissants des pays qui assurent la réciprocité de traitement aux Brésiliens.",
        "refs": [("decreto_9199_2017", "20", ["§ 2º A prorrogação do prazo de estada"])],
    },
    {
        "id": "brx-03",
        "theme": "immigration",
        "question": "Si je quitte le Brésil quelques jours, est-ce que le décompte de mon séjour s'arrête ?",
        "answer": "Oui : le décompte du séjour du visto de visita commence à la première entrée et est suspendu chaque fois que le visiteur quitte le territoire.",
        "refs": [("decreto_9199_2017", "20", ["§ 1º A contagem do prazo de estada"])],
    },
    {
        "id": "brx-04",
        "theme": "immigration",
        "question": "Quelle amende si je reste au-delà de mon séjour autorisé ?",
        "answer": "Rester après l'expiration du séjour est puni d'une amende par jour d'excès (et d'une déportation si l'on ne part pas ou ne se régularise pas) ; pour une personne physique, l'amende va de R$ 100 à R$ 10 000.",
        "refs": [
            ("decreto_9199_2017", "307", ["II - permanecer no território nacional depois de encerrado"]),
            ("lei_13445_2017", "109", ["II - permanecer em território nacional depois de esgotado"]),
            ("lei_13445_2017", "108", ["V - o valor mínimo de R$ 100,00"]),
            ("decreto_9199_2017", "301", ["V - o valor mínimo de R$ 100,00"]),
        ],
    },
    {
        "id": "brx-05",
        "theme": "immigration",
        "question": "Une amende migratoire impayée bloque-t-elle ma demande de résidence ?",
        "answer": "Oui : la tramitação de la demande d'autorisation de résidence est conditionnée au paiement des amendes appliquées sur le fondement du décret.",
        "refs": [("decreto_9199_2017", "129", ["§ 3º A tramitação de pedido de autorização de residência"])],
    },
    {
        "id": "brx-06",
        "theme": "immigration",
        "question": "Peut-on obtenir la résidence même en situation irrégulière ?",
        "answer": "Oui : l'autorisation de résidence peut être accordée indépendamment de la situation migratoire.",
        "refs": [("lei_13445_2017", "31", ["§ 5º Poderá ser concedida autorização de residência independentemente"])],
    },
    {
        "id": "brx-07",
        "theme": "immigration",
        "question": "Un visiteur a-t-il le droit d'être rémunéré par une source brésilienne ?",
        "answer": "Non : il est interdit au titulaire d'un visto de visita d'exercer une activité rémunérée au Brésil ; il peut seulement recevoir des diárias, ajudas de custo, cachets ou le remboursement de frais de voyage, et des prix.",
        "refs": [
            (
                "lei_13445_2017",
                "13",
                [
                    "§ 1º É vedado ao beneficiário de visto de visita exercer atividade remunerada",
                    "§ 2º O beneficiário de visto de visita poderá receber pagamento",
                ],
            )
        ],
    },
    {
        "id": "brx-08",
        "theme": "immigration",
        "question": "Sur quelle base demander une résidence pour rejoindre une compagne brésilienne ?",
        "answer": "La réunion familiale : le visa ou l'autorisation de résidence pour reunião familiar est accordé au conjoint ou compagnon (companheiro, union stable comprise), sans discrimination.",
        "refs": [
            ("lei_13445_2017", "37", ["I - cônjuge ou companheiro, sem discriminação alguma"]),
            ("decreto_9199_2017", "153", ["I - cônjuge ou companheiro, sem discriminação alguma"]),
        ],
    },
    {
        "id": "brx-09",
        "theme": "immigration",
        "question": "Qu'est-ce qui caractérise une union stable ?",
        "answer": "L'união estável est la convivência publique, continue et durable, établie avec l'objectif de constituer une famille.",
        "refs": [("lei_10406_2002", "1.723", ["configurada na convivência pública, contínua e duradoura"])],
    },
    {
        "id": "brx-10",
        "theme": "immigration",
        "question": "Dans quelle unité de la Polícia Federal dois-je déposer ma demande ?",
        "answer": "Pour un résident autorisé sur une autre base que le travail maritime : l'unité de la Polícia Federal de la circonscription de son domicile ; la PF peut, par décision motivée et exceptionnellement, accepter une autre unité.",
        "refs": [
            (
                "decreto_9199_2017",
                "67",
                [
                    "II - na unidade da Polícia Federal em que haja atendimento a imigrantes da circunscrição",
                    "§ 2º A Polícia Federal poderá, por meio de requerimento e decisão fundamentada",
                ],
            )
        ],
    },
    {
        "id": "brx-11",
        "theme": "immigration",
        "question": "Comment prouver mon adresse si le bail n'est pas à mon nom ?",
        "answer": "Par une déclaration signée par l'intéressé, sous les peines de la loi : elle est présumée vraie pour prouver la résidence.",
        "refs": [("lei_7115_1983", "1", ["A declaração destinada a fazer prova de vida, residência"])],
    },
    # Société (lucro presumido) et impôts
    {
        "id": "brx-12",
        "theme": "company_tax",
        "question": "Quel pourcentage du chiffre d'affaires sert de base à l'IRPJ pour une société de services en lucro presumido ?",
        "answer": "32 % de la receita bruta pour la prestation de services en général (au lieu de 8 % dans le cas général).",
        "refs": [
            (
                "lei_9249_1995",
                "15",
                ["III - trinta e dois por cento, para as atividades de", "a) prestação de serviços em geral"],
            ),
            # The IN restates the rates (art. 33) and applies them to lucro presumido (art. 215).
            ("in_rfb_1700_2017", "33", ["IV - 32% (trinta e dois por cento) sobre a receita bruta auferida"]),
            ("in_rfb_1700_2017", "215", ["O lucro presumido será determinado mediante aplicação dos percentuais"]),
        ],
    },
    {
        "id": "brx-13",
        "theme": "company_tax",
        "question": "Quel pourcentage du chiffre d'affaires sert de base à la CSLL pour une société de services en lucro presumido ?",
        "answer": "32 % de la receita bruta pour les activités de services visées à l'art. 15 §1º, III (12 % pour les autres recettes).",
        "refs": [
            (
                "lei_9249_1995",
                "20",
                ["I - 32% (trinta e dois por cento) para a receita bruta decorrente das atividades"],
            ),
            ("in_rfb_1700_2017", "34", ["§ 1º O percentual de que trata o caput será de 32%"]),
        ],
    },
    {
        "id": "brx-14",
        "theme": "company_tax",
        "question": "À partir de quel montant s'applique l'adicional de 10 % d'IRPJ ?",
        "answer": "Sur la part du lucro (réel, presumido ou arbitrado) qui dépasse R$ 20 000 multipliés par le nombre de mois de la période, soit R$ 60 000 par trimestre.",
        "refs": [
            ("lei_9249_1995", "3", ["§ 1º A parcela do lucro real, presumido ou arbitrado, que exceder"]),
            ("lei_9430_1996", "4", ["§ 1º A parcela do lucro real, presumido ou arbitrado, que exceder"]),
            ("in_rfb_1700_2017", "29", ["§ 1º A parcela do lucro real, presumido ou arbitrado que exceder"]),
        ],
    },
    {
        "id": "brx-15",
        "theme": "company_tax",
        "question": "L'IRPJ du lucro presumido se paie-t-il au mois ou au trimestre ?",
        "answer": "Au trimestre (périodes closes au 31 mars, 30 juin, 30 septembre et 31 décembre), en quota unique le mois suivant ou, au choix, en trois quotas mensuelles.",
        "refs": [
            ("lei_9430_1996", "1", ["por períodos de apuração trimestrais"]),
            ("in_rfb_1700_2017", "31", ["serão determinadas em períodos de apuração trimestrais"]),
            (
                "lei_9430_1996",
                "5",
                ["§ 1º À opção da pessoa jurídica, o imposto devido poderá ser pago em até três quotas"],
            ),
        ],
    },
    {
        "id": "brx-16",
        "theme": "company_tax",
        "question": "Une société peut-elle être imposée sur l'encaissement plutôt que sur la facturation ?",
        "answer": "Oui : la société au lucro presumido peut reconnaître ses recettes à la mesure de leur encaissement (regime de caixa), à condition de tenir le livre Caixa en indiquant pour chaque encaissement la nota fiscal correspondante.",
        "refs": [
            (
                "in_rfb_1700_2017",
                "223",
                ["adotar o critério de reconhecimento de suas receitas na medida do recebimento"],
            )
        ],
    },
    {
        "id": "brx-17",
        "theme": "company_tax",
        "question": "L'ISS est-il dû sur un service rendu à un client à l'étranger ?",
        "answer": "Non : l'ISS ne frappe pas les exportations de services, sauf si le service est développé au Brésil et que son résultat s'y vérifie, même payé par un non-résident.",
        "refs": [
            (
                "lc_116_2003",
                "2",
                [
                    "I – as exportações de serviços para o exterior do País",
                    "Parágrafo único. Não se enquadram no disposto no inciso I",
                ],
            )
        ],
    },
    {
        "id": "brx-18",
        "theme": "company_tax",
        "question": "PIS et COFINS sont-ils dus sur une facture à un client français payée en euros ?",
        "answer": "Non : PIS/Pasep et Cofins ne frappent pas les recettes de services rendus à une personne résidente ou domiciliée à l'étranger dont le paiement représente une entrée de devises.",
        "refs": [
            (
                "lei_10833_2003",
                "6",
                ["II - prestação de serviços para pessoa física ou jurídica residente ou domiciliada no exterior"],
            ),
            (
                "lei_10637_2002",
                "5",
                ["II - prestação de serviços para pessoa física ou jurídica residente ou domiciliada no exterior"],
            ),
        ],
    },
    {
        "id": "brx-19",
        "theme": "company_tax",
        "question": "Les dividendes (lucros) versés à l'associé sont-ils imposés ?",
        "answer": "En principe non (art. 10 de la Lei 9.249), mais depuis janvier 2026 une retenue de 10 % s'applique au-delà de R$ 50 000 par mois versés par une même société à une même personne physique résidente, et les dividendes envoyés à l'étranger subissent une retenue de 10 %.",
        "refs": [
            (
                "lei_9249_1995",
                "10",
                [
                    "não ficarão sujeitos à incidência do imposto de renda na fonte",
                    "§ 4º Os lucros ou dividendos pagos, creditados, entregues, empregados ou remetidos ao exterior",
                ],
            ),
            ("lei_15270_2025", "6-A", ["em montante superior a R$ 50.000,00 (cinquenta mil reais) em um mesmo mês"]),
            # The new wording of Lei 9.249 art. 10, quoted in the amending law.
            ("lei_15270_2025", "“Art. 10.", ["não ficarão sujeitos à incidência do imposto"]),
        ],
    },
    {
        "id": "brx-20",
        "theme": "company_tax",
        "question": "Puis-je opter pour le Simples Nacional, et à quelle date ?",
        "answer": "L'option se fait en janvier, jusqu'au dernier jour ouvré, avec effet au 1er janvier, et elle est irrévocable pour toute l'année (sauf début d'activité).",
        "refs": [
            (
                "lc_123_2006",
                "16",
                [
                    "sendo irretratável para todo o ano-calendário",
                    "§ 2º A opção de que trata o caput deste artigo deverá ser realizada no mês de janeiro",
                ],
            )
        ],
    },
    # INSS, retraite, fiscalité personnelle
    {
        "id": "brx-21",
        "theme": "inss_personal_tax",
        "question": "Le pró-labore d'un associé est-il soumis à l'INSS ?",
        "answer": "Oui : l'associé rémunéré pour son travail est assuré obligatoire comme contribuinte individual ; la société retient la cotisation sur sa rémunération et la reverse. Le taux est de 20 %, diminué de la déduction de 45 % de la part patronale plafonnée à 9 %, soit 11 % retenus.",
        "refs": [
            (
                "lei_8212_1991",
                "12",
                ["o sócio gerente e o sócio cotista que recebam remuneração decorrente de seu trabalho"],
            ),
            (
                "lei_10666_2003",
                "4",
                ["Fica a empresa obrigada a arrecadar a contribuição do segurado contribuinte individual"],
            ),
            (
                "lei_8212_1991",
                "21",
                [
                    "A alíquota de contribuição dos segurados contribuinte individual e facultativo será de vinte por cento"
                ],
            ),
            (
                "lei_8212_1991",
                "30",
                ["§ 4o Na hipótese de o contribuinte individual prestar serviço a uma ou mais empresas"],
            ),
        ],
    },
    {
        "id": "brx-22",
        "theme": "inss_personal_tax",
        "question": "Quelle part la société paie-t-elle en plus sur le pró-labore ?",
        "answer": "20 % des rémunérations versées aux contribuintes individuais qui lui rendent des services (hors Simples Nacional).",
        "refs": [("lei_8212_1991", "22", ["III - vinte por cento sobre o total das remunerações pagas ou creditadas"])],
    },
    {
        "id": "brx-23",
        "theme": "inss_personal_tax",
        "question": "À quel âge et après combien d'années peut-on toucher la retraite INSS ?",
        "answer": "Pour un assuré affilié après la réforme : 65 ans et 20 ans de cotisation pour un homme, 62 ans et 15 ans pour une femme.",
        "refs": [("ec_103_2019", "19", ["será aposentado aos 62 (sessenta e dois) anos de idade, se mulher, 65"])],
    },
    {
        "id": "brx-24",
        "theme": "inss_personal_tax",
        "question": "Comment est calculé le montant de la retraite INSS ?",
        "answer": "60 % de la moyenne arithmétique simple de tous les salaires de cotisation, plus 2 points par année de cotisation au-delà de 20 ans.",
        "refs": [
            (
                "ec_103_2019",
                "26",
                [
                    "será utilizada a média aritmética simples dos salários de contribuição",
                    "§ 2º O valor do benefício de aposentadoria corresponderá a 60%",
                ],
            )
        ],
    },
    {
        "id": "brx-25",
        "theme": "inss_personal_tax",
        "question": "Mes années de travail en France comptent-elles pour la retraite brésilienne ?",
        "answer": "Oui, grâce à l'accord France-Brésil : les périodes d'assurance des deux pays sont totalisées pour ouvrir le droit, puis chaque pays paie une part au prorata des périodes accomplies chez lui.",
        "refs": [
            (
                "decreto_8300_2014",
                "Artigo 16",
                ["1. Quando houverem transcorrido períodos de seguro nos termos das legislações de ambas"],
            ),
            (
                "decreto_8300_2014",
                "Artigo 19",
                ["um coeficiente igual à relação entre a duração dos períodos de seguro"],
            ),
        ],
    },
    {
        "id": "brx-26",
        "theme": "inss_personal_tax",
        "question": "À partir de quand devient-on résident fiscal au Brésil ?",
        "answer": "Dès l'arrivée avec un visa permanent (autorisation de résidence) ou un contrat de travail ; avec un visa temporaire, au 184e jour de présence, consécutif ou non, sur une période de 12 mois, ou à l'obtention du visa permanent ou du contrat de travail si elle a lieu avant.",
        "refs": [
            (
                "in_srf_208_2002",
                "2",
                ["2. na data em que complete 184 dias", "3. na data da obtenção de visto permanente"],
            )
        ],
    },
    {
        "id": "brx-27",
        "theme": "inss_personal_tax",
        "question": "Comment sont imposés mes livrets et mon PEA en France une fois résident brésilien ?",
        "answer": "Comme aplicações financeiras no exterior : leurs revenus sont déclarés à part dans la déclaration annuelle (DAA) et imposés à 15 %, sans déduction.",
        "refs": [
            (
                "lei_14754_2023",
                "2",
                [
                    "§ 1º Os rendimentos de que trata o caput deste artigo ficarão sujeitos à incidência do Imposto sobre a Renda das Pessoas Físicas (IRPF), no ajuste anual, à alíquota de 15%"
                ],
            ),
            (
                "lei_14754_2023",
                "3",
                [
                    "Os rendimentos auferidos em aplicações financeiras no exterior pelas pessoas físicas residentes no País serão tributados"
                ],
            ),
        ],
    },
    {
        "id": "brx-28",
        "theme": "inss_personal_tax",
        "question": "Quel IOF sur un virement de reais vers mon compte en France ?",
        "answer": "Selon la finalité : 1,10 % pour un transfert d'un résident à des fins d'investissement, 3,5 % pour la mise à disposition (disponibilidade) de fonds à l'étranger ; ces taux ont été modifiés en 2025 et changent souvent.",
        "refs": [
            (
                "decreto_6306_2007",
                "15-B",
                [
                    "XXI - nas liquidações de operações de câmbio para transferência de recursos ao exterior, com vistas à colocação de disponibilidade",
                    "XXI-A - nas liquidações de operações de câmbio para transferência de recursos ao exterior",
                ],
            )
        ],
    },
    # Pièges
    {
        "id": "brx-29",
        "theme": "trap",
        "question": "Un Français peut-il prolonger son séjour de visiteur au-delà de 90 jours ?",
        "answer": "Les documents ne permettent pas de trancher : le Decreto 9.199, art. 20 §2º, ne permet la prorrogation qu'aux ressortissants des pays qui assurent la réciprocité aux Brésiliens, mais la liste de ces pays (le QGRV du ministère des Relations extérieures) n'est pas dans les documents. Il ne faut pas répondre simplement oui.",
        "refs": [("decreto_9199_2017", "20", ["§ 2º A prorrogação do prazo de estada"])],
        "expected_behaviour": "cite_and_flag_missing",
    },
    {
        "id": "brx-30",
        "theme": "trap",
        "question": "Quel est le taux du Livret A ?",
        "answer": "Je ne trouve pas cette information dans les documents.",
        "refs": [],
        "expected_behaviour": "abstain",
    },
    # Paraphrases familières (question type of their own)
    {
        "id": "brx-p07",
        "theme": "paraphrase",
        "source": "brx-07",
        "question": "je peux bosser payé au Brésil avec mon visa touriste ?",
    },
    {
        "id": "brx-p01",
        "theme": "paraphrase",
        "source": "brx-01",
        "question": "je peux rester combien de temps au Brésil en touriste, et ça se rallonge ?",
    },
    {
        "id": "brx-p11",
        "theme": "paraphrase",
        "source": "brx-11",
        "question": "mon nom est pas sur le bail, comment je prouve où j'habite ?",
    },
    {
        "id": "brx-p12",
        "theme": "paraphrase",
        "source": "brx-12",
        "question": "ma boîte fait de la presta en lucro presumido, l'impôt sur les bénéfices est calculé sur quelle part de ce que je facture ?",
    },
    {
        "id": "brx-p17",
        "theme": "paraphrase",
        "source": "brx-17",
        "question": "je facture un client en France depuis le Brésil, je dois payer l'ISS ?",
    },
    {
        "id": "brx-p19",
        "theme": "paraphrase",
        "source": "brx-19",
        "question": "si je me verse des dividendes de ma boîte, je paie de l'impôt dessus ?",
    },
    {
        "id": "brx-p23",
        "theme": "paraphrase",
        "source": "brx-23",
        "question": "la retraite au Brésil c'est à quel âge, faut avoir cotisé combien ?",
    },
    {
        "id": "brx-p26",
        "theme": "paraphrase",
        "source": "brx-26",
        "question": "au bout de combien de temps au Brésil je deviens résident fiscal là-bas ?",
    },
]

_NEXT_ARTICLE = re.compile(r"\n(?:Art\.\s*\.?\s*\d|Artigo\s+\d)")
_NEXT_QUOTED_ARTICLE = re.compile(r"\n“?Art\.\s*\d")


def article_span(text: str, article: str, anchor: str | None = None) -> tuple[int, int]:
    """Offsets of an article: its heading line to the next article heading.

    The first heading whose article contains `anchor` wins (an amending law
    can quote the same article number of several laws)."""
    following_re = _NEXT_ARTICLE
    if article.startswith("Artigo "):
        heading = re.compile(rf"(?:^|\n)Artigo\s+{re.escape(article.split()[1])}\s*\n")
    elif article.startswith("“"):
        # New wording quoted inside an amending law ("“Art. 10. ..."), up
        # to the next article, quoted or not.
        heading = re.compile(rf"(?:^|\n){re.escape(article)}\s")
        following_re = _NEXT_QUOTED_ARTICLE
    else:
        number, _, letter = article.partition("-")
        suffix = rf"\s*[º°o]?\s*-\s*{letter}" if letter else ""
        heading = re.compile(rf"(?:^|\n)Art\.\s*\.?\s*{re.escape(number)}{suffix}\s*(?:[º°o]|\.|\s)(?![\d-])")
    for match in heading.finditer(text):
        start = match.start() + (1 if text[match.start()] == "\n" else 0)
        following = following_re.search(text, match.end())
        end = following.start() if following else len(text)
        if anchor is None or anchor in text[start:end]:
            return start, end
    raise ValueError(f"article {article} not found")


def line_span(text: str, start: int, end: int, anchor: str) -> tuple[int, int]:
    """Offsets of the line(s) of the article that contain `anchor`."""
    position = text.find(anchor, start, end)
    if position < 0:
        raise ValueError(f"anchor not found: {anchor!r}")
    line_start = max(start, text.rfind("\n", start, position) + 1)
    line_end = text.find("\n", position + len(anchor))
    return line_start, min(end, line_end if line_end >= 0 else len(text))


def build(corpus_dir: Path) -> list[dict[str, Any]]:
    texts: dict[str, str] = {}

    def text_of(stem: str) -> str:
        if stem not in texts:
            texts[stem] = (corpus_dir / f"{stem}.txt").read_text(encoding="utf-8")
        return texts[stem]

    by_id = {row["id"]: row for row in QUESTIONS}
    rows = []
    for row in QUESTIONS:
        base = by_id[row["source"]] if "source" in row else row
        expected, provisions, references = [], [], []
        for stem, article, anchors in base["refs"]:
            text = text_of(stem)
            start, end = article_span(text, article, anchors[0] if anchors else None)
            file_name = f"{stem}.txt"
            if not any(span["file_name"] == file_name and span["start"] == start for span in expected):
                expected.append({"file_name": file_name, "start": start, "end": end, "text": text[start:end]})
            for anchor in anchors:
                p_start, p_end = line_span(text, start, end, anchor)
                provisions.append({"file_name": file_name, "start": p_start, "end": p_end, "text": text[p_start:p_end]})
            references.append(f"{stem} art. {article}")
        rows.append(
            {
                "id": row["id"],
                "question": row["question"],
                "expected_file_names": sorted({span["file_name"] for span in expected}),
                "ground_truth_answer": base["answer"],
                "expected_spans": expected,
                "question_type": row["theme"],
                "context": {
                    "theme_label": THEMES[row["theme"]],
                    "references": references,
                    "provision_spans": provisions,
                    "question_language": "fr",
                    "passage_language": "pt",
                    **({"paraphrase_of": row["source"]} if "source" in row else {}),
                    **({"expected_behaviour": base["expected_behaviour"]} if "expected_behaviour" in base else {}),
                },
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--corpus", type=Path, default=Path("data/lexml/br_expat/corpus"))
    parser.add_argument("--output", type=Path, default=Path("benchmarks/br_expat/ground_truth.jsonl"))
    args = parser.parse_args()
    rows = build(args.corpus)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"{len(rows)} questions -> {args.output}")


if __name__ == "__main__":
    main()
