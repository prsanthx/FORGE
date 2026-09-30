export default function Confirm({
  title,
  body,
  confirmLabel = "Remove",
  onCancel,
  onConfirm,
}: {
  title: string;
  body: string;
  confirmLabel?: string;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <div className="modal-back" role="presentation" onClick={onCancel}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="confirm-title"
        className="panel w-full max-w-sm p-4 shadow-lift"
        onClick={(event) => event.stopPropagation()}
      >
        <h2 id="confirm-title" className="text-[15px] font-medium">
          {title}
        </h2>
        <p className="mt-2 text-[13px] leading-6 text-mute">{body}</p>
        <div className="mt-4 flex justify-end gap-2">
          <button className="btn-ghost" onClick={onCancel}>
            Cancel
          </button>
          <button className="btn border-bad/40 bg-bad/10 text-bad" onClick={onConfirm}>
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
