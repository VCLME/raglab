// Example questions shown under the Chat composer, per corpus and per UI
// language. Hand-written situations, not copied from the frozen benchmark
// sets: someone who does not know the law can still click one and see the
// pipeline at work. Every question is answered by a passage of its corpus
// (checked with retrieval). The Brazilian corpus keeps French and English
// questions on purpose: retrieval is multilingual. The Brazil expat corpus is
// the exception: its examples are real questions of its frozen set, in every
// language with the article in the top 5 of the default pipeline.

export type ExampleLanguage = "fr" | "en" | "pt";

const LEGI_CONSOMMATION: Record<ExampleLanguage, string[]> = {
  fr: [
    "J'ai acheté un aspirateur en ligne il y a dix jours. Puis-je encore le renvoyer sans donner de raison ?",
    "Mon téléphone tombe en panne au bout de huit mois. Le vendeur peut-il refuser de le réparer ?",
    "La garantie de conformité s'applique-t-elle à l'achat d'un chiot ?",
    "Un fabricant a-t-il le droit de réduire exprès la durée de vie d'un appareil pour pousser à en racheter un ?",
  ],
  en: [
    "I bought something online ten days ago. How long is the withdrawal period for a distance contract?",
    "My phone broke down after eight months. Can the seller refuse to repair it?",
    "Does the legal guarantee of conformity apply to the sale of domestic animals?",
    "My smartphone has slowed down since an update. Is the manufacturer allowed to do that?",
  ],
  pt: [
    "Comprei um produto pela internet há dez dias. Qual é o prazo de retratação de um contrato à distância?",
    "Meu celular quebrou depois de oito meses. O vendedor pode se recusar a consertá-lo?",
    "Quanto tempo dura a garantia legal de conformidade de um produto novo?",
    "Meu smartphone ficou lento depois de uma atualização. O fabricante pode fazer isso?",
  ],
};

const LEXML: Record<ExampleLanguage, string[]> = {
  fr: [
    "Quel organisme coordonne la politique nationale de l'environnement au Brésil ?",
    "Que prévoit la loi brésilienne sur l'éducation à l'environnement ?",
    "Je suis au Brésil avec un visa touriste. Ai-je le droit d'être payé par une entreprise brésilienne ?",
    "Peut-on obtenir un titre de séjour au Brésil même en situation irrégulière ?",
  ],
  en: [
    "Which body coordinates Brazil's national environmental policy?",
    "What does Brazilian law provide for environmental education?",
    "I am in Brazil on a tourist visa. Can a Brazilian company pay me?",
    "Can I get a residence permit in Brazil if my stay is irregular?",
  ],
  pt: [
    "Qual órgão coordena a política nacional do meio ambiente?",
    "O que a lei prevê para a educação ambiental?",
    "Estou no Brasil com visto de turista. Posso ser pago por uma empresa brasileira?",
    "Dá para conseguir autorização de residência mesmo em situação migratória irregular?",
  ],
};

const BR_EXPAT: Record<ExampleLanguage, string[]> = {
  fr: [
    "Je suis au Brésil avec un visa touriste. Ai-je le droit d'être payé par une entreprise brésilienne ?",
    "La prolongation du séjour visiteur est-elle possible pour tous les pays ?",
    "À partir de quel montant s'applique l'adicional de 10 % d'IRPJ ?",
    "Si je me verse des dividendes de ma société, est-ce que je paie de l'impôt dessus ?",
  ],
  en: [
    "I am in Brazil on a tourist visa. Can a Brazilian company pay me?",
    "Can a visitor's stay in Brazil be extended for nationals of every country?",
    "Above what amount does the 10% IRPJ surcharge apply?",
    "If I pay myself dividends from my company, are they taxed?",
  ],
  pt: [
    "Estou no Brasil com visto de turista. Posso ser pago por uma empresa brasileira?",
    "A prorrogação do prazo de estada do visto de visita vale para nacionais de qualquer país?",
    "A partir de qual valor incide o adicional de 10% do IRPJ?",
    "Se eu distribuir lucros da minha empresa para mim, pago imposto?",
  ],
};

const EURLEX: Record<ExampleLanguage, string[]> = {
  fr: [
    "Nous venons de découvrir une fuite de données clients. Sous quel délai faut-il prévenir l'autorité de contrôle ?",
    "Nous testons un système d'IA en conditions réelles. Combien de temps le test peut-il durer ?",
    "Deux entreprises traitent ensemble les mêmes données clients. Comment répartir leurs responsabilités ?",
    "Notre banque a subi un incident informatique majeur. Que doit contenir le rapport à l'autorité ?",
  ],
  en: [
    "We just found a leak of customer data. How soon must we notify the supervisory authority?",
    "We are testing an AI system in real-world conditions. How long can the test last?",
    "Two companies process the same customer data together. How should they split their responsibilities?",
    "Our bank suffered a major ICT incident. What must the report to the authority contain?",
  ],
  pt: [
    "Acabamos de descobrir uma fuga de dados de clientes. Em que prazo devemos notificar a autoridade de controlo?",
    "Estamos a testar um sistema de IA em condições reais. Quanto tempo pode durar o teste?",
    "Duas empresas tratam em conjunto os mesmos dados de clientes. Como devem repartir as responsabilidades?",
    "O nosso banco sofreu um incidente informático grave. O que deve conter o relatório à autoridade?",
  ],
};

const PIAF: Record<ExampleLanguage, string[]> = {
  fr: [
    "Que mange le rhinocéros noir ?",
    "Combien de personnes parlent albanais ?",
    "Combien de buts Giuseppe Meazza a-t-il marqués lors de sa première saison à l'Inter ?",
    "Combien d'élèves l'École nationale de l'aviation civile forme-t-elle chaque année ?",
  ],
  en: [
    "What does the black rhinoceros eat?",
    "How many people speak Albanian?",
    "How many goals did Giuseppe Meazza score in his first season at Inter?",
    "How many students does the French civil aviation school train each year?",
  ],
  pt: [
    "O que come o rinoceronte-negro?",
    "Quantas pessoas falam albanês?",
    "Quantos gols Giuseppe Meazza marcou na primeira temporada pela Inter?",
    "Quantos alunos a escola nacional de aviação civil francesa forma por ano?",
  ],
};

const BY_CORPUS: Record<string, Record<ExampleLanguage, string[]>> = {
  bench_legi_consommation_fr: LEGI_CONSOMMATION,
  bench_lexml_pt: LEXML,
  lexml_real: LEXML,
  bench_br_expat_pt: BR_EXPAT,
  bench_eurlex_compliance: EURLEX,
  bench_piaf_fr: PIAF,
  piaf_fr: PIAF,
};

export function exampleLanguage(uiLanguage: string): ExampleLanguage {
  if (uiLanguage.startsWith("pt")) return "pt";
  if (uiLanguage.startsWith("en")) return "en";
  return "fr";
}

/** Hand-written examples for this corpus, or null when it has none. */
export function exampleQuestions(corpus: string, uiLanguage: string): string[] | null {
  return BY_CORPUS[corpus]?.[exampleLanguage(uiLanguage)] ?? null;
}
