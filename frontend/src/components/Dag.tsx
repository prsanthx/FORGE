import type { Task } from "../types";
import { statusTone } from "../format";

export default function Dag({ tasks }: { tasks: Task[] }) {
  if (!tasks.length) return <p className="text-sm text-mute">No tasks yet.</p>;
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
    <div className="flex gap-4 overflow-x-auto pb-2">
      {layers.map((layer, index) => (
        <div key={index} className="flex min-w-[200px] flex-col gap-3">
          <div className="kicker">Layer {index + 1}</div>
          {layer.map((task) => (
            <div key={task.id} className={`rounded border bg-black/20 px-3 py-2 ${statusTone(task.status)}`}>
              <div className="flex items-center justify-between gap-2 text-[10px] uppercase tracking-wider">
                <span>{task.task_key}</span>
                <span>{task.status}</span>
              </div>
              <div className="mt-1 text-sm text-ink">{task.title}</div>
              {task.attempt > 0 && <div className="mt-1 text-[11px] text-mute">attempt {task.attempt}</div>}
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
