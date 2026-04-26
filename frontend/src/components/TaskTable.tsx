import type { TaskEntry } from "../types/api";

interface TaskTableProps {
  title: string;
  tasks: TaskEntry[];
  onSelect?: (task: TaskEntry, index: number) => void;
}

export function TaskTable({ title, tasks, onSelect }: TaskTableProps): JSX.Element {
  return (
    <section className="panel">
      <h2>{title}</h2>
      {tasks.length === 0 ? (
        <p className="empty">No tasks available</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>Description</th>
                <th>Context</th>
                <th>Start</th>
                <th>Due</th>
                <th>Remaining (p)</th>
                <th>Invested (p)</th>
                <th>Severity</th>
                <th>Status</th>
                <th>Heuristic</th>
              </tr>
            </thead>
            <tbody>
              {tasks.map((task, index) => (
                <tr
                  key={`${task.id}-${index}`}
                  className={onSelect ? "clickable" : ""}
                  onClick={() => onSelect?.(task, index)}
                  onKeyDown={(event) => {
                    if (!onSelect) {
                      return;
                    }
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      onSelect(task, index);
                    }
                  }}
                  tabIndex={onSelect ? 0 : -1}
                >
                  <td>{index + 1}</td>
                  <td>{task.description}</td>
                  <td>{task.context}</td>
                  <td>{task.start}</td>
                  <td>{task.due}</td>
                  <td>{task.total_cost.toFixed(2)}</td>
                  <td>{task.effort_invested.toFixed(2)}</td>
                  <td>{task.severity.toFixed(2)}</td>
                  <td>{task.status || "-"}</td>
                  <td>{task.heuristic_value.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
