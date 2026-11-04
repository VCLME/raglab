import { useTranslation } from "react-i18next";
import { useConfig } from "./useConfig";

const REASONS = ["device_cpu", "torch_missing", "cuda_unavailable"];

/**
 * Why the re-ranker runs without a GPU, in words, from `/api/config`
 * `rerank_gpu_status`: GPU off by configuration, no PyTorch, or no CUDA
 * device seen by the API. An older API without the field gets the neutral
 * wording. Fills the `{{why}}` of the re-ranking notices.
 */
export function useGpuWhy(): string {
  const { t } = useTranslation();
  const status = useConfig()?.rerank_gpu_status;
  return t(`gpu.why_${status && REASONS.includes(status) ? status : "unknown"}`);
}
