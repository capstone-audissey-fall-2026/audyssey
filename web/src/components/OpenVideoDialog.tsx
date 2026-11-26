import { FormEvent, useEffect, useId, useRef } from "react";
import { projectRow } from "../lib/projects";
import type { Job } from "../types";
import GpuToolsForm from "./GpuToolsForm";
import Icon from "./Icon";

interface OpenVideoDialogProps {
  open: boolean;
  onClose: () => void;
  onUpload: (file: File) => Promise<void> | void; // rejects when the server refuses the file
  uploading: boolean;
  uploadError: string | null;
  projects: Job[]; // newest first
  onOpenJob: (id: string) => void;
}

export default function OpenVideoDialog({ open, onClose, onUpload, uploading, uploadError, projects, onOpenJob }: OpenVideoDialogProps) {
  const uid = useId();
  const dialogRef = useRef<HTMLDialogElement | null>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  // The chosen file stays in the input when the upload fails, so the person can see what was refused.
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = event.currentTarget;
    const file = new FormData(form).get("file");
    if (!(file instanceof File) || file.size === 0) return;
    try {
      await onUpload(file);
      form.reset();
    } catch {
      // App reports the failure through `uploadError`.
    }
  };

  return (
    <dialog
      aria-labelledby={`${uid}-title`}
      className="dlg"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
      onClose={onClose}
      ref={dialogRef}
    >
      <div className="dlg-body">
        <div className="dlg-head">
          <h2 id={`${uid}-title`}>Open video</h2>
          <button className="btn sm" type="button" onClick={onClose}>
            Close
          </button>
        </div>
        <form className="dlg-sec" onSubmit={submit}>
          <h3>Upload a video</h3>
          <label>
            Video
            <input name="file" type="file" accept="video/*" required aria-describedby={uploadError ? `${uid}-err` : undefined} />
          </label>
          {uploadError ? (
            <p className="err" id={`${uid}-err`} role="alert">
              <Icon name="x" />
              <span>{uploadError}</span>
            </p>
          ) : null}
          <div className="actions">
            <button className="btn" type="submit" disabled={uploading}>
              {uploading ? "Uploading…" : "Upload"}
            </button>
          </div>
        </form>
        <GpuToolsForm open={open} />
        <section className="dlg-sec" aria-labelledby={`${uid}-recent`}>
          <h3 id={`${uid}-recent`}>Recent projects</h3>
          {projects.length === 0 ? (
            <p className="dlg-empty">No projects yet. Uploaded videos appear here.</p>
          ) : (
            <ul className="proj-list">
              {projects.map(projectRow).map((row) => (
                <li className="proj" key={row.id}>
                  <div className="proj-info">
                    <span className="proj-name">{row.label}</span>
                    <span className="proj-meta">{row.detail}</span>
                  </div>
                  <button className="btn sm" type="button" onClick={() => onOpenJob(row.id)}>
                    Open
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </dialog>
  );
}
