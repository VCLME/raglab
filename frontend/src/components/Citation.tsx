import { useTranslation } from "react-i18next";

interface Props {
  rank: number;
  fileName?: string;
  /** What the chip reads instead of the rank, e.g. the cited article ("art. L221-18"). */
  label?: string | null;
  onClick: () => void;
  active?: boolean;
}

export function Citation({ rank, fileName, label, onClick, active }: Props) {
  const { t } = useTranslation();
  return (
    <button
      className={`citation${label ? " labelled" : ""}${active ? " active" : ""}`}
      onClick={onClick}
      title={fileName ? t("chat.citation_title_file", { rank, file: fileName }) : t("chat.citation_title", { rank })}
      type="button"
    >
      {label ?? rank}
    </button>
  );
}
