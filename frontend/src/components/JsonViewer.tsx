interface Props {
  value: unknown;
  maxHeight?: number;
}

export function JsonViewer({ value, maxHeight }: Props) {
  const style = maxHeight ? { maxHeight: `${maxHeight}px` } : undefined;
  return (
    <pre className="json-viewer" style={style}>
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}
