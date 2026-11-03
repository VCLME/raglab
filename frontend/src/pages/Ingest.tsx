import { useState } from "react";
import { useTranslation } from "react-i18next";
import { post } from "../api/client";
import { useApiAction } from "../hooks/useApi";
import type { IngestResponse } from "../api/types";
import { ErrorBanner } from "../components/ErrorBanner";
import { FieldRow } from "../components/FieldRow";
import { JsonViewer } from "../components/JsonViewer";
import { Spinner } from "../components/Spinner";
import { StatusBadge } from "../components/StatusBadge";

export function Ingest() {
  const { t } = useTranslation();
  const [folder, setFolder] = useState("data/documents");
  const [corpus, setCorpus] = useState("demo");
  const [description, setDescription] = useState("");
  const [tagsRaw, setTagsRaw] = useState("");

  const action = useApiAction((body: unknown) =>
    post<IngestResponse>("/api/ingest", body)
  );

  const submit = () => {
    const tags = tagsRaw
      .split(",")
      .map((t) => t.trim())
      .filter(Boolean);
    action.run({
      folder,
      corpus,
      description: description || null,
      tags: tags.length ? tags : null,
    });
  };

  return (
    <div>
      <p className="muted card-lead">{t("ingest.subtitle")}</p>
      <div className="split">
        <div className="card">
          <h3>{t("query.parameters")}</h3>
          <FieldRow label={t("ingest.folder_label")} hint={t("ingest.folder_hint")}>
            <input value={folder} onChange={(e) => setFolder(e.target.value)} />
          </FieldRow>
          <FieldRow label={t("ingest.corpus_label")}>
            <input value={corpus} onChange={(e) => setCorpus(e.target.value)} />
          </FieldRow>
          <FieldRow label={t("ingest.description_label")} hint={t("ingest.description_hint")}>
            <input value={description} onChange={(e) => setDescription(e.target.value)} />
          </FieldRow>
          <FieldRow label={t("ingest.tags_label")} hint={t("ingest.tags_hint")}>
            <input
              value={tagsRaw}
              onChange={(e) => setTagsRaw(e.target.value)}
              placeholder="legal, contrat"
            />
          </FieldRow>
          <button onClick={submit} disabled={action.loading || !folder || !corpus}>
            {action.loading ? t("ingest.ingesting") : t("ingest.launch")}
          </button>
        </div>
        <div className="card">
          <h3>{t("common.result")}</h3>
          {action.loading ? <Spinner label={t("ingest.ingesting")} /> : null}
          <ErrorBanner error={action.error} />
          {action.data ? (
            <>
              <div className="inline" style={{ marginBottom: 12 }}>
                <StatusBadge
                  state="ok"
                  label={t("ingest.ingested_badge", { count: action.data.ingested })}
                />
                <StatusBadge
                  state="info"
                  label={t("ingest.updated_badge", { count: action.data.updated })}
                />
                <StatusBadge
                  state="warn"
                  label={t("ingest.skipped_badge", { count: action.data.skipped })}
                />
              </div>
              <JsonViewer value={action.data} />
            </>
          ) : (
            <p className="muted">{t("ingest.empty_result")}</p>
          )}
        </div>
      </div>
    </div>
  );
}
