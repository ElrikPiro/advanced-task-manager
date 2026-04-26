interface KeyValueGridProps {
  entries: Array<{ label: string; value: string | number }>;
}

export function KeyValueGrid({ entries }: KeyValueGridProps): JSX.Element {
  return (
    <div className="key-value-grid">
      {entries.map((entry) => (
        <div key={entry.label} className="key-value-row">
          <span className="key">{entry.label}</span>
          <span className="value">{entry.value}</span>
        </div>
      ))}
    </div>
  );
}
