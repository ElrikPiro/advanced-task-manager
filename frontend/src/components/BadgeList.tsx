interface BadgeListProps {
  title: string;
  values: string[];
}

export function BadgeList({ title, values }: BadgeListProps): JSX.Element {
  return (
    <section className="panel">
      <h2>{title}</h2>
      {values.length === 0 ? (
        <p className="empty">No entries</p>
      ) : (
        <div className="badge-list">
          {values.map((value) => (
            <span key={value} className="badge">
              {value}
            </span>
          ))}
        </div>
      )}
    </section>
  );
}
