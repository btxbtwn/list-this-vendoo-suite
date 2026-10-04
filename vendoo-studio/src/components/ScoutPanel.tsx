import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { ScoutCheck, ScoutState } from "../api/types";
import { addToast } from "../ui/toast";
import { formatMoney } from "./analyticsFormat";
import { DraftInput } from "./DraftInput";
import { SCOUT_QUERY_KEY, isChecking, trackRecordLine, verdictLabel, verdictReason } from "./scoutCheck";
import { SoldCompsCard } from "./SoldCompsCard";

const MAX_PHOTOS = 8;

interface Props {
  onOpenListing: (convId: string) => void;
}

/**
 * "Is this worth buying?" while standing in the store: a photo or two of the
 * item and its tag, the asking price if there is one, and Studio answers from
 * sold comps. Bought starts a draft from the same photos; nothing is listed.
 */
export function ScoutPanel({ onOpenListing }: Props) {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: SCOUT_QUERY_KEY,
    queryFn: api.scout.list,
    refetchInterval: (current) => (isChecking(current.state.data) ? 3000 : false),
  });
  const [openId, setOpenId] = useState<string | null>(null);
  const checks = query.data?.checks ?? [];
  const open = checks.find((check) => check.id === openId) ?? checks[0] ?? null;
  const record = query.data ? trackRecordLine(query.data.track_record) : null;

  const replace = (check: ScoutCheck) => {
    queryClient.setQueryData<ScoutState>(SCOUT_QUERY_KEY, (current) => current && {
      ...current,
      checks: current.checks.some((row) => row.id === check.id)
        ? current.checks.map((row) => (row.id === check.id ? check : row))
        : [check, ...current.checks],
    });
  };

  return (
    <div className="scout">
      <NewCheck
        onCreated={(check) => {
          replace(check);
          setOpenId(check.id);
        }}
      />
      {query.isError ? <p className="sourcing-hint">{(query.error as Error).message}</p> : null}
      {open ? (
        <CheckCard
          key={open.id}
          check={open}
          onChanged={(check) => {
            replace(check);
            void queryClient.invalidateQueries({ queryKey: SCOUT_QUERY_KEY });
          }}
          onOpenListing={onOpenListing}
        />
      ) : null}
      {checks.length > 1 ? (
        <section className="sourcing-section" aria-label="Earlier checks">
          <h2 className="sourcing-section-title">Earlier checks</h2>
          {record ? <p className="sourcing-hint">{record}</p> : null}
          <ol className="sourcing-items">
            {checks.filter((check) => check.id !== open?.id).map((check) => (
              <HistoryRow key={check.id} check={check} onOpen={() => setOpenId(check.id)} />
            ))}
          </ol>
        </section>
      ) : null}
    </div>
  );
}

function NewCheck({ onCreated }: { onCreated: (check: ScoutCheck) => void }) {
  const [photos, setPhotos] = useState<{ file: File; url: string }[]>([]);
  const [asking, setAsking] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const photosRef = useRef(photos);
  useEffect(() => {
    photosRef.current = photos;
  }, [photos]);
  useEffect(() => () => photosRef.current.forEach((photo) => URL.revokeObjectURL(photo.url)), []);
  const clear = () => {
    photos.forEach((photo) => URL.revokeObjectURL(photo.url));
    setPhotos([]);
  };
  const create = useMutation({
    mutationFn: () => api.scout.create(photos.map((photo) => photo.file), asking.trim() ? Number(asking) : null),
    onSuccess: (check) => {
      clear();
      setAsking("");
      onCreated(check);
    },
    onError: (error: Error) => addToast({ type: "error", title: "Could not start the check", description: error.message }),
  });

  return (
    <form
      className="scout-new"
      onSubmit={(event) => {
        event.preventDefault();
        if (photos.length && !create.isPending) create.mutate();
      }}
    >
      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        capture="environment"
        multiple
        hidden
        onChange={(event) => {
          const room = MAX_PHOTOS - photos.length;
          const picked = Array.from(event.target.files ?? []).slice(0, Math.max(0, room));
          setPhotos((current) => [...current, ...picked.map((file) => ({ file, url: URL.createObjectURL(file) }))]);
          event.target.value = "";
        }}
      />
      <div className="scout-photos">
        {photos.map((photo, index) => (
          <button
            key={photo.url}
            type="button"
            className="scout-thumb"
            aria-label={`Remove photo ${index + 1}`}
            onClick={() => {
              URL.revokeObjectURL(photo.url);
              setPhotos((current) => current.filter((row) => row !== photo));
            }}
          >
            <img src={photo.url} alt="" />
          </button>
        ))}
        {photos.length < MAX_PHOTOS ? (
          <button type="button" className="scout-add" onClick={() => inputRef.current?.click()}>
            {photos.length ? "Add another" : "Take photos"}
          </button>
        ) : null}
      </div>
      <p className="sourcing-hint">The whole item and its brand tag are usually enough. Tap a photo to remove it.</p>
      <div className="scout-new-row">
        <label className="sourcing-setting">
          Asking (optional)
          <span className="sourcing-input">
            <span className="sourcing-input-prefix">$</span>
            <input
              className="input input-sm"
              style={{ width: "5.5rem" }}
              inputMode="decimal"
              aria-label="Asking price"
              value={asking}
              onChange={(event) => setAsking(event.target.value.replace(/[^\d.]/g, ""))}
            />
          </span>
        </label>
        <button type="submit" className="btn btn-primary" disabled={!photos.length || create.isPending}>
          {create.isPending ? "Uploading…" : "Is it worth it?"}
        </button>
      </div>
    </form>
  );
}

function CheckCard({
  check,
  onChanged,
  onOpenListing,
}: {
  check: ScoutCheck;
  onChanged: (check: ScoutCheck) => void;
  onOpenListing: (convId: string) => void;
}) {
  const onError = (error: Error) => addToast({ type: "error", title: "Could not save", description: error.message });
  const price = useMutation({
    mutationFn: (value: number | null) => api.scout.setAskingPrice(check.id, value),
    onSuccess: onChanged,
    onError,
  });
  const decide = useMutation({
    mutationFn: (decision: "bought" | "passed") => api.scout.decide(check.id, decision),
    onSuccess: (updated) => {
      onChanged(updated);
      if (updated.decision === "bought") {
        addToast({ type: "success", title: "Draft started", description: "Its photos and analysis are ready to generate." });
      }
    },
    onError,
  });
  const label = verdictLabel(check.verdict);

  return (
    <section className="scout-card" aria-label={check.title || "Current check"}>
      <div className="scout-card-photos">
        {check.photo_urls.map((url) => <img key={url} src={url} alt="" />)}
      </div>
      <div className="scout-card-title">{check.title || "Looking at your photos…"}</div>
      {check.status === "checking" ? (
        <p className="sourcing-hint" role="status">Identifying it and looking up sold listings. This usually takes a minute or two.</p>
      ) : null}
      {check.status === "failed" ? <p className="sourcing-problem" role="alert">{check.error}</p> : null}
      {check.status === "done" ? (
        <>
          <div className="scout-verdict-row">
            {label ? <span className={`scout-verdict is-${check.verdict}`}>{label}</span> : null}
            <span className="scout-reason">{verdictReason(check)}</span>
          </div>
          <div className="scout-card-actions">
            <span className="sourcing-setting">
              Asking
              <DraftInput
                value={check.asking_price != null ? String(check.asking_price) : ""}
                label="Asking price"
                prefix="$"
                width="5.5rem"
                inputMode="decimal"
                disabled={price.isPending}
                clean={(text) => text.replace(/[^\d.]/g, "")}
                accept={(text) => text === "" || Number.isFinite(Number(text))}
                onCommit={(text) => price.mutate(text === "" ? null : Number(text))}
              />
            </span>
            <span className="scout-spacer" />
            <span className="scout-decide">
            {check.decision === "bought" && check.conversation_id ? (
              <button type="button" className="btn btn-primary" onClick={() => onOpenListing(check.conversation_id!)}>
                Open the draft
              </button>
            ) : (
              <>
                <button
                  type="button"
                  className="btn btn-secondary"
                  disabled={decide.isPending || check.decision === "passed"}
                  onClick={() => decide.mutate("passed")}
                >
                  {check.decision === "passed" ? "Passed" : "Pass"}
                </button>
                <button
                  type="button"
                  className="btn btn-primary"
                  disabled={decide.isPending}
                  onClick={() => decide.mutate("bought")}
                >
                  I bought it
                </button>
              </>
            )}
            </span>
          </div>
          {check.comps ? (
            <details className="sourcing-more">
              <summary>Sold listings Studio found</summary>
              <SoldCompsCard text={check.comps} />
            </details>
          ) : null}
        </>
      ) : null}
    </section>
  );
}

function HistoryRow({ check, onOpen }: { check: ScoutCheck; onOpen: () => void }) {
  const label = check.status === "checking" ? "Checking…" : check.status === "failed" ? "Failed" : verdictLabel(check.verdict);
  const outcome = check.sold_price != null
    ? `sold for ${formatMoney(check.sold_price)}`
    : check.decision === "bought" ? "bought" : check.decision === "passed" ? "passed" : null;
  return (
    <li className="sourcing-item">
      <div className="sourcing-item-main">
        <button type="button" className="sourcing-link sourcing-item-title" onClick={onOpen}>
          {check.title || "Unidentified item"}
        </button>
        <div className="sourcing-item-reason">
          {[label, check.asking_price != null ? `asking ${formatMoney(check.asking_price)}` : null, outcome]
            .filter(Boolean).join(" · ")}
        </div>
      </div>
      <div className="sourcing-item-money">
        {check.estimate != null ? <div>{formatMoney(Math.round(check.estimate))}</div> : null}
      </div>
    </li>
  );
}
