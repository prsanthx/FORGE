import type { Task } from "../types";
import { statusTone } from "../format";

export default function Dag({ tasks }: { tasks: Task[] }) {
  if (!tasks.length) return <p className="text-sm text-mute">The planner has not emitted tasks yet.</p>;
  const byKey = new Map(tasks.map((task) => [task.task_key, task]));
  const depth = new Map<string, number>();
  const visit = (key: string, stack: Set<string>): number => {
    if (depth.has(key)) return depth.get(key) || 0;
    if (stack.has(key)) return 0;
    stack.add(key);
    const task = byKey.get(key);
    const deps = task?.dependencies || [];
    const value = deps.length ? 1 + Math.max(...deps.map((dep) => visit(dep, stack))) : 0;
    depth.set(key, value);
    return value;
  };
  const layers: Task[][] = [];
  for (const task of tasks) {
    const layer = visit(task.task_key, new Set());
    while (layers.length <= layer) layers.push([]);
    layers[layer].push(task);
  }
  return (
    <div className="flex items-stretch gap-3 overflow-x-auto pb-1">
      {layers.map((layer, index) => (
        <div key={index} className="flex min-w-[220px] items-stretch gap-3">
          <div className="flex flex-1 flex-col gap-2.5">
            <div className="kicker">Layer {index + 1}</div>
            {layer.map((task, taskIndex) => (
              <div
                key={task.id}
                className={`rounded-xl border px-3 py-2.5 ${statusTone(task.status)}`}
                style={{ animation: `rise 0.45s cubic-bezier(0.16,1,0.3,1) ${index * 80 + taskIndex * 40}ms both` }}
              >
                <div className="flex items-center justify-between gap-2 text-[10px] font-medium uppercase tracking-wider">
                  <span className="font-mono">{task.task_key}</span>
                  <span>{task.status.replaceAll("_", " ")}</span>
                </div>
                <div className="mt-1 text-[13px] leading-5 text-ink">{task.title}</div>
                {task.dependencies.length > 0 && (
                  <div className="mt-1 text-[11px] text-mute">after {task.dependencies.join(", ")}</div>
                )}
                {task.attempt > 0 && <div className="mt-1 text-[11px] text-mute">attempt {task.attempt}</div>}
              </div>
            ))}
          </div>
          {index < layers.length - 1 && (
            <div className="hidden w-4 shrink-0 items-center justify-center text-faint sm:flex" aria-hidden>
              <svg viewBox="0 0 16 16" className="h-4 w-4">
                <path d="M3 8h9M9 4l4 4-4 4" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
