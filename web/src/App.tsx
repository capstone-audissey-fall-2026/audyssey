import { useEffect, useState } from "react";
import { exportUrl, listJobs, sendCommand, startJob, uploadVideo } from "./api";
import OpenVideoDialog from "./components/OpenVideoDialog";
import TopBar from "./components/TopBar";
import { errorText, useJob } from "./lib/useJob";
import type { Job, Method } from "./types";

const hashId = () => decodeURIComponent(window.location.hash.slice(1)) || null;

export default function App() {
  const { job, busy, error, follow, run, receive } = useJob();
  const [method, setMethod] = useState<Method>("separate");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [projects, setProjects] = useState<Job[]>([]);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);

  // The job id lives in the URL hash, so a reload or a shared link opens the same job.
  useEffect(() => {
    const sync = () => {
      const id = hashId();
      void follow(id);
      if (id === null) setDialogOpen(true);
    };
    sync();
    window.addEventListener("hashchange", sync);
    return () => window.removeEventListener("hashchange", sync);
  }, [follow]);

  useEffect(() => {
    if (dialogOpen) listJobs().then(setProjects, () => setProjects([]));
  }, [dialogOpen]);

  const open = (id: string) => {
    window.location.hash = encodeURIComponent(id);
    setDialogOpen(false);
  };

  const upload = async (file: File) => {
    setUploading(true);
    setUploadError(null);
    try {
      open((await uploadVideo(file)).id);
    } catch (e) {
      setUploadError(errorText(e));
      throw e;
    } finally {
      setUploading(false);
    }
  };

  const start = () => {
    if (!job) return;
    void run("start", () => startJob(job.id, job.silent ? "generate" : method)).then((next) => next && receive(next));
  };

  const exportMix = () => {
    if (!job) return;
    void run("export", async () => {
      receive(await sendCommand(job.id, { type: "render", include_residual_stem: false }));
      const link = document.createElement("a");
      link.href = exportUrl(job.id);
      link.download = "";
      link.click();
    });
  };

  return (
    <div className="app">
      <TopBar
        job={job}
        busy={busy}
        error={error}
        method={method}
        onMethodChange={setMethod}
        onOpen={() => {
          setUploadError(null);
          setDialogOpen(true);
        }}
        onStart={start}
        onExport={exportMix}
      />
      <main className="main">{job ? null : <p className="dlg-empty">Open a video to start.</p>}</main>
      <OpenVideoDialog
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
        onUpload={upload}
        uploading={uploading}
        uploadError={uploadError}
        projects={projects}
        onOpenJob={open}
      />
    </div>
  );
}
