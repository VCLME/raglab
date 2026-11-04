import { useTranslation } from "react-i18next";
import type { RoutingDecision } from "../api/types";
import { StatusBadge } from "./StatusBadge";

interface Props {
  routing: RoutingDecision;
  // Expert view: every score the router decided on, plus its timings.
  detailed?: boolean;
}

function fmt(value: number | null | undefined, digits = 3): string {
  return value == null ? "—" : value.toFixed(digits);
}

export function RoutingPanel({ routing, detailed = false }: Props) {
  const { t } = useTranslation();
  const { language, intent, corpus, abstention } = routing;
  const declined = !routing.answer_from_documents;

  return (
    <div className="routing-panel">
      <div className="routing-summary">
        <span>
          {t("routing.language")} <code>{language.language}</code>
        </span>
        <span>
          {t("routing.intent")} <code>{t(`routing.intents.${intent.intent}`)}</code>
        </span>
        <span>
          {t("routing.corpus")} <code>{corpus.corpus_name ?? "—"}</code>
          {corpus.source === "requested" && corpus.suggested_corpus !== corpus.corpus_name ? (
            <span className="muted">
              {" "}
              {t("routing.suggested", { corpus: corpus.suggested_corpus ?? "—" })}
            </span>
          ) : null}
        </span>
        <StatusBadge
          state={declined ? "warn" : "ok"}
          label={
            declined
              ? t("routing.declined", {
                  reason: t(`routing.reasons.${(abstention?.reason ?? "").split(":")[0] || "none"}`),
                })
              : t("routing.answered")
          }
        />
        {abstention?.override === "legal_citation" ? (
          <span className="muted">
            {t("routing.citation_override", { label: routing.legal_citation ?? "" })}
          </span>
        ) : null}
      </div>

      {detailed ? (
        <table className="table routing-scores">
          <tbody>
            <tr>
              <th>{t("routing.language")}</th>
              <td>
                {Object.entries(language.scores)
                  .map(([k, v]) => `${k} ${fmt(v, 2)}`)
                  .join(" · ")}{" "}
                <span className="muted">({t(`routing.methods.${language.method}`)})</span>
              </td>
            </tr>
            <tr>
              <th>{t("routing.intent")}</th>
              <td>
                {Object.entries(intent.scores)
                  .map(([k, v]) => `${t(`routing.intents.${k}`)} ${fmt(v)}`)
                  .join(" · ")}
                <div className="muted">
                  {intent.method === "knn"
                    ? t("routing.intent_rule_knn", {
                        margin: fmt(intent.margin, 2),
                        documentary: fmt(intent.documentary_margin),
                        probability: fmt(intent.not_documentary_probability, 2),
                      })
                    : intent.method === "logistic"
                      ? t("routing.intent_rule_logistic", {
                          probability: fmt(intent.not_documentary_probability, 2),
                        })
                      : t("routing.intent_rule", { margin: fmt(intent.margin, 2) })}
                  {intent.nearest_example
                    ? ` — ${t("routing.nearest_example", { text: intent.nearest_example })}`
                    : ""}
                </div>
              </td>
            </tr>
            <tr>
              <th>{t("routing.corpus")}</th>
              <td>
                {corpus.candidates.length > 0
                  ? corpus.candidates
                      .map((c) =>
                        c.translated_score != null
                          ? `${c.corpus_name} ${fmt(c.score)} ${t("routing.rescored", {
                              original: fmt(c.original_score),
                              translated: fmt(c.translated_score),
                            })}`
                          : `${c.corpus_name} ${fmt(c.score)}`,
                      )
                      .join(" · ")
                  : t("routing.no_candidate")}
                <div className="muted">
                  {t(`routing.corpus_sources.${corpus.source}`)} — {t("routing.margin")}{" "}
                  {fmt(corpus.margin)} — {t(`routing.scorings.${corpus.scoring ?? "chunks"}`)}
                </div>
              </td>
            </tr>
            <tr>
              <th>{t("routing.abstention")}</th>
              <td>
                {abstention
                  ? t("routing.abstention_rule", {
                      source: abstention.score_source,
                      score: fmt(abstention.best_score),
                      threshold: fmt(abstention.threshold),
                    })
                  : "—"}
                {abstention?.joint_score != null ? (
                  <div className="muted">
                    {t("routing.joint_score", {
                      score: fmt(abstention.joint_score, 2),
                      threshold: fmt(abstention.joint_threshold, 2),
                    })}
                  </div>
                ) : null}
                {abstention?.translated_score != null ? (
                  <div className="muted">
                    {t("routing.translated_score", { score: fmt(abstention.translated_score) })}
                  </div>
                ) : null}
              </td>
            </tr>
            <tr>
              <th>{t("routing.timings")}</th>
              <td>
                {Object.entries(routing.timings_ms)
                  .map(([k, v]) => `${k} ${v.toFixed(1)} ms`)
                  .join(" · ")}
              </td>
            </tr>
          </tbody>
        </table>
      ) : null}
    </div>
  );
}
