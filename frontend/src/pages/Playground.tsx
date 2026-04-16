import { useMemo, useState } from "react";
import { get, post } from "../api/client";
import { useApiAction, useApiLoad } from "../hooks/useApi";
import type {
  OllamaChatMessage,
  OllamaChatResponse,
  OllamaModelsResponse,
} from "../api/types";
import { ErrorBanner } from "../components/ErrorBanner";
import { FieldRow } from "../components/FieldRow";
import { JsonViewer } from "../components/JsonViewer";
import { Spinner } from "../components/Spinner";

export function Playground() {
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

  const effectiveModel = model || modelsLoad.data?.default_generation_model || "";

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
        <h2>Prompt Playground</h2>
        <span className="muted">Ollama direct, sans retrieval.</span>
      </div>
      <div className="split">
        <div>
          <div className="card">
            <h3>Parametres modele</h3>
            <FieldRow label="Modele">
              <select value={model} onChange={(e) => setModel(e.target.value)}>
                <option value="">(defaut : {modelsLoad.data?.default_generation_model ?? "qwen2.5:7b"})</option>
                {(modelsLoad.data?.models ?? []).map((m) => (
                  <option key={m.name} value={m.name}>
                    {m.name}
                  </option>
                ))}
              </select>
            </FieldRow>
            <FieldRow label="System prompt" hint="Optionnel, applique une fois par echange">
              <textarea value={system} onChange={(e) => setSystem(e.target.value)} rows={4} />
            </FieldRow>
            <FieldRow label={`Temperature (${temperature.toFixed(2)})`}>
              <input type="range" min={0} max={2} step={0.05} value={temperature} onChange={(e) => setTemperature(Number(e.target.value))} />
            </FieldRow>
            <FieldRow label={`top_p (${topP.toFixed(2)})`}>
              <input type="range" min={0} max={1} step={0.05} value={topP} onChange={(e) => setTopP(Number(e.target.value))} />
            </FieldRow>
            <FieldRow label="num_predict" hint="Limite de tokens en sortie">
              <input type="number" value={numPredict} onChange={(e) => setNumPredict(e.target.value)} />
            </FieldRow>
            <FieldRow label="num_ctx" hint="Taille de la fenetre de contexte">
              <input type="number" value={numCtx} onChange={(e) => setNumCtx(e.target.value)} />
            </FieldRow>
            <FieldRow label="seed" hint="Pour de la reproductibilite">
              <input type="number" value={seed} onChange={(e) => setSeed(e.target.value)} />
            </FieldRow>
            <FieldRow label="options JSON avancees" hint="Fusionnees avec les champs ci-dessus">
              <textarea value={advancedRaw} onChange={(e) => setAdvancedRaw(e.target.value)} rows={3} placeholder='{"repeat_penalty": 1.1}' />
            </FieldRow>
            {advancedInvalid ? <div className="error-banner">JSON invalide dans options avancees</div> : null}
          </div>
        </div>

        <div>
          <div className="card">
            <div className="inline" style={{ justifyContent: "space-between" }}>
              <h3 style={{ margin: 0 }}>Conversation</h3>
              <div className="inline">
                <span className="muted">
                  Modele : <code>{effectiveModel || "defaut"}</code>
                </span>
                <button className="ghost" onClick={reset}>Reset</button>
              </div>
            </div>
            <div className="chat" style={{ marginTop: 12 }}>
              {conversation.length === 0 ? (
                <p className="muted">Aucun message encore. Envoyez un prompt ci-dessous.</p>
              ) : null}
              {conversation.map((m, i) => (
                <div key={i} className={`bubble ${m.role}`}>
                  <div className="muted" style={{ fontSize: 10, marginBottom: 4 }}>{m.role}</div>
                  {m.content}
                </div>
              ))}
            </div>
            <FieldRow label="User prompt">
              <textarea value={userPrompt} onChange={(e) => setUserPrompt(e.target.value)} rows={4} />
            </FieldRow>
            <div className="inline">
              <button onClick={send} disabled={action.loading || !userPrompt.trim() || advancedInvalid}>
                {action.loading ? "Envoi…" : "Envoyer"}
              </button>
              {action.loading ? <Spinner /> : null}
              {action.data ? (
                <span className="muted">reponse en {action.data.elapsed_ms.toFixed(0)} ms</span>
              ) : null}
            </div>
            <ErrorBanner error={action.error} />
          </div>
          {action.data ? (
            <div className="card">
              <h3>Payload envoye</h3>
              <JsonViewer value={action.data.payload_sent} maxHeight={300} />
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
