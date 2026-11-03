/**
 * Real retrieval-side stream of a cross-reference question on the LexML index
 * (hybrid + citations + graph, no re-ranking), recorded from the pipeline with
 * `QueryService.pipeline_events`; the learning-mode tests replay it.
 */
export const recorded = {
  "question": "Qual prazo de universalização se exige na comprovação de capacidade econômico-financeira prevista no art. 10-B da Lei nº 11.445?",
  "events": [
    [
      "pipeline",
      {
        "stages": [
          "embed",
          "retrieval",
          "lexical",
          "graph",
          "fusion",
          "prompt",
          "generation"
        ]
      }
    ],
    [
      "stage",
      {
        "stage": "embed",
        "status": "start",
        "t_ms": 0.0,
        "live": false
      }
    ],
    [
      "stage",
      {
        "stage": "embed",
        "status": "end",
        "t_ms": 19.083,
        "duration_ms": 19.083,
        "counts": {
          "dimension": 384
        },
        "data": {
          "dimension": 384,
          "head": [
            0.0256,
            -0.005,
            -0.0501,
            -0.0928,
            0.0562,
            -0.0415,
            0.0371,
            0.0539
          ],
          "norm": 1.0
        },
        "live": false
      }
    ],
    [
      "stage",
      {
        "stage": "retrieval",
        "status": "start",
        "t_ms": 19.083,
        "live": false
      }
    ],
    [
      "stage",
      {
        "stage": "retrieval",
        "status": "end",
        "t_ms": 77.891,
        "duration_ms": 58.808,
        "counts": {
          "chunks_out": 5,
          "top_k": 5
        },
        "data": {
          "top_chunks": [
            {
              "rank": 1,
              "file_name": "lei_11445_2007.txt",
              "excerpt": "(Incluído pela Lei nº 14.026, de 2020)\nArt. 10-B. Os contratos em vigor, incluídos aditivos e renovações, autorizados nos termos desta Lei, bem como aqueles pro",
              "score": 1.0,
              "citation_match": true
            },
            {
              "rank": 2,
              "file_name": "lei_11445_2007.txt",
              "excerpt": "(Incluído pela Lei nº 14.026, de 2020)\nArt. 11. São condições de validade dos contratos que tenham por objeto a prestação de serviços públicos de saneamento bás",
              "score": 1.0,
              "citation_match": true
            },
            {
              "rank": 3,
              "file_name": "lei_11445_2007.txt",
              "excerpt": "(Incluído pela Lei nº 14.026, de 2020)\n§ 7º Caso o contrato do prestador do serviço não tenha valor de contrato, o faturamento anual projetado para o subdelegat",
              "score": 1.0,
              "graph_score": 1.0,
              "graph_rank": 1,
              "graph_pinned": true
            },
            {
              "rank": 4,
              "file_name": "lei_11445_2007.txt",
              "excerpt": "(Incluído pela Lei nº 14.026, de 2020)\n§ 9º Quando os estudos para a licitação da prestação regionalizada apontarem para a inviabilidade econômico-financeira da",
              "score": 0.01562881562881563,
              "dense_score": 0.8705230951309204,
              "dense_rank": 5,
              "lexical_score": 19.91254186131548,
              "lexical_rank": 3,
              "fused_score": 0.01562881562881563,
              "fused_rank": 2
            },
            {
              "rank": 5,
              "file_name": "lei_11445_2007.txt",
              "excerpt": "A União elaborará, sob a coordenação do Ministério das Cidades: (Redação dada pela Lei nº 14.600, de 2023)\nI - o Plano Nacional de Saneamento Básico, que conter",
              "score": 0.01527518656716418,
              "dense_score": 0.8678181171417236,
              "dense_rank": 7,
              "lexical_score": 17.515710951268964,
              "lexical_rank": 4,
              "fused_score": 0.01527518656716418,
              "fused_rank": 4
            }
          ]
        },
        "live": false
      }
    ],
    [
      "stage",
      {
        "stage": "lexical",
        "status": "start",
        "t_ms": 77.891,
        "live": false
      }
    ],
    [
      "stage",
      {
        "stage": "lexical",
        "status": "end",
        "t_ms": 91.966,
        "duration_ms": 14.075,
        "counts": {
          "chunks_out": 5
        },
        "data": {
          "top_chunks": [
            {
              "rank": 1,
              "file_name": "lei_11445_2007.txt",
              "excerpt": "(Incluído pela Lei nº 14.026, de 2020)\nArt. 10-B. Os contratos em vigor, incluídos aditivos e renovações, autorizados nos termos desta Lei, bem como aqueles pro",
              "score": 1.0,
              "citation_match": true
            },
            {
              "rank": 2,
              "file_name": "lei_11445_2007.txt",
              "excerpt": "(Incluído pela Lei nº 14.026, de 2020)\nArt. 11. São condições de validade dos contratos que tenham por objeto a prestação de serviços públicos de saneamento bás",
              "score": 1.0,
              "citation_match": true
            },
            {
              "rank": 3,
              "file_name": "lei_11445_2007.txt",
              "excerpt": "(Incluído pela Lei nº 14.026, de 2020)\n§ 7º Caso o contrato do prestador do serviço não tenha valor de contrato, o faturamento anual projetado para o subdelegat",
              "score": 1.0,
              "graph_score": 1.0,
              "graph_rank": 1,
              "graph_pinned": true
            },
            {
              "rank": 4,
              "file_name": "lei_11445_2007.txt",
              "excerpt": "(Incluído pela Lei nº 14.026, de 2020)\n§ 9º Quando os estudos para a licitação da prestação regionalizada apontarem para a inviabilidade econômico-financeira da",
              "score": 0.01562881562881563,
              "dense_score": 0.8705230951309204,
              "dense_rank": 5,
              "lexical_score": 19.91254186131548,
              "lexical_rank": 3,
              "fused_score": 0.01562881562881563,
              "fused_rank": 2
            },
            {
              "rank": 5,
              "file_name": "lei_11445_2007.txt",
              "excerpt": "A União elaborará, sob a coordenação do Ministério das Cidades: (Redação dada pela Lei nº 14.600, de 2023)\nI - o Plano Nacional de Saneamento Básico, que conter",
              "score": 0.01527518656716418,
              "dense_score": 0.8678181171417236,
              "dense_rank": 7,
              "lexical_score": 17.515710951268964,
              "lexical_rank": 4,
              "fused_score": 0.01527518656716418,
              "fused_rank": 4
            }
          ]
        },
        "live": false
      }
    ],
    [
      "stage",
      {
        "stage": "graph",
        "status": "start",
        "t_ms": 91.966,
        "live": false
      }
    ],
    [
      "stage",
      {
        "stage": "graph",
        "status": "end",
        "t_ms": 100.216,
        "duration_ms": 8.25,
        "counts": {
          "seeds": 16,
          "articles": 4,
          "chunks": 8,
          "added": 2
        },
        "data": {
          "links": [
            {
              "from": "Art. 10-B — Lei nº 11.445/2007",
              "to": "Art. 11-B — Lei nº 11.445/2007",
              "snippet": "viabilizar a universalização dos serviços na área licitada até 31 de dezembro de 2033, nos termos do § 2º do art. 11-B desta Lei. (Redação dada pela Lei nº 14.026, de 2020) (Regulamento) (Regulamento) (Regulamento)",
              "chunks": 2,
              "added": 1
            },
            {
              "from": "Art. 50 — Lei nº 11.445/2007",
              "to": "Art. 3º — Lei nº 11.445/2007",
              "snippet": "VI - à regularidade da operação a ser financiada, nos termos do inciso XIII do caput do art. 3º desta Lei; (Incluído pela Lei nº 14.026, de 2020)",
              "chunks": 2,
              "added": 1
            },
            {
              "from": "Art. 50 — Lei nº 11.445/2007",
              "to": "Art. 48 — Lei nº 11.445/2007",
              "snippet": "por órgãos ou entidades da União serão feitos em conformidade com as diretrizes e objetivos estabelecidos nos arts. 48 e 49 desta Lei e com os planos de saneamento básico e condicionados:",
              "chunks": 2,
              "added": 0
            },
            {
              "from": "Art. 50 — Lei nº 11.445/2007",
              "to": "Art. 49 — Lei nº 11.445/2007",
              "snippet": "por órgãos ou entidades da União serão feitos em conformidade com as diretrizes e objetivos estabelecidos nos arts. 48 e 49 desta Lei e com os planos de saneamento básico e condicionados:",
              "chunks": 2,
              "added": 0
            }
          ],
          "top_chunks": [
            {
              "rank": 1,
              "file_name": "lei_11445_2007.txt",
              "excerpt": "(Incluído pela Lei nº 14.026, de 2020)\n§ 7º Caso o contrato do prestador do serviço não tenha valor de contrato, o faturamento anual projetado para o subdelegat",
              "score": 1.0,
              "graph_score": 1.0,
              "graph_rank": 1
            },
            {
              "rank": 2,
              "file_name": "lei_11445_2007.txt",
              "excerpt": "(Redação dada pela Lei nº 14.026, de 2020)\n§ 1º Os contratos em vigor que não possuírem as metas de que trata o caput deste artigo terão até 31 de março de 2022",
              "score": 0.5,
              "graph_score": 0.5,
              "graph_rank": 2
            },
            {
              "rank": 3,
              "file_name": "lei_11445_2007.txt",
              "excerpt": "3º Para fins do disposto nesta Lei, considera-se: (Redação dada pela Lei nº 14.026, de 2020)\nI - saneamento básico: conjunto de serviços públicos, infraestrutur",
              "score": 0.3333333333333333,
              "graph_score": 0.3333333333333333,
              "graph_rank": 3
            },
            {
              "rank": 4,
              "file_name": "lei_11445_2007.txt",
              "excerpt": "241 da Constituição Federal; (Redação dada pela Lei nº 14.026, de 2020)\nIII - universalização: ampliação progressiva do acesso de todos os domicílios ocupados a",
              "score": 0.25,
              "graph_score": 0.25,
              "graph_rank": 4
            },
            {
              "rank": 5,
              "file_name": "lei_11445_2007.txt",
              "excerpt": "A União, no estabelecimento de sua política de saneamento básico, observará as seguintes diretrizes:\nI - prioridade para as ações que promovam a eqüidade social",
              "score": 0.2,
              "graph_score": 0.2,
              "graph_rank": 5
            }
          ]
        },
        "live": false
      }
    ],
    [
      "stage",
      {
        "stage": "fusion",
        "status": "start",
        "t_ms": 100.216,
        "live": false
      }
    ],
    [
      "stage",
      {
        "stage": "fusion",
        "status": "end",
        "t_ms": 100.825,
        "duration_ms": 0.609,
        "counts": {
          "chunks_out": 5
        },
        "data": {
          "top_chunks": [
            {
              "rank": 1,
              "file_name": "lei_11445_2007.txt",
              "excerpt": "(Incluído pela Lei nº 14.026, de 2020)\nArt. 10-B. Os contratos em vigor, incluídos aditivos e renovações, autorizados nos termos desta Lei, bem como aqueles pro",
              "score": 1.0,
              "citation_match": true
            },
            {
              "rank": 2,
              "file_name": "lei_11445_2007.txt",
              "excerpt": "(Incluído pela Lei nº 14.026, de 2020)\nArt. 11. São condições de validade dos contratos que tenham por objeto a prestação de serviços públicos de saneamento bás",
              "score": 1.0,
              "citation_match": true
            },
            {
              "rank": 3,
              "file_name": "lei_11445_2007.txt",
              "excerpt": "(Incluído pela Lei nº 14.026, de 2020)\n§ 7º Caso o contrato do prestador do serviço não tenha valor de contrato, o faturamento anual projetado para o subdelegat",
              "score": 1.0,
              "graph_score": 1.0,
              "graph_rank": 1,
              "graph_pinned": true
            },
            {
              "rank": 4,
              "file_name": "lei_11445_2007.txt",
              "excerpt": "(Incluído pela Lei nº 14.026, de 2020)\n§ 9º Quando os estudos para a licitação da prestação regionalizada apontarem para a inviabilidade econômico-financeira da",
              "score": 0.01562881562881563,
              "dense_score": 0.8705230951309204,
              "dense_rank": 5,
              "lexical_score": 19.91254186131548,
              "lexical_rank": 3,
              "fused_score": 0.01562881562881563,
              "fused_rank": 2
            },
            {
              "rank": 5,
              "file_name": "lei_11445_2007.txt",
              "excerpt": "A União elaborará, sob a coordenação do Ministério das Cidades: (Redação dada pela Lei nº 14.600, de 2023)\nI - o Plano Nacional de Saneamento Básico, que conter",
              "score": 0.01527518656716418,
              "dense_score": 0.8678181171417236,
              "dense_rank": 7,
              "lexical_score": 17.515710951268964,
              "lexical_rank": 4,
              "fused_score": 0.01527518656716418,
              "fused_rank": 4
            }
          ]
        },
        "live": false
      }
    ]
  ],
  "retrieval": {
    "question": "Qual prazo de universalização se exige na comprovação de capacidade econômico-financeira prevista no art. 10-B da Lei nº 11.445?",
    "index_run_id": "3f1c9a52-7d4e-4b8a-9c21-5e6f7a8b9c0d",
    "strategy": "traditional",
    "retrieved_chunks": [
      {
        "chunk_id": "29e4362c-e552-46df-9926-3d66666b64b3",
        "document_id": "364ae647-8c89-4946-baa4-9ed6265219d7",
        "file_name": "lei_11445_2007.txt",
        "source_path": "lei_11445_2007.txt",
        "chunk_text": "(Incluído pela Lei nº 14.026, de 2020)\nArt. 10-B. Os contratos em vigor, incluídos aditivos e renovações, autorizados nos termos desta Lei, bem como aqueles provenientes de licitação para prestação ou concessão dos serviços públicos de saneamento básico, estarão condicionados à comprovação da capacidade econômico-financeira da contratada, por recursos próprios ou por contratação de dívida, com vis",
        "score": 1.0,
        "rank": 1,
        "char_start": 28065,
        "char_end": 28911,
        "dense_score": null,
        "dense_rank": null,
        "lexical_score": null,
        "lexical_rank": null,
        "fused_score": null,
        "fused_rank": null,
        "rerank_score": null,
        "rerank_rank": null,
        "citation_match": true,
        "graph_score": null,
        "graph_rank": null,
        "graph_reason": null,
        "graph_via": null,
        "graph_pinned": null
      },
      {
        "chunk_id": "ddae55b9-3434-4175-adfb-5f1a802b37e6",
        "document_id": "364ae647-8c89-4946-baa4-9ed6265219d7",
        "file_name": "lei_11445_2007.txt",
        "source_path": "lei_11445_2007.txt",
        "chunk_text": "(Incluído pela Lei nº 14.026, de 2020)\nArt. 11. São condições de validade dos contratos que tenham por objeto a prestação de serviços públicos de saneamento básico:\nI - a existência de plano de saneamento básico;\nII - a existência de estudo que comprove a viabilidade técnica e econômico-financeira da prestação dos serviços, nos termos estabelecidos no respectivo plano de saneamento básico; (Redaçã",
        "score": 1.0,
        "rank": 2,
        "char_start": 28864,
        "char_end": 29710,
        "dense_score": null,
        "dense_rank": null,
        "lexical_score": null,
        "lexical_rank": null,
        "fused_score": null,
        "fused_rank": null,
        "rerank_score": null,
        "rerank_rank": null,
        "citation_match": true,
        "graph_score": null,
        "graph_rank": null,
        "graph_reason": null,
        "graph_via": null,
        "graph_pinned": null
      },
      {
        "chunk_id": "8f5009dd-3bb8-469d-ac19-4ddf3498c6d1",
        "document_id": "364ae647-8c89-4946-baa4-9ed6265219d7",
        "file_name": "lei_11445_2007.txt",
        "source_path": "lei_11445_2007.txt",
        "chunk_text": "(Incluído pela Lei nº 14.026, de 2020)\n§ 7º Caso o contrato do prestador do serviço não tenha valor de contrato, o faturamento anual projetado para o subdelegatário não poderá ultrapassar 25% (vinte e cinco por cento) do faturamento anual projetado para o prestador do serviço. (Incluído pela Lei nº 14.026, de 2020)\n(Vigência encerrada)\n(Vigência encerrada)\n(Vigência encerrada)\n(Vigência encerrada)",
        "score": 1.0,
        "rank": 3,
        "char_start": 33907,
        "char_end": 34758,
        "dense_score": null,
        "dense_rank": null,
        "lexical_score": null,
        "lexical_rank": null,
        "fused_score": null,
        "fused_rank": null,
        "rerank_score": null,
        "rerank_rank": null,
        "citation_match": null,
        "graph_score": 1.0,
        "graph_rank": 1,
        "graph_reason": "cité par l'art. 10-b de la Lei nº 11.445/2007",
        "graph_via": "Art. 10-B — Lei nº 11.445/2007",
        "graph_pinned": true
      },
      {
        "chunk_id": "8eb0229e-4cfe-4e6d-8d49-4766099ddccf",
        "document_id": "364ae647-8c89-4946-baa4-9ed6265219d7",
        "file_name": "lei_11445_2007.txt",
        "source_path": "lei_11445_2007.txt",
        "chunk_text": "(Incluído pela Lei nº 14.026, de 2020)\n§ 9º Quando os estudos para a licitação da prestação regionalizada apontarem para a inviabilidade econômico-financeira da universalização na data referida no caput deste artigo, mesmo após o agrupamento de Municípios de diferentes portes, fica permitida a dilação do prazo, desde que não ultrapasse 1º de janeiro de 2040 e haja anuência prévia da agência regula",
        "score": 0.01562881562881563,
        "rank": 4,
        "char_start": 37876,
        "char_end": 38653,
        "dense_score": 0.8705230951309204,
        "dense_rank": 5,
        "lexical_score": 19.91254186131548,
        "lexical_rank": 3,
        "fused_score": 0.01562881562881563,
        "fused_rank": 2,
        "rerank_score": null,
        "rerank_rank": null,
        "citation_match": null,
        "graph_score": null,
        "graph_rank": null,
        "graph_reason": null,
        "graph_via": null,
        "graph_pinned": null
      },
      {
        "chunk_id": "ba6ce7c5-d19e-4441-ae2e-f235e589e0ad",
        "document_id": "364ae647-8c89-4946-baa4-9ed6265219d7",
        "file_name": "lei_11445_2007.txt",
        "source_path": "lei_11445_2007.txt",
        "chunk_text": "A União elaborará, sob a coordenação do Ministério das Cidades: (Redação dada pela Lei nº 14.600, de 2023)\nI - o Plano Nacional de Saneamento Básico, que conterá: (Redação dada pela Lei nº 14.026, de 2020)\na) os objetivos e metas nacionais e regionalizadas, de curto, médio e longo prazos, para a universalização dos serviços de saneamento básico e o alcance de níveis crescentes de saneamento básico",
        "score": 0.01527518656716418,
        "rank": 5,
        "char_start": 92738,
        "char_end": 94303,
        "dense_score": 0.8678181171417236,
        "dense_rank": 7,
        "lexical_score": 17.515710951268964,
        "lexical_rank": 4,
        "fused_score": 0.01527518656716418,
        "fused_rank": 4,
        "rerank_score": null,
        "rerank_rank": null,
        "citation_match": null,
        "graph_score": null,
        "graph_rank": null,
        "graph_reason": null,
        "graph_via": null,
        "graph_pinned": null
      }
    ],
    "retrieval_mode": "hybrid",
    "citation": {
      "label": "art. 10-B — Lei nº 11445",
      "law_number": "11445",
      "article": "10-B",
      "law_found": true,
      "article_found": true
    },
    "query_lexemes": [
      "10",
      "11.445",
      "art",
      "b",
      "capac",
      "comprovaca",
      "econom",
      "economico-financeir",
      "exig",
      "financeir",
      "lei",
      "nº",
      "praz",
      "previst",
      "universalizaca"
    ],
    "rerank": false,
    "rerank_stats": {},
    "rerank_notice": null,
    "graph": true,
    "graph_notice": null,
    "graph_stats": {
      "seeds": 16,
      "articles": 4,
      "chunks": 8,
      "added": 2
    },
    "filters": {
      "document_ids": [
        "364ae647-8c89-4946-baa4-9ed6265219d7"
      ],
      "file_names": [],
      "source_path_contains": null,
      "tags": [],
      "metadata_equals": {}
    },
    "answer": null,
    "elapsed_ms": 0.0,
    "timings_ms": {
      "embed": 19.083,
      "retrieval": 88.652,
      "citation": 6.852,
      "dense": 58.808,
      "lexical": 14.075,
      "graph": 8.25,
      "fusion": 0.609
    },
    "generation_stats": {}
  }
};
