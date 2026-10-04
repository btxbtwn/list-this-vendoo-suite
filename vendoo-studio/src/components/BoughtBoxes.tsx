import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { SourceBox, SourceBoxInput, SourceBoxes, SourceStoreResults } from "../api/types";
import { confirmDialog } from "../ui/confirmDialog";
import { addToast } from "../ui/toast";
import { formatDays, formatMoney } from "./analyticsFormat";
import { BOXES_QUERY_KEY, boxProgress, boxStoreKey, boxStoreName, formatPercent } from "./boughtBoxes";
import { DraftInput } from "./DraftInput";

/**
 * The boxes the seller bought and what each has made back so far: money in
 * against what its sales brought in after fees and shipping. Listings join a
 * box when its photos are bulk uploaded, or from Item Details.
 */
export function BoughtBoxes() {
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: BOXES_QUERY_KEY, queryFn: api.boxes.list });
  const onSaved = (data: SourceBoxes) => queryClient.setQueryData(BOXES_QUERY_KEY, data);
  const onError = (error: Error) =>
    addToast({ type: "error", title: "Could not save the box", description: error.message });
  const update = useMutation({
    mutationFn: ({ id, changes }: { id: string; changes: Partial<SourceBoxInput> }) => api.boxes.update(id, changes),
    onSuccess: onSaved,
    onError,
  });
  const remove = useMutation({ mutationFn: api.boxes.remove, onSuccess: onSaved, onError });
  const create = useMutation({ mutationFn: api.boxes.create, onSuccess: onSaved, onError });
  const [adding, setAdding] = useState(false);
  const data = query.data;

  const onRemove = async (box: SourceBox) => {
    const ok = await confirmDialog(
      `Remove “${box.title}” from your boxes? Its listings stay; they just won't belong to a box.`,
      { variant: "destructive", confirmLabel: "Remove box" },
    );
    if (ok) remove.mutate(box.id);
  };

  return (
    <section className="sourcing-section" aria-label="Boxes you bought">
      <div className="sourcing-title-row">
        <h2 className="sourcing-section-title">Boxes you bought</h2>
        {!adding ? (
          <button type="button" className="sourcing-link bought-add-link" onClick={() => setAdding(true)}>Add a box</button>
        ) : null}
      </div>
      <p className="sourcing-hint">
        What each box cost with shipping, and what its sales have brought back after fees. Choose the box when you
        bulk upload its photos, or in a listing's Item Details.
      </p>
      {adding ? (
        <AddBoxForm
          saving={create.isPending}
          onCancel={() => setAdding(false)}
          onSave={(box) => create.mutate(box, { onSuccess: () => setAdding(false) })}
        />
      ) : null}
      {query.isError ? <p className="sourcing-hint">{(query.error as Error).message}</p> : null}
      {data && data.boxes.length === 0 && !adding ? (
        <p className="sourcing-hint">
          No boxes yet. Press <strong>I bought this</strong> on a box above once you've paid for it.
        </p>
      ) : null}
      {data && data.stores.length > 1 ? (
        <div className="bought-stores">
          {data.stores.map((store) => <StoreCard key={store.store} store={store} />)}
        </div>
      ) : null}
      {data?.boxes.length ? (
        <ol className="sourcing-items">
          {data.boxes.map((box) => (
            <BoxRow
              key={box.id}
              box={box}
              saving={update.isPending}
              onChange={(changes) => update.mutate({ id: box.id, changes })}
              onRemove={() => void onRemove(box)}
            />
          ))}
        </ol>
      ) : null}
    </section>
  );
}

function StoreCard({ store }: { store: SourceStoreResults }) {
  return (
    <div className="bought-store">
      <strong>{boxStoreName(store.store)}</strong>
      <span>{store.boxes === 1 ? "1 box" : `${store.boxes} boxes`} · {formatMoney(Math.round(store.spent))} in</span>
      <span>
        {formatMoney(Math.round(store.returned))} back ·{" "}
        <span className={store.profit >= 0 ? "sourcing-profit" : "sourcing-loss"}>
          {store.profit >= 0 ? "+" : "−"}{formatMoney(Math.abs(Math.round(store.profit)))}
        </span>
      </span>
      <span>{formatPercent(store.sell_through)} sold{store.median_days != null ? ` · ${formatDays(store.median_days)} to sell` : ""}</span>
    </div>
  );
}

function BoxRow({
  box,
  saving,
  onChange,
  onRemove,
}: {
  box: SourceBox;
  saving: boolean;
  onChange: (changes: Partial<SourceBoxInput>) => void;
  onRemove: () => void;
}) {
  const money = (text: string) => Number.isFinite(Number(text)) && Number(text) >= 0 && text !== "";
  const bought = box.bought_at ? new Date(box.bought_at).toLocaleDateString(undefined, { month: "short", day: "numeric" }) : null;
  return (
    <li className="sourcing-item">
      <div className="sourcing-item-main">
        {box.url ? (
          <a className="sourcing-item-title" href={box.url} target="_blank" rel="noopener noreferrer">{box.title}</a>
        ) : (
          <span className="sourcing-item-title">{box.title}</span>
        )}
        <div className="sourcing-item-reason">
          {[boxStoreName(box.store), bought ? `bought ${bought}` : null, boxProgress(box)].filter(Boolean).join(" · ")}
          {box.median_days != null ? ` · ${formatDays(box.median_days)} to sell` : ""}
        </div>
        <div className="bought-fields">
          <span className="sourcing-setting">
            Box
            <DraftInput
              value={String(box.price)}
              label={`Price paid for ${box.title}`}
              prefix="$"
              width="5rem"
              inputMode="decimal"
              disabled={saving}
              clean={(text) => text.replace(/[^\d.]/g, "")}
              accept={money}
              onCommit={(text) => onChange({ price: Number(text) })}
            />
          </span>
          <span className="sourcing-setting">
            Shipping
            <DraftInput
              value={String(box.shipping)}
              label={`Shipping paid for ${box.title}`}
              prefix="$"
              width="5.5rem"
              inputMode="decimal"
              disabled={saving}
              clean={(text) => text.replace(/[^\d.]/g, "")}
              accept={money}
              onCommit={(text) => onChange({ shipping: Number(text) })}
            />
          </span>
          <span className="sourcing-setting">
            Pieces
            <DraftInput
              value={box.pieces ? String(box.pieces) : ""}
              label={`Pieces in ${box.title}`}
              width="3.5rem"
              inputMode="numeric"
              disabled={saving}
              clean={(text) => text.replace(/\D/g, "")}
              accept={() => true}
              onCommit={(text) => onChange({ pieces: text ? Number(text) : null })}
            />
          </span>
          {box.cost_per_piece != null ? (
            <span className="sourcing-hint">{formatMoney(box.cost_per_piece)} a piece</span>
          ) : null}
          <button type="button" className="sourcing-link bought-remove" onClick={onRemove}>Remove</button>
        </div>
      </div>
      <div className="sourcing-item-money">
        <div>{formatMoney(Math.round(box.spent))} in</div>
        <div>{formatMoney(Math.round(box.returned))} back</div>
        <div className={box.profit >= 0 ? "sourcing-profit" : "sourcing-loss"}>
          {box.profit >= 0 ? "+" : "−"}{formatMoney(Math.abs(Math.round(box.profit)))}
        </div>
        {box.unsold_asking > 0 ? (
          <div className="sourcing-item-why">{formatMoney(Math.round(box.unsold_asking))} still listed</div>
        ) : null}
      </div>
    </li>
  );
}

function AddBoxForm({
  saving,
  onCancel,
  onSave,
}: {
  saving: boolean;
  onCancel: () => void;
  onSave: (box: SourceBoxInput) => void;
}) {
  const [store, setStore] = useState("Raghouse");
  const [title, setTitle] = useState("");
  const [price, setPrice] = useState("");
  const [shipping, setShipping] = useState("");
  const [pieces, setPieces] = useState("");
  const valid = store.trim() && title.trim() && price !== "" && Number(price) >= 0 && Number(shipping || 0) >= 0;
  return (
    <form
      className="bought-add"
      onSubmit={(event) => {
        event.preventDefault();
        if (!valid || saving) return;
        onSave({
          store: boxStoreKey(store),
          title: title.trim(),
          price: Number(price),
          shipping: Number(shipping || 0),
          pieces: pieces ? Number(pieces) : null,
        });
      }}
    >
      <label className="bought-add-field">
        <span className="label">Store</span>
        <input className="input input-sm" list="bought-stores" value={store} onChange={(event) => setStore(event.target.value)} />
        <datalist id="bought-stores">
          <option value="Raghouse" />
          <option value="Thrift Vintage Fashion" />
        </datalist>
      </label>
      <label className="bought-add-field is-wide">
        <span className="label">Box</span>
        <input
          className="input input-sm"
          placeholder="Carhartt mix 25 pcs"
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          autoFocus
        />
      </label>
      <label className="bought-add-field">
        <span className="label">Price</span>
        <input className="input input-sm" inputMode="decimal" value={price} onChange={(event) => setPrice(event.target.value.replace(/[^\d.]/g, ""))} />
      </label>
      <label className="bought-add-field">
        <span className="label">Shipping</span>
        <input className="input input-sm" inputMode="decimal" value={shipping} onChange={(event) => setShipping(event.target.value.replace(/[^\d.]/g, ""))} />
      </label>
      <label className="bought-add-field">
        <span className="label">Pieces</span>
        <input className="input input-sm" inputMode="numeric" value={pieces} onChange={(event) => setPieces(event.target.value.replace(/\D/g, ""))} />
      </label>
      <div className="bought-add-actions">
        <button type="button" className="btn btn-ghost btn-sm" onClick={onCancel}>Cancel</button>
        <button type="submit" className="btn btn-primary btn-sm" disabled={!valid || saving}>Add box</button>
      </div>
    </form>
  );
}
