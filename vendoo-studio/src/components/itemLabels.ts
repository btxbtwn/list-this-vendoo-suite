export function splitLabels(raw: string): string[] {
  return raw.split(",").map((part) => part.trim()).filter(Boolean);
}

export function joinLabels(labels: string[]): string {
  return labels.join(", ");
}

export function removeLabel(raw: string, target: string): string {
  const needle = target.trim().toLowerCase();
  if (!needle) return raw;
  return joinLabels(splitLabels(raw).filter((label) => label.toLowerCase() !== needle));
}

export function addLabel(raw: string, addition: string): string {
  const next = addition.trim();
  if (!next) return joinLabels(splitLabels(raw));
  const existing = splitLabels(raw);
  if (existing.some((label) => label.toLowerCase() === next.toLowerCase())) {
    return joinLabels(existing);
  }
  return joinLabels([...existing, next]);
}
