interface Props {
  rank: number;
  fileName?: string;
  onClick: () => void;
  active?: boolean;
}

export function Citation({ rank, fileName, onClick, active }: Props) {
  return (
    <button
      className={`citation${active ? " active" : ""}`}
      onClick={onClick}
      title={fileName ? `Source rank ${rank} — ${fileName}` : `Source rank ${rank}`}
      type="button"
    >
      {rank}
    </button>
  );
}
