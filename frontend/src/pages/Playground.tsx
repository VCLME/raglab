import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { get, post } from "../api/client";
import { useApiAction, useApiLoad } from "../hooks/useApi";
import type {
  OllamaChatMessage,
  OllamaChatResponse,
  OllamaModelsResponse,
} from "../api/types";
import { ErrorBanner } from "../components/ErrorBanner";
import { ExplainBanner } from "../components/ExplainBanner";
import { FieldRow } from "../components/FieldRow";
import { JsonViewer } from "../components/JsonViewer";
import { Spinner } from "../components/Spinner";

export function Playground() {
  const { t } = useTranslation();
  const modelsLoad = useApiLoad<OllamaModelsResponse>(() => get("/api/ollama/models"));
  const [model, setModel] = useState("");
  const [system, setSystem] = useState("");
  const [userPrompt, setUserPrompt] = useState("");
  const [temperature, setTemperature] = useState(0.2);
  const [topP, setTopP] = useState(0.9);
  const [numPredict, setNumPredict] = useState<string>("");
  const [numCtx, setNumCtx] = useState<string>("");
  const [seed, setSeed] = useState<string>("");
  const [advancedRaw, setAdvancedRaw] = useState("");
  const [conversation, setConversation] = useState<OllamaChatMessage[]>([]);

  const action = useApiAction((body: unknown) =>
    post<OllamaChatResponse>("/api/ollama/chat", body)
  );

  const defaultModel = modelsLoad.data?.default_generation_model ?? "qwen2.5:7b";
  const effectiveModel = model || defaultModel;

  const parsedAdvanced = useMemo(() => {
    if (!advancedRaw.trim()) return null;
    try {
      return JSON.parse(advancedRaw);
    } catch {
      return null;
    }
  }, [advancedRaw]);

  const advancedInvalid = advancedRaw.trim() !== "" && parsedAdvanced === null;

  const send = async () => {
    const body: Record<string, unknown> = {
      messages: [...conversation, { role: "user", content: userPrompt }],
      model: model || null,
      system: system || null,
      temperature,
      top_p: topP,
    };
    if (numPredict) body.num_predict = Number(numPredict);
    if (numCtx) body.num_ctx = Number(numCtx);
    if (seed) body.seed = Number(seed);
    if (parsedAdvanced && typeof parsedAdvanced === "object") {
      body.options = parsedAdvanced;
    }
    const result = await action.run(body);
    setConversation((prev) => [
      ...prev,
      { role: "user", content: userPrompt },
      { role: "assistant", content: result.answer },
    ]);
    setUserPrompt("");
  };

  const reset = () => {
    setConversation([]);
    action.reset();
  };

  return (
    <div>
      <div className="page-header">
        <h2>{t("playground.title")}</h2>
        <span className="muted">{t("playground.subtitle")}</span>
      </div>
      <ExplainBanner
        subtitle={t("playground.subtitle")}
        body={t("playground.explain_body")}
        storageKey="raglab.explain.playground"
      />
      <div className="split">
        <div>
          <div className="card">
            <h3>{t("playground.model_params")}</h3>
            <FieldRow
              label={t("playground.model_label")}
              hint={t("playground.model_default_hint", { value: defaultModel })}
            >
              <select value={model} onChange={(e) => setModel(e.target.value)}>
                <option value="">
                  {t("playground.model_default_option", { value: defaultModel })}
                </option>
                {(modelsLoad.data?.models ?? []).map((m) => (
                  <option key={m.name} value={m.name}>
                    {m.name}
                  </option>
                ))}
              </select>
            </FieldRow>
            <FieldRow label={t("playground.system_label")} hint={t("playground.system_hint")}>
              <textarea value={system} onChange={(e) => setSystem(e.target.value)} rows={4} />
            </FieldRow>
            <FieldRow label={t("playground.temperature_label", { value: temperature.toFixed(2) })}>
              <input
                type="range"
                min={0}
                max={2}
                step={0.05}
                value={temperature}
                onChange={(e) => setTemperature(Number(e.target.value))}
              />
            </FieldRow>
            <FieldRow label={t("playground.top_p_label", { value: topP.toFixed(2) })}>
              <input
                type="range"
                min={0}
                max={1}
                step={0.05}
                value={topP}
                onChange={(e) => setTopP(Number(e.target.value))}
              />
            </FieldRow>
            <FieldRow label={t("playground.num_predict_label")} hint={t("playground.num_predict_hint")}>
              <input type="number" value={numPredict} onChange={(e) => setNumPredict(e.target.value)} />
            </FieldRow>
            <FieldRow label={t("playground.num_ctx_label")} hint={t("playground.num_ctx_hint")}>
              <input type="number" value={numCtx} onChange={(e) => setNumCtx(e.target.value)} />
            </FieldRow>
            <FieldRow label={t("playground.seed_label")} hint={t("playground.seed_hint")}>
              <input type="number" value={seed} onChange={(e) => setSeed(e.target.value)} />
            </FieldRow>
            <FieldRow label={t("playground.options_label")} hint={t("playground.options_hint")}>
              <textarea
                value={advancedRaw}
                onChange={(e) => setAdvancedRaw(e.target.value)}
                rows={3}
                placeholder='{"repeat_penalty": 1.1}'
              />
            </FieldRow>
            {advancedInvalid ? (
              <div className="error-banner">{t("playground.options_invalid")}</div>
            ) : null}
          </div>
        </div>

        <div>
          <div className="card">
            <div className="inline" style={{ justifyContent: "space-between" }}>
              <h3 style={{ margin: 0 }}>{t("playground.conversation")}</h3>
              <div className="inline">
                <span className="muted">
                  {t("playground.model_prefix")} <code>{effectiveModel || t("playground.model_fallback")}</code>
                </span>
                <button className="ghost" onClick={reset}>
                  {t("common.reset")}
                </button>
              </div>
            </div>
            <div className="chat" style={{ marginTop: 12 }}>
              {conversation.length === 0 ? (
                <p className="muted">{t("playground.no_messages")}</p>
              ) : null}
              {conversation.map((m, i) => (
                <div key={i} className={`bubble ${m.role}`}>
                  <div className="muted" style={{ fontSize: 10, marginBottom: 4 }}>
                    {m.role}
                  </div>
                  {m.content}
                </div>
              ))}
            </div>
            <FieldRow label={t("playground.user_prompt")}>
              <textarea value={userPrompt} onChange={(e) => setUserPrompt(e.target.value)} rows={4} />
            </FieldRow>
            <div className="inline">
              <button
                onClick={send}
                disabled={action.loading || !userPrompt.trim() || advancedInvalid}
              >
                {action.loading ? t("playground.sending") : t("playground.send")}
              </button>
              {action.loading ? <Spinner /> : null}
              {action.data ? (
                <span className="muted">
                  {t("playground.elapsed", { ms: action.data.elapsed_ms.toFixed(0) })}
                </span>
              ) : null}
            </div>
            <ErrorBanner error={action.error} />
          </div>
          {action.data ? (
            <div className="card">
              <h3>{t("playground.payload_sent")}</h3>
              <JsonViewer value={action.data.payload_sent} maxHeight={300} />
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
